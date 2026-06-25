from __future__ import annotations

import threading
import time

from cloud.app.agent_service.hermes_official import (
    chat_with_hermes_gateway,
    chat_with_hermes_official,
    run_hermes_gateway_prompt,
)
from cloud.app.agent_service.orchestrator import AgentOrchestrator
from cloud.app.api.web_routes import (
    WebObservationQuery,
    _build_observation_query_response,
    _device_freshness,
    _format_sample_timestamp,
    _bound_device_context,
    _normalize_device_presence_claim,
    _registered_settings_for_device,
    _sanitize_hermes_readonly_answer,
    _try_disabled_web_hardware_action,
    _try_llm_first_web_hardware_action,
    _try_llm_first_web_readonly_action,
    _web_device_context,
)
from cloud.app.config import Settings
from cloud.app.device_state.store import device_state_store
from cloud.app.device_registry import DeviceRegistry
from cloud.app.model_config import effective_model_settings
from cloud.app.module_binding_store import ModuleBindingStore, module_binding_public_view
from cloud.app.qqbot import QQBotMessageEvent
from cloud.app.server_context import _find_sample, _message_payload, knowledge_catalog, latest_aht20_observation


_CONVERSATION_HISTORY: dict[str, list[dict[str, object]]] = {}
_HERMES_SESSION_IDS: dict[str, str] = {}
_CONVERSATION_LOCK = threading.Lock()


def generate_qqbot_reply(
    event: QQBotMessageEvent,
    settings: Settings,
    orchestrator: AgentOrchestrator,
    registry: DeviceRegistry,
) -> str:
    selected_device_id = _select_qqbot_device_id(settings, registry)
    effective_settings = _registered_settings_for_device(settings, registry, selected_device_id)
    effective_settings = effective_model_settings(effective_settings)
    hardware_control_enabled = qqbot_hardware_control_allowed(event, effective_settings)
    conversation_history = _conversation_history_for_turn(event.conversation_key, event.text)
    provider = effective_settings.llm_provider.lower()
    automation_context = {
        "owner_channel": "qq_group" if event.group_openid else "qq_c2c",
        "owner_id": event.conversation_key,
        "conversation_id": event.group_openid or event.user_openid,
        "device_id": effective_settings.device_id,
        "control_enabled": hardware_control_enabled,
    }

    if hardware_control_enabled:
        response = _try_llm_first_web_hardware_action(
            event.text,
            effective_settings,
            orchestrator,
            conversation_history=conversation_history,
            automation_context=automation_context,
        )
        action_kind = _response_action_kind(response)
        if action_kind not in {"", "none", "observation_query"}:
            assistant_message = _finalize_qqbot_response(event.text, response, effective_settings)
            return _store_conversation_reply(event.conversation_key, event.text, assistant_message)
        grounded_response = _try_qqbot_hermes_grounded_reply(
            event,
            effective_settings,
            conversation_history=conversation_history,
        )
        if grounded_response is not None:
            assistant_message = _finalize_qqbot_response(event.text, grounded_response, effective_settings)
            return _store_conversation_reply(event.conversation_key, event.text, assistant_message)
        assistant_message = _finalize_qqbot_response(event.text, response, effective_settings)
        return _store_conversation_reply(event.conversation_key, event.text, assistant_message)

    if provider in {"deepseek", "hermes_official"}:
        structured_response = _try_disabled_web_hardware_action(
            event.text,
            effective_settings,
            conversation_history=conversation_history,
            automation_context=automation_context,
        )
        if structured_response is not None:
            assistant_message = _finalize_qqbot_response(event.text, structured_response, effective_settings)
            return _store_conversation_reply(event.conversation_key, event.text, assistant_message)

    grounded_response = _try_qqbot_hermes_grounded_reply(
        event,
        effective_settings,
        conversation_history=conversation_history,
    )
    if grounded_response is not None:
        assistant_message = _finalize_qqbot_response(event.text, grounded_response, effective_settings)
        return _store_conversation_reply(event.conversation_key, event.text, assistant_message)

    if provider in {"deepseek", "hermes_official"}:
        response = _try_llm_first_web_readonly_action(
            event.text,
            effective_settings,
            conversation_history=conversation_history,
            conversation_key=event.conversation_key,
        )
        assistant_message = _finalize_qqbot_response(event.text, response, effective_settings)
        return _store_conversation_reply(event.conversation_key, event.text, assistant_message)

    binding_store = ModuleBindingStore(effective_settings)
    device_snapshot, _freshness, topology, bindings, diagnostics = _bound_device_context(
        effective_settings,
        binding_store,
    )
    context = {
        "project_root": "/home/admin/embedded-agent",
        "knowledge_catalog": knowledge_catalog(limit=40),
        "signal_model": topology,
        "latest_device_state": device_snapshot,
        "diagnostics": diagnostics,
        "module_bindings": [
            view for view in (module_binding_public_view(item) for item in bindings) if view is not None
        ],
        "hardware_control_enabled": hardware_control_enabled,
        "qqbot_event_type": event.event_type,
        "qqbot_group_message": bool(event.group_openid),
    }
    if effective_settings.hermes_gateway_url:
        assistant_message = chat_with_hermes_gateway(
            event.text,
            effective_settings,
            conversation=event.conversation_key,
            context=context,
        )
        assistant_message = _normalize_device_presence_claim(assistant_message, effective_settings)
        return _store_conversation_reply(event.conversation_key, event.text, assistant_message)

    result = chat_with_hermes_official(
        event.text,
        effective_settings,
        session_id=_HERMES_SESSION_IDS.get(event.conversation_key) or None,
        device_context=context,
    )
    _HERMES_SESSION_IDS[event.conversation_key] = result.session_id
    assistant_message = _normalize_device_presence_claim(result.assistant_message, effective_settings)
    return _store_conversation_reply(event.conversation_key, event.text, assistant_message)


def _response_action_kind(response: dict[str, object]) -> str:
    hardware_control = response.get("hardware_control")
    if not isinstance(hardware_control, dict):
        return ""
    return str(hardware_control.get("action_kind") or "").strip()


def _select_qqbot_device_id(settings: Settings, registry: DeviceRegistry) -> str:
    registry.ensure_default_device()
    freshest_device_id = ""
    freshest_last_seen = -1.0
    for device in registry.list_devices():
        device_id = str(device.get("device_id") or "").strip()
        if not device_id:
            continue
        snapshot = device_state_store.snapshot(device_id)
        freshness = _device_freshness(snapshot)
        last_seen = snapshot.get("last_seen")
        if not freshness["online"] or not isinstance(last_seen, (int, float)):
            continue
        if float(last_seen) > freshest_last_seen:
            freshest_device_id = device_id
            freshest_last_seen = float(last_seen)
    return freshest_device_id or settings.device_id


def qqbot_hardware_control_allowed(event: QQBotMessageEvent, settings: Settings) -> bool:
    if not settings.qqbot_hardware_control_enabled:
        return False
    if event.event_type == "GROUP_AT_MESSAGE_CREATE" and not settings.qqbot_allow_group_commands:
        return False
    allowed_users = _clean_csv_values(settings.qqbot_allowed_user_openids)
    if allowed_users and event.user_openid not in allowed_users:
        return False
    allowed_groups = _clean_csv_values(settings.qqbot_allowed_group_openids)
    if event.group_openid and allowed_groups and event.group_openid not in allowed_groups:
        return False
    return True


def _try_qqbot_hermes_grounded_reply(
    event: QQBotMessageEvent,
    settings: Settings,
    *,
    conversation_history: list[dict[str, object]],
) -> dict[str, object] | None:
    if not settings.hermes_gateway_url.strip():
        return None

    snapshot_response = _build_observation_query_response(
        settings,
        query=WebObservationQuery(
            devices=["AHT20", "BH1750"],
            capabilities=["env.temperature", "env.humidity", "env.light.lux"],
        ),
        source="qqbot_grounded_uploaded_data_context",
        confidence=1.0,
    )
    uploaded_data_summary = dict(snapshot_response.get("hardware_control", {})).get("result", {})
    if not isinstance(uploaded_data_summary, dict):
        uploaded_data_summary = {}

    context = _web_device_context(settings)
    context["uploaded_data_summary"] = uploaded_data_summary
    context["conversation_history"] = [
        {
            "role": str(item.get("role") or ""),
            "content": str(item.get("content") or "")[:400],
            "created_at": item.get("created_at"),
        }
        for item in conversation_history[-12:]
        if isinstance(item, dict)
    ]
    context["qqbot_event"] = {
        "event_type": event.event_type,
        "conversation_key": event.conversation_key,
        "group_message": bool(event.group_openid),
    }

    try:
        assistant_message = run_hermes_gateway_prompt(
            event.text,
            settings,
            conversation=event.conversation_key,
            instructions=(
                "You are the QQ bot conversation assistant for the RA8P1 project. "
                "Answer in Chinese unless the user asks otherwise. "
                "First understand the user's natural-language intent from the current message plus "
                "conversation_history. Then answer strictly from uploaded_data_summary, latest_device_state, "
                "diagnostics, and signal_model. Treat those uploaded values as the authoritative server-side "
                "state. Never invent measurements, freshness, online status, hardware actions, background jobs, "
                "or monitoring tasks. Structured control and task requests are handled before this freeform step. "
                "If the user asks for current sensor data, quote only the latest uploaded "
                "values that are actually present. If a requested value is missing, stale, or offline, say so "
                "directly. Do not claim a control or task was created from this freeform answer. "
                "Do not return JSON."
            ),
            context=context,
            store=True,
        )
    except Exception:
        return None

    normalized_message = assistant_message.strip()
    if not normalized_message:
        return None
    normalized_message = _sanitize_hermes_readonly_answer(normalized_message, uploaded_data_summary)

    return {
        "ok": True,
        "assistant_message": _normalize_device_presence_claim(normalized_message, settings),
        "source": "qqbot:hermes_grounded_uploaded_data",
        "created_at": int(time.time()),
        "hardware_control": {
            "enabled": False,
            "read_only": True,
            "action_kind": "none",
            "intent_source": "qqbot_model_grounded_uploaded_data",
            "intent_confidence": 1.0,
            "reasoning_summary": "QQBot Hermes freeform answer grounded on uploaded live data",
            "tool_trace": ["qqbot_hermes_grounded_uploaded_data"],
            "uploaded_data_summary": uploaded_data_summary,
        },
    }


def _conversation_history_for_turn(conversation_key: str, text: str) -> list[dict[str, object]]:
    with _CONVERSATION_LOCK:
        history = list(_CONVERSATION_HISTORY.get(conversation_key, []))
    history.append({"role": "user", "content": text, "created_at": int(time.time())})
    return history[-24:]


def _store_conversation_reply(conversation_key: str, user_text: str, assistant_text: str) -> str:
    with _CONVERSATION_LOCK:
        history = _CONVERSATION_HISTORY.setdefault(conversation_key, [])
        history.append({"role": "user", "content": user_text, "created_at": int(time.time())})
        history.append({"role": "assistant", "content": assistant_text, "created_at": int(time.time())})
        if len(history) > 24:
            del history[:-24]
    return str(assistant_text)


def _clean_csv_values(raw: str) -> set[str]:
    return {
        item.strip()
        for item in raw.split(",")
        if item.strip()
    }


def _try_qqbot_direct_observation_reply(text: str, settings: Settings) -> str | None:
    normalized = text.strip().lower()
    wants_read = any(token in normalized for token in ("读取", "查询", "查看", "回传", "获取", "现在", "当前", "在线", "状态"))
    wants_temp_humidity = any(token in normalized for token in ("aht20", "温湿度", "温度", "湿度"))
    wants_light = any(token in normalized for token in ("光照", "亮度", "lux", "照度", "bh1750"))
    wants_status = any(token in normalized for token in ("在线", "状态", "设备情况", "设备状态"))

    if not (wants_read or wants_temp_humidity or wants_light or wants_status):
        return None

    snapshot = device_state_store.snapshot(settings.device_id)
    freshness = _device_freshness(snapshot)
    parts: list[str] = []

    if wants_status and not (wants_temp_humidity or wants_light):
        if freshness["online"]:
            parts.append(
                f"云端当前看到设备 `{settings.device_id}` 在线，最近一次上报时间是 {_format_sample_timestamp(snapshot.get('last_seen'))}。"
            )
        else:
            if snapshot.get("last_seen") is None:
                parts.append(
                    f"云端当前没有看到设备 `{settings.device_id}` 在线。`last_seen` 为空，说明服务器还没有收到这台设备的上电或遥测上报。"
                )
            else:
                parts.append(
                    f"云端当前没有看到设备 `{settings.device_id}` 在线。最近一次上报时间是 {_format_sample_timestamp(snapshot.get('last_seen'))}，已经不是实时状态。"
                )

    if wants_temp_humidity:
        response = _build_observation_query_response(
            settings,
            user_text=text,
            source="qqbot:direct_observation_query",
            confidence=1.0,
            reasoning_summary="deterministic qqbot observation route",
        )
        parts.append(_finalize_qqbot_response(text, response, settings))

    if wants_light:
        parts.append(_build_light_observation_reply(settings))

    if not parts:
        return None
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def _build_light_observation_reply(settings: Settings) -> str:
    snapshot = device_state_store.snapshot(settings.device_id)
    freshness = _device_freshness(snapshot)
    sample, sample_timestamp = _latest_light_sample(snapshot)
    if not freshness["online"]:
        if snapshot.get("last_seen") is None:
            return (
                f"云端当前没有收到设备 `{settings.device_id}` 的实时光照上报，"
                "所以我不能返回当前 lux。现在设备看起来还没有上电，或者尚未重新连上 MQTT / 云端。"
            )
        return (
            f"云端当前没有收到设备 `{settings.device_id}` 的实时光照上报，"
            f"最近一次设备上报时间是 {_format_sample_timestamp(snapshot.get('last_seen'))}，不能代表现在。"
        )
    if sample is None:
        return "云端当前没有收到光照模块的在线 lux 样本，所以我不能编造当前光照值。"
    value = sample.get("value")
    unit = str(sample.get("unit") or "lux")
    return f"已读取光照模块最近一次实时上报：光照 {value} {unit}。"


def _latest_light_sample(snapshot: dict[str, object]) -> tuple[dict[str, object] | None, object]:
    candidates: list[tuple[float, dict[str, object]]] = []
    for message in (snapshot.get("last_telemetry"), snapshot.get("last_status")):
        payload = _message_payload(message)
        for capability_id in ("env.light.lux", "env.illuminance"):
            sample = _find_sample(payload, capability_id, port_id="i2c.s1", module_type="BH1750")
            if sample:
                timestamp = sample.get("ts_ms")
                score = float(timestamp) if isinstance(timestamp, (int, float)) else 0.0
                candidates.append((score, sample))
    if not candidates:
        return None, None
    sample = max(candidates, key=lambda item: item[0])[1]
    return sample, sample.get("ts_ms")


def _finalize_qqbot_response(user_text: str, response: dict[str, object], settings: Settings) -> str:
    assistant_message = _normalize_device_presence_claim(str(response.get("assistant_message") or ""), settings)
    hardware_control = response.get("hardware_control")
    if not isinstance(hardware_control, dict):
        return assistant_message

    action_kind = str(hardware_control.get("action_kind") or "")
    if action_kind != "observation_query":
        return assistant_message

    result = hardware_control.get("result")
    result = result if isinstance(result, dict) else {}
    observations = result.get("observations")
    if isinstance(observations, dict) and observations:
        observation_items = [
            item for item in observations.values() if isinstance(item, dict)
        ]
        if not observation_items:
            return assistant_message
        if all(
            bool(item.get("fresh")) and bool(item.get("device_online")) and bool(item.get("sample_online"))
            for item in observation_items
        ):
            return assistant_message
        if any(bool(item.get("fresh")) for item in observation_items):
            return assistant_message

    fresh = bool(result.get("fresh"))
    device_online = bool(result.get("device_online"))
    sample_online = bool(result.get("sample_online"))
    if fresh and device_online and sample_online:
        return assistant_message

    snapshot = device_state_store.snapshot(settings.device_id)
    sample_time = str(result.get("sample_time") or "未知")
    if snapshot.get("last_seen") is None:
        return (
            f"云端当前没有收到设备 `{settings.device_id}` 的实时上报，"
            "所以我不能把温湿度当成当前值返回。"
            "现在设备看起来还没有上电，或者尚未重新连上 MQTT / 云端。"
        )
    return (
        f"云端当前没有收到设备 `{settings.device_id}` 的实时上报，"
        "所以我不能把缓存读数当成当前值返回。"
        f"最近一次历史样本时间是 {sample_time}，但它只能算历史记录，不能代表现在。"
    )
