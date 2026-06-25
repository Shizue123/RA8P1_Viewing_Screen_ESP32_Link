from __future__ import annotations

import hashlib
import re
import secrets
import time
from typing import Any
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from cloud.app.agent_service.action_plan import interpret_text_to_rule_program
from cloud.app.agent_service.hermes_official import (
    chat_with_hermes_gateway,
    chat_with_hermes_official,
    run_hermes_gateway_prompt,
)
from cloud.app.agent_service.orchestrator import AgentOrchestrator
from cloud.app.agent_service.web_hardware_agent import (
    WebHardwareDecision,
    WebObservationQuery,
    decide_web_hardware_action,
    synthesize_observation_reply,
)
from cloud.app.automation_tasks import (
    automation_next_run,
    automation_task_from_text,
    contextual_automation_task_from_text,
    get_automation_task_service,
)
from cloud.app.api.routes import _delivery_stage_label, _device_diagnostics, _finalize_web_deploy_view
from cloud.app.auth import (
    AuthStore,
    AuthenticatedUser,
    ChangePasswordRequest,
    CreateUserRequest,
    LoginRequest,
    clear_session_cookie,
    set_session_cookie,
)
from cloud.app.config import Settings, get_settings
from cloud.app.device_state.store import device_state_store
from cloud.app.device_registry import DeviceRegistry
from cloud.app.models import ProgramDeployRequest
from cloud.app.models import RuleProgram
from cloud.app.models import MqttEnvelope
from cloud.app.module_binding_store import (
    ModuleBindingStore,
    apply_bindings_to_diagnostics,
    apply_bindings_to_signal_topology,
    module_binding_public_view,
)
from cloud.app.model_config import (
    ModelProfileRequest,
    ModelSelectionRequest,
    create_model_profile,
    delete_model_profile,
    effective_model_settings,
    model_config_view,
    update_model_selection,
)
from cloud.app.mqtt_service.client import MqttPublisher
from cloud.app.security import build_script_signature
from cloud.app.server_context import (
    _find_sample,
    _message_payload,
    knowledge_catalog,
    latest_aht20_observation,
    signal_topology,
)


router = APIRouter()
_LOCAL_TZ = ZoneInfo("Asia/Shanghai")


class WebChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    conversation_id: str = Field(min_length=8, max_length=64)
    device_id: str | None = Field(default=None, min_length=1, max_length=64)


class ConversationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    is_pinned: bool | None = None


class DeviceRegistrationRequest(BaseModel):
    ra8p1_uid: str = Field(default="", max_length=64)
    esp32_mac: str = Field(default="", max_length=32)
    esp32_chip_id: str = Field(default="", max_length=64)
    label: str = Field(default="", max_length=80)
    bootstrap_secret: str = Field(default="", max_length=128)


class ModuleBindingConfirmRequest(BaseModel):
    device_id: str | None = Field(default=None, min_length=1, max_length=64)
    port_id: str = Field(min_length=1, max_length=64)
    binding_key: str = Field(default="", max_length=128)
    option_id: str = Field(min_length=1, max_length=64)


def get_auth_store(settings: Settings = Depends(get_settings)) -> AuthStore:
    return AuthStore(settings)


def get_orchestrator(settings: Settings = Depends(get_settings)) -> AgentOrchestrator:
    return AgentOrchestrator(settings, MqttPublisher(settings))


def get_device_registry(settings: Settings = Depends(get_settings)) -> DeviceRegistry:
    return DeviceRegistry(settings)


def get_module_binding_store(settings: Settings = Depends(get_settings)) -> ModuleBindingStore:
    return ModuleBindingStore(settings)


def current_user(
    request: Request,
    store: AuthStore = Depends(get_auth_store),
) -> AuthenticatedUser:
    return store.authenticate(request)


def csrf_user(
    request: Request,
    store: AuthStore = Depends(get_auth_store),
) -> AuthenticatedUser:
    return store.authenticate(request, require_csrf=True)


def admin_user(user: AuthenticatedUser = Depends(csrf_user)) -> AuthenticatedUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="administrator role required")
    return user


def _registered_settings_for_device(settings: Settings, registry: DeviceRegistry, device_id: str | None) -> Settings:
    if not hasattr(registry, "ensure_default_device"):
        registry = DeviceRegistry(settings)
    registry.ensure_default_device()
    clean_device_id = _clean_device_id(device_id) or settings.device_id
    if registry.get(clean_device_id) is None:
        raise HTTPException(status_code=404, detail="device not registered")
    return settings.model_copy(update={"device_id": clean_device_id})


def _clean_device_id(value: str | None) -> str:
    if value is None or not isinstance(value, str):
        return ""
    return "".join(ch for ch in value.strip() if ch.isalnum() or ch in "-_:.")[:64]


def _clean_binding_key(value: str | None) -> str:
    if value is None or not isinstance(value, str):
        return ""
    return "".join(ch for ch in value.strip() if ch.isalnum() or ch in "-_:.")[:128]


def _device_view(registry: DeviceRegistry, device_id: str, snapshot: dict[str, object] | None = None) -> dict[str, object]:
    device = registry.get(device_id) or {"device_id": device_id, "label": device_id, "status": "observed"}
    snapshot = snapshot or device_state_store.snapshot(device_id)
    freshness = _device_freshness(snapshot)
    return {
        "device_id": device_id,
        "label": device.get("label") or device_id,
        "status": device.get("status") or "unknown",
        "source": device.get("source") or "unknown",
        "ra8p1_uid": device.get("ra8p1_uid") or "",
        "esp32_mac": device.get("esp32_mac") or "",
        "esp32_chip_id": device.get("esp32_chip_id") or "",
        "first_seen": device.get("first_seen"),
        "last_seen": snapshot.get("last_seen") or device.get("last_seen"),
        "online": freshness["online"],
        "age_sec": freshness["age_sec"],
        "channels": sorted((snapshot.get("channels") or {}).keys())
        if isinstance(snapshot.get("channels"), dict)
        else [],
    }


def _bound_device_context(
    settings: Settings,
    binding_store: ModuleBindingStore,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], list[dict[str, object]], dict[str, object]]:
    device_snapshot = device_state_store.snapshot(settings.device_id)
    freshness = _device_freshness(device_snapshot)
    device_snapshot["_now"] = int(time.time())
    device_snapshot["_device_online"] = freshness["online"]
    bindings = binding_store.list_for_device(settings.device_id)
    topology = apply_bindings_to_signal_topology(signal_topology(device_snapshot), bindings)
    diagnostics = apply_bindings_to_diagnostics(_device_diagnostics(device_snapshot), bindings)
    return device_snapshot, freshness, topology, bindings, diagnostics


def _find_channel_endpoint(topology: dict[str, object], port_id: str) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    channels = topology.get("channels")
    if not isinstance(channels, list):
        return None, None
    for channel in channels:
        if not isinstance(channel, dict):
            continue
        if str(channel.get("id") or "").strip() != port_id:
            continue
        hardware = channel.get("hardware")
        if not isinstance(hardware, list):
            return channel, None
        for endpoint in hardware:
            if isinstance(endpoint, dict):
                return channel, endpoint
        return channel, None
    return None, None


@router.get("/auth/session")
def auth_session(
    request: Request,
    store: AuthStore = Depends(get_auth_store),
) -> dict[str, object]:
    try:
        user = store.authenticate(request)
    except HTTPException:
        return {"authenticated": False, "bootstrap_required": store.bootstrap_required()}
    return {
        "authenticated": True,
        "bootstrap_required": False,
        "user": user.public(),
        "csrf_token": user.csrf_token,
    }


@router.post("/auth/bootstrap")
def auth_bootstrap(
    payload: LoginRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
    store: AuthStore = Depends(get_auth_store),
) -> dict[str, object]:
    store.register_first_admin(payload.username, payload.password)
    token, user = store.login(payload.username, payload.password)
    set_session_cookie(response, settings, token)
    return {"ok": True, "user": user.public(), "csrf_token": user.csrf_token}


@router.post("/auth/login")
def auth_login(
    payload: LoginRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
    store: AuthStore = Depends(get_auth_store),
) -> dict[str, object]:
    token, user = store.login(payload.username, payload.password)
    set_session_cookie(response, settings, token)
    return {"ok": True, "user": user.public(), "csrf_token": user.csrf_token}


@router.post("/auth/logout")
def auth_logout(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    store: AuthStore = Depends(get_auth_store),
    _user: AuthenticatedUser = Depends(csrf_user),
) -> dict[str, object]:
    store.logout(request)
    clear_session_cookie(response, settings)
    return {"ok": True}


@router.get("/auth/users")
def auth_users(
    store: AuthStore = Depends(get_auth_store),
    user: AuthenticatedUser = Depends(current_user),
) -> dict[str, object]:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="administrator role required")
    return {"ok": True, "users": store.list_users()}


@router.post("/auth/users")
def auth_create_user(
    payload: CreateUserRequest,
    store: AuthStore = Depends(get_auth_store),
    _admin: AuthenticatedUser = Depends(admin_user),
) -> dict[str, object]:
    return {"ok": True, "user": store.create_user(payload.username, payload.password, payload.role)}


@router.delete("/auth/users/{user_id}")
def auth_delete_user(
    user_id: int,
    store: AuthStore = Depends(get_auth_store),
    admin: AuthenticatedUser = Depends(admin_user),
) -> dict[str, object]:
    return {"ok": True, "user": store.delete_user(admin, user_id)}


@router.post("/auth/password")
def auth_change_password(
    payload: ChangePasswordRequest,
    store: AuthStore = Depends(get_auth_store),
    user: AuthenticatedUser = Depends(csrf_user),
) -> dict[str, object]:
    store.change_password(user, payload.current_password, payload.new_password)
    return {"ok": True, "reauthenticate": True}


@router.get("/web/context")
def web_context(
    device_id: str | None = Query(default=None, max_length=64),
    settings: Settings = Depends(get_settings),
    registry: DeviceRegistry = Depends(get_device_registry),
    binding_store: ModuleBindingStore = Depends(get_module_binding_store),
    user: AuthenticatedUser = Depends(current_user),
) -> dict[str, object]:
    settings = _registered_settings_for_device(settings, registry, device_id)
    effective_settings = effective_model_settings(settings)
    control_enabled = _web_hardware_control_allowed(effective_settings, user)
    device_snapshot, freshness, topology, bindings, diagnostics = _bound_device_context(settings, binding_store)
    time_alignment = _device_web_time_alignment(device_snapshot)
    return {
        "ok": True,
        "user": user.public(),
        "device_id": settings.device_id,
        "devices": [
            _device_view(registry, str(device.get("device_id") or ""))
            for device in registry.list_devices()
            if device.get("device_id")
        ],
        "signal_topology": topology,
        "module_bindings": [
            view for view in (module_binding_public_view(item) for item in bindings) if view is not None
        ],
        "diagnostics": diagnostics,
        "model_config": model_config_view(settings),
        "device_state": {
            "device_id": device_snapshot.get("device_id"),
            "last_seen": device_snapshot.get("last_seen"),
            "online": freshness["online"],
            "age_sec": freshness["age_sec"],
            "stale_after_sec": freshness["stale_after_sec"],
            "channels": sorted((device_snapshot.get("channels") or {}).keys())
            if isinstance(device_snapshot.get("channels"), dict)
            else [],
            "time_alignment": time_alignment,
        },
        "scope": {
            "hardware_control_enabled": control_enabled,
            "message": (
                "已启用管理员硬件控制入口。"
                if control_enabled
                else "当前阶段仅启用对话与资料检索。"
            ),
        },
    }


@router.get("/web/devices")
def web_devices(
    registry: DeviceRegistry = Depends(get_device_registry),
    _user: AuthenticatedUser = Depends(current_user),
) -> dict[str, object]:
    return {
        "ok": True,
        "devices": [
            _device_view(registry, str(device.get("device_id") or ""))
            for device in registry.list_devices()
            if device.get("device_id")
        ],
    }


@router.post("/web/module-bindings/confirm")
def web_confirm_module_binding(
    payload: ModuleBindingConfirmRequest,
    settings: Settings = Depends(get_settings),
    registry: DeviceRegistry = Depends(get_device_registry),
    binding_store: ModuleBindingStore = Depends(get_module_binding_store),
    user: AuthenticatedUser = Depends(csrf_user),
) -> dict[str, object]:
    settings = _registered_settings_for_device(settings, registry, payload.device_id)
    _device_snapshot, _freshness, topology, _bindings, _diagnostics = _bound_device_context(settings, binding_store)
    clean_port_id = _clean_device_id(payload.port_id)
    _channel, endpoint = _find_channel_endpoint(topology, clean_port_id)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="port not found in current device context")
    metadata = endpoint.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    options = metadata.get("binding_options")
    options = options if isinstance(options, list) else []
    if not options:
        raise HTTPException(status_code=422, detail="this port does not currently accept manual module confirmation")
    option_ids = {
        str(item.get("id") or "").strip()
        for item in options
        if isinstance(item, dict) and item.get("id")
    }
    if payload.option_id not in option_ids:
        raise HTTPException(status_code=422, detail="unsupported module option for this port")
    binding_key = _clean_binding_key(payload.binding_key) or str(metadata.get("binding_key") or clean_port_id)
    try:
        binding = binding_store.confirm(
            device_id=settings.device_id,
            port_id=clean_port_id,
            binding_key=binding_key,
            option_id=payload.option_id,
            confirmed_by=user.username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ok": True,
        "device_id": settings.device_id,
        "binding": module_binding_public_view(binding),
    }


@router.post("/devices/register")
def register_device(
    payload: DeviceRegistrationRequest,
    settings: Settings = Depends(get_settings),
    registry: DeviceRegistry = Depends(get_device_registry),
) -> dict[str, object]:
    expected_secret = settings.device_registration_secret.strip()
    if expected_secret and payload.bootstrap_secret != expected_secret:
        raise HTTPException(status_code=401, detail="invalid device registration secret")
    try:
        device = registry.register(
            ra8p1_uid=payload.ra8p1_uid,
            esp32_mac=payload.esp32_mac,
            esp32_chip_id=payload.esp32_chip_id,
            label=payload.label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ok": True,
        "device": device,
        "device_id": device["device_id"],
        "device_secret": device.get("device_secret", ""),
    }


@router.get("/web/model-config")
def web_model_config(
    settings: Settings = Depends(get_settings),
    _user: AuthenticatedUser = Depends(current_user),
) -> dict[str, object]:
    return {"ok": True, "model_config": model_config_view(settings)}


@router.post("/web/model-config")
def web_update_model_config(
    payload: ModelSelectionRequest,
    settings: Settings = Depends(get_settings),
    _admin: AuthenticatedUser = Depends(admin_user),
) -> dict[str, object]:
    try:
        updated = update_model_selection(settings, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "model_config": updated}


@router.post("/web/model-config/profiles")
def web_create_model_profile(
    payload: ModelProfileRequest,
    settings: Settings = Depends(get_settings),
    _admin: AuthenticatedUser = Depends(admin_user),
) -> dict[str, object]:
    updated = create_model_profile(settings, payload)
    return {"ok": True, "model_config": updated}


@router.delete("/web/model-config/profiles/{provider}/{model}")
def web_delete_model_profile(
    provider: str,
    model: str,
    settings: Settings = Depends(get_settings),
    _admin: AuthenticatedUser = Depends(admin_user),
) -> dict[str, object]:
    updated = delete_model_profile(settings, provider, model)
    return {"ok": True, "model_config": updated}


@router.post("/web/chat")
def web_chat(
    payload: WebChatRequest,
    settings: Settings = Depends(get_settings),
    store: AuthStore = Depends(get_auth_store),
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    user: AuthenticatedUser = Depends(csrf_user),
    registry: DeviceRegistry = Depends(get_device_registry),
    binding_store: ModuleBindingStore = Depends(get_module_binding_store),
) -> dict[str, object]:
    settings = _registered_settings_for_device(settings, registry, payload.device_id)
    settings = effective_model_settings(settings)
    conversation = store.conversation_for_user(user.id, payload.conversation_id)
    store.append_chat_message(user.id, payload.conversation_id, "user", payload.text)
    hardware_control_enabled = _web_hardware_control_allowed(settings, user)
    provider = settings.llm_provider.lower()
    if hardware_control_enabled:
        conversation_history = store.chat_history(user.id, payload.conversation_id, limit=24)
        hardware_response = _try_llm_first_web_hardware_action(
            payload.text,
            settings,
            orchestrator,
            conversation_history=conversation_history,
            automation_context={
                "owner_channel": "web",
                "owner_id": str(user.id),
                "conversation_id": payload.conversation_id,
                "device_id": settings.device_id,
                "control_enabled": True,
            },
        )
        store.append_chat_message(user.id, payload.conversation_id, "assistant", hardware_response["assistant_message"])
        if hardware_response.get("session_id"):
            store.set_hermes_session(user.id, str(hardware_response["session_id"]))
        return hardware_response
    if provider in {"deepseek", "hermes_official"}:
        conversation_history = store.chat_history(user.id, payload.conversation_id, limit=24)
        disabled_hardware_response = _try_disabled_web_hardware_action(
            payload.text,
            settings,
            conversation_history=conversation_history,
            automation_context={
                "owner_channel": "web",
                "owner_id": str(user.id),
                "conversation_id": payload.conversation_id,
                "device_id": settings.device_id,
                "control_enabled": False,
            },
        )
        if disabled_hardware_response is not None:
            store.append_chat_message(
                user.id,
                payload.conversation_id,
                "assistant",
                disabled_hardware_response["assistant_message"],
            )
            return disabled_hardware_response
        readonly_response = _try_llm_first_web_readonly_action(
            payload.text,
            settings,
            conversation_history=conversation_history,
            conversation_key=f"ra8p1-web-user-{user.id}-{conversation['id']}",
        )
        store.append_chat_message(user.id, payload.conversation_id, "assistant", readonly_response["assistant_message"])
        return readonly_response

    catalog = knowledge_catalog(limit=40)
    device_snapshot, _freshness, topology, bindings, diagnostics = _bound_device_context(settings, binding_store)
    context = {
        "project_root": "/home/admin/embedded-agent",
        "knowledge_catalog": catalog,
        "signal_model": topology,
        "latest_device_state": device_snapshot,
        "diagnostics": diagnostics,
        "module_bindings": [
            view for view in (module_binding_public_view(item) for item in bindings) if view is not None
        ],
        "hardware_control_enabled": hardware_control_enabled,
    }
    try:
        if settings.hermes_gateway_url:
            assistant_message = chat_with_hermes_gateway(
                payload.text,
                settings,
                conversation=f"ra8p1-web-user-{user.id}-{conversation['id']}",
                context=context,
            )
            source = "hermes_gateway"
        else:
            result = chat_with_hermes_official(
                payload.text,
                settings,
                session_id=user.hermes_session_id or None,
                device_context=context,
            )
            assistant_message = result.assistant_message
            store.set_hermes_session(user.id, result.session_id)
            source = "hermes_cli"
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    store.append_chat_message(user.id, payload.conversation_id, "assistant", assistant_message)
    return {
        "ok": True,
        "assistant_message": assistant_message,
        "source": source,
        "created_at": int(time.time()),
        "hardware_control": {
            "enabled": hardware_control_enabled,
            "action_kind": "none",
        },
    }


def _web_device_context(settings: Settings) -> dict[str, object]:
    binding_store = ModuleBindingStore(settings)
    device_snapshot, _freshness, topology, bindings, diagnostics = _bound_device_context(settings, binding_store)
    return {
        "device_id": settings.device_id,
        "signal_model": topology,
        "latest_device_state": device_snapshot,
        "diagnostics": diagnostics,
        "module_bindings": [
            view for view in (module_binding_public_view(item) for item in bindings) if view is not None
        ],
        "hardware_control_enabled": settings.web_hardware_control_enabled,
        "execution_policy": {
            "planner": "llm_first_tool_calling",
            "code_generation": "disabled_for_model",
            "server_validation": "required_before_mqtt",
        },
    }


def _device_web_time_alignment(snapshot: dict[str, object]) -> dict[str, object]:
    server_now = datetime.now(_LOCAL_TZ)
    device_time_text = ""
    for key in ("last_telemetry", "last_status"):
        message = snapshot.get(key)
        payload = message.get("payload") if isinstance(message, dict) else None
        clock = payload.get("clock") if isinstance(payload, dict) else None
        if isinstance(clock, dict) and clock.get("local_iso"):
            device_time_text = str(clock["local_iso"])
            break
    if not device_time_text:
        return {
            "server_time": server_now.isoformat(timespec="seconds"),
            "device_time": None,
            "skew_sec": None,
            "aligned": False,
        }
    try:
        device_time = datetime.fromisoformat(device_time_text)
        if device_time.tzinfo is None:
            device_time = device_time.replace(tzinfo=_LOCAL_TZ)
        skew_sec = round((server_now - device_time).total_seconds(), 1)
    except ValueError:
        return {
            "server_time": server_now.isoformat(timespec="seconds"),
            "device_time": device_time_text,
            "skew_sec": None,
            "aligned": False,
        }
    return {
        "server_time": server_now.isoformat(timespec="seconds"),
        "device_time": device_time.isoformat(timespec="seconds"),
        "skew_sec": skew_sec,
        "aligned": abs(skew_sec) <= 5,
    }


def _resolve_servo_auto_reset(
    text: str,
    settings: Settings,
    automation_context: dict[str, object] | None,
    *,
    explicit_default: bool = False,
) -> bool:
    normalized = _normalize_web_text(text)
    explicit_enable = any(
        token in normalized
        for token in ("自动复位", "自动回中", "回到90", "回到 90", "回中")
    )
    explicit_disable = any(
        token in normalized
        for token in ("不要自动复位", "不要再自动复位", "不自动复位", "保持目标角度", "不要回中")
    )
    if automation_context is None:
        return False if explicit_disable else explicit_enable or explicit_default
    owner_channel = str(automation_context.get("owner_channel") or "")
    owner_id = str(automation_context.get("owner_id") or "")
    conversation_id = str(automation_context.get("conversation_id") or "")
    service = get_automation_task_service(settings)
    if "以后" in normalized and (explicit_enable or explicit_disable):
        service.set_servo_auto_reset_preference(
            owner_channel,
            owner_id,
            conversation_id,
            explicit_enable and not explicit_disable,
        )
    if explicit_disable:
        return False
    if explicit_enable:
        return True
    return service.servo_auto_reset_preference(owner_channel, owner_id, conversation_id)


def _try_servo_preference_only_update(
    text: str,
    settings: Settings,
    automation_context: dict[str, object] | None,
) -> dict[str, object] | None:
    normalized = _normalize_web_text(text)
    if automation_context is None or "以后" not in normalized:
        return None
    has_reset_preference = any(
        token in normalized
        for token in ("自动复位", "自动回中", "不要回中", "不自动复位", "保持目标角度")
    )
    has_action = any(token in normalized for token in ("转动", "旋转", "摆动", "转到"))
    if not has_reset_preference or has_action:
        return None
    enabled = _resolve_servo_auto_reset(text, settings, automation_context)
    return {
        "ok": True,
        "assistant_message": (
            "已记住：这个对话中后续舵机动作都会自动回到 90 度。"
            if enabled
            else "已记住：这个对话中后续舵机动作默认保持目标角度，不自动复位。"
        ),
        "source": "automation_preference_service",
        "created_at": int(time.time()),
        "hardware_control": {
            "enabled": False,
            "action_kind": "none",
            "preference": {"servo_auto_reset": enabled},
        },
    }


def _try_disabled_web_hardware_action(
    text: str,
    settings: Settings,
    *,
    conversation_history: list[dict[str, object]],
    automation_context: dict[str, object] | None = None,
) -> dict[str, object] | None:
    preference_response = _try_servo_preference_only_update(text, settings, automation_context)
    if preference_response is not None:
        return preference_response
    latest_task = None
    if automation_context is not None and _may_reference_existing_task(text):
        latest_task = get_automation_task_service(settings).latest_conversation_task(
            str(automation_context.get("owner_channel") or ""),
            str(automation_context.get("owner_id") or ""),
            str(automation_context.get("conversation_id") or ""),
        )
    parsed_task = contextual_automation_task_from_text(
        text,
        conversation_history=conversation_history,
        latest_task=latest_task,
    )
    if parsed_task is not None and parsed_task.get("operation") == "clarify":
        return _automation_clarification_response(
            str(parsed_task.get("question") or "请补充任务周期。")
        )
    if (
        parsed_task is not None
        and parsed_task.get("operation") in {"update", "cancel", "list"}
        and automation_context is not None
    ):
        return _handle_automation_task(
            text,
            parsed_task,
            settings,
            automation_context=automation_context,
            assistant_message="已结合当前对话中的任务上下文处理。",
            confidence=1.0,
            reasoning_summary="conversation-scoped deterministic task context",
            tool_trace=["conversation_task_context"],
            knowledge_sources=[],
        )
    try:
        decision = decide_web_hardware_action(
            text,
            settings,
            conversation_history=conversation_history,
            device_context=_web_device_context(settings),
        )
    except Exception:
        return None

    if decision.action_kind == "none":
        return None
    if decision.action_kind == "observation_query":
        response = _build_observation_query_response(
            settings,
            query=decision.observation_query,
            user_text=text,
            source="llm_first_web_hardware_agent:read_only_observation",
            confidence=decision.confidence,
            reasoning_summary=decision.reasoning_summary,
            tool_trace=decision.tool_trace,
            knowledge_sources=decision.knowledge_sources,
            conversation_history=conversation_history,
        )
        hardware_control = response.get("hardware_control")
        if isinstance(hardware_control, dict):
            hardware_control["enabled"] = False
            hardware_control["read_only"] = True
        return response

    if decision.action_kind == "automation_task" and automation_context is not None:
        return _handle_automation_task(
            text,
            decision.automation_task,
            settings,
            automation_context=automation_context,
            assistant_message=decision.assistant_message,
            confidence=decision.confidence,
            reasoning_summary=decision.reasoning_summary,
            tool_trace=decision.tool_trace,
            knowledge_sources=decision.knowledge_sources,
        )

    if decision.action_kind in {"manual_action", "rule_program"}:
        return {
            "ok": True,
            "assistant_message": (
                f"{decision.assistant_message}\n\n"
                "当前网页未启用硬件执行，因此这次只保留理解结果，不会向设备下发动作。"
            ),
            "source": "llm_first_web_hardware_agent:control_disabled",
            "created_at": int(time.time()),
            "hardware_control": {
                "enabled": False,
                "read_only": True,
                "action_kind": "disabled",
                "requested_action_kind": decision.action_kind,
                "intent_source": "llm_first_web_hardware_agent",
                "intent_confidence": decision.confidence,
                "reasoning_summary": decision.reasoning_summary,
                "tool_trace": decision.tool_trace,
                "knowledge_sources": decision.knowledge_sources,
            },
        }
    return None


def _try_llm_first_web_readonly_action(
    text: str,
    settings: Settings,
    *,
    conversation_history: list[dict[str, object]],
    conversation_key: str | None = None,
) -> dict[str, object]:
    grounded = _try_hermes_grounded_readonly_answer(
        text,
        settings,
        conversation_history=conversation_history,
        conversation_key=conversation_key,
    )
    if grounded is not None:
        return grounded

    fallback = _try_readonly_observation_fallback(
        text,
        settings,
        conversation_history=conversation_history,
        source="read_only_llm_fallback",
    )
    if fallback is not None:
        hardware_control = fallback.get("hardware_control")
        if isinstance(hardware_control, dict):
            hardware_control["enabled"] = False
            hardware_control["read_only"] = True
            hardware_control["intent_source"] = "llm_failed:local_observation_fallback"
            hardware_control["reasoning_summary"] = (
                "DeepSeek grounded readonly answer unavailable, used local observation fallback"
            )[:400]
            hardware_control["tool_trace"] = ["deepseek_grounded_unavailable", "local_observation_fallback"]
        return fallback

    return _local_contextual_conversation_response(
        text,
        settings,
        conversation_history=conversation_history,
        automation_context=None,
        model_error="grounded conversation unavailable",
    )


def _try_readonly_observation_fallback(
    text: str,
    settings: Settings,
    *,
    conversation_history: list[dict[str, object]],
    source: str,
) -> dict[str, object] | None:
    direct = _try_observation_query(text, settings, source=source)
    if direct is not None:
        return direct
    followup_basis = _previous_user_observation_request(text, conversation_history)
    if not followup_basis:
        return None
    return _try_observation_query(followup_basis, settings, source=f"{source}:followup")


def _previous_user_observation_request(
    text: str,
    conversation_history: list[dict[str, object]],
) -> str:
    normalized = _normalize_web_text(text)
    followup_tokens = {"现在", "现在呢", "那现在呢", "然后呢", "还有呢", "此时呢", "目前呢"}
    if normalized not in followup_tokens:
        return ""
    user_messages = [
        str(item.get("content") or "")
        for item in conversation_history
        if isinstance(item, dict) and str(item.get("role") or "") == "user"
    ]
    if len(user_messages) < 2:
        return ""
    previous = user_messages[-2].strip()
    return previous[:800]


def _try_hermes_grounded_readonly_answer(
    text: str,
    settings: Settings,
    *,
    conversation_history: list[dict[str, object]],
    conversation_key: str | None,
) -> dict[str, object] | None:
    snapshot_response = _build_observation_query_response(
        settings,
        query=WebObservationQuery(
            devices=["AHT20", "BH1750"],
            capabilities=["env.temperature", "env.humidity", "env.light.lux"],
        ),
        source="grounded_uploaded_data_context",
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
    try:
        if settings.hermes_gateway_url:
            assistant_message = run_hermes_gateway_prompt(
                text,
                settings,
                conversation=conversation_key or f"web-readonly:{settings.device_id}:{secrets.token_hex(6)}",
                instructions=(
                    "You are a Chinese hardware assistant for the RA8P1 project. "
                    "Understand the user's natural-language intent from the current message plus "
                    "conversation_history, then answer strictly from uploaded_data_summary and "
                    "latest_device_state. Treat those uploaded values as the authoritative server-side "
                    "data. Do not invent measurements, online status, freshness, device capabilities, or "
                    "unstated conclusions. If some requested value is missing or stale, say that directly. "
                    "If uploaded_data_summary has null values or online=false, do not mention any historical "
                    "numbers, previous measurements, or 'last known' values unless they are explicitly present "
                    "in uploaded_data_summary. "
                    "Do not return JSON. This is read-only chat: never propose or perform hardware execution."
                ),
                context=context,
                store=True,
            )
        else:
            result = chat_with_hermes_official(
                text,
                settings,
                device_context=context,
            )
            assistant_message = result.assistant_message
    except Exception:
        return None
    normalized_message = assistant_message.strip()
    lowered = normalized_message.lower()
    if (
        not normalized_message
        or "insufficient balance" in lowered
        or "error code: 402" in lowered
        or "\"message\": \"insufficient balance\"" in lowered
    ):
        return None
    normalized_message = _sanitize_hermes_readonly_answer(normalized_message, uploaded_data_summary)

    return {
        "ok": True,
        "assistant_message": _normalize_device_presence_claim(normalized_message, settings),
        "source": "hermes_grounded_uploaded_data",
        "created_at": int(time.time()),
        "hardware_control": {
            "enabled": False,
            "read_only": True,
            "action_kind": "none",
            "intent_source": "model_grounded_uploaded_data",
            "intent_confidence": 1.0,
            "reasoning_summary": "Hermes freeform answer grounded on uploaded live data",
            "tool_trace": ["hermes_grounded_uploaded_data"],
            "uploaded_data_summary": uploaded_data_summary,
        },
    }


def _try_contextual_web_conversation_answer(
    text: str,
    settings: Settings,
    *,
    conversation_history: list[dict[str, object]],
    automation_context: dict[str, object] | None,
) -> dict[str, object] | None:
    if not settings.hermes_gateway_url.strip():
        return None
    tasks = _conversation_task_summary(settings, automation_context)
    context = _web_device_context(settings)
    context["conversation_history"] = [
        {
            "role": str(item.get("role") or ""),
            "content": str(item.get("content") or "")[:600],
            "created_at": item.get("created_at"),
        }
        for item in conversation_history[-16:]
        if isinstance(item, dict)
    ]
    context["conversation_tasks"] = tasks
    conversation_key = _automation_conversation_key(automation_context, settings.device_id)
    try:
        assistant_message = run_hermes_gateway_prompt(
            text,
            settings,
            conversation=conversation_key,
            instructions=(
                "You are the conversational Hermes layer for the RA8P1 Web interface. "
                "Answer in Chinese. Understand ordinary natural language from the full conversation history; "
                "do not force normal questions into a hardware JSON decision. conversation_tasks is the "
                "authoritative task state. Explain task delivery, status, or context from that state. "
                "Do not claim that a task or hardware action was created unless conversation_tasks or "
                "latest_device_state proves it. Do not return JSON."
            ),
            context=context,
            store=True,
        )
    except Exception:
        return None
    lowered = assistant_message.lower()
    if (
        not assistant_message.strip()
        or "insufficient balance" in lowered
        or "error code: 402" in lowered
        or "expecting property name enclosed" in lowered
    ):
        return None
    return {
        "ok": True,
        "assistant_message": _normalize_device_presence_claim(assistant_message.strip(), settings),
        "source": "hermes_contextual_conversation",
        "created_at": int(time.time()),
        "hardware_control": {
            "enabled": False,
            "read_only": True,
            "action_kind": "none",
            "intent_source": "hermes_contextual_conversation",
            "conversation_tasks": tasks,
        },
    }


def _local_contextual_conversation_response(
    text: str,
    settings: Settings,
    *,
    conversation_history: list[dict[str, object]],
    automation_context: dict[str, object] | None,
    model_error: str,
) -> dict[str, object]:
    tasks = _conversation_task_summary(settings, automation_context)
    normalized = _normalize_web_text(text)
    latest = tasks[0] if tasks else None
    if any(token in normalized for token in ("上报", "汇报", "对话框", "发到哪里", "路线")):
        if latest and latest.get("task_type") == "scheduled_report":
            status = "已执行" if not latest.get("enabled") and latest.get("last_run_at") else "等待执行"
            message = (
                f"定时汇报会由云端后台任务服务触发，并作为助手消息写回创建任务的这个对话框，"
                f"不需要网页一直打开。最近任务 `{latest['task_id']}` 当前状态：{status}。"
            )
            latest_result = latest.get("last_result")
            if isinstance(latest_result, dict) and latest_result.get("message"):
                message += "\n\n最近一次汇报内容已写入会话；网页会自动刷新显示。"
        else:
            message = (
                "Web 定时汇报的路线是：后台调度器 → 读取服务器最新上报 → "
                "写入创建任务的同一对话框。QQBot 任务则主动发送到原 QQ 会话。"
            )
    elif latest is not None:
        message = (
            "我把这句识别为普通对话，没有下发硬件。当前会话最近任务是 "
            f"`{latest['task_id']}`：{latest['name']}。你可以直接接着说“改成10点25”、"
            "“改为每天”或“取消刚才那个”，不必重复完整任务。"
        )
    else:
        message = (
            "我把这句识别为普通对话，没有下发硬件。当前模型服务暂时不可用，"
            "但会话上下文仍保留；定时任务可以继续用自然语言创建、修改和取消。"
        )
    return {
        "ok": True,
        "assistant_message": message,
        "source": "local_contextual_conversation_fallback",
        "created_at": int(time.time()),
        "hardware_control": {
            "enabled": False,
            "read_only": True,
            "action_kind": "none",
            "intent_source": "model_unavailable:contextual_fallback",
            "reasoning_summary": str(model_error)[:240],
            "conversation_tasks": tasks,
        },
    }


def _conversation_task_summary(
    settings: Settings,
    automation_context: dict[str, object] | None,
) -> list[dict[str, object]]:
    if automation_context is None:
        return []
    service = get_automation_task_service(settings)
    owner_channel = str(automation_context.get("owner_channel") or "")
    owner_id = str(automation_context.get("owner_id") or "")
    conversation_id = str(automation_context.get("conversation_id") or "")
    return [
        {
            "task_id": task["task_id"],
            "task_type": task["task_type"],
            "name": task["name"],
            "schedule_kind": task["schedule_kind"],
            "next_run_at": task["next_run_at"],
            "last_run_at": task["last_run_at"],
            "last_result": task["last_result"],
            "enabled": task["enabled"],
            "spec": task["spec"],
        }
        for task in service.list_tasks(owner_channel, owner_id, enabled_only=False)
        if task["conversation_id"] == conversation_id
    ][:10]


def _automation_conversation_key(
    automation_context: dict[str, object] | None,
    device_id: str,
) -> str:
    if automation_context is None:
        return f"web-conversation:{device_id}:{secrets.token_hex(6)}"
    return (
        f"web-conversation:{automation_context.get('owner_channel')}:"
        f"{automation_context.get('owner_id')}:{automation_context.get('conversation_id')}"
    )


def _may_reference_existing_task(text: str) -> bool:
    normalized = _normalize_web_text(text)
    return any(
        token in normalized
        for token in (
            "改成",
            "改到",
            "改为",
            "调整",
            "换成",
            "延后",
            "提前",
            "取消刚才",
            "删除刚才",
            "刚才那个",
            "这个任务",
            "改成每天",
            "只执行一次",
            "仅今天",
        )
    )


def _sanitize_hermes_readonly_answer(
    message: str,
    uploaded_data_summary: dict[str, object],
) -> str:
    if not isinstance(uploaded_data_summary, dict):
        return message
    current_values = [
        uploaded_data_summary.get("temperature"),
        uploaded_data_summary.get("humidity"),
        uploaded_data_summary.get("light"),
    ]
    if any(value is not None for value in current_values):
        return message
    if uploaded_data_summary.get("online") or uploaded_data_summary.get("fresh"):
        return message
    lower = message.lower()
    if any(token in lower for token in ("上次", "之前", "last known", "last time", "历史")):
        return (
            "云端当前没有收到这台设备的实时上报。AHT20 和 BH1750 现在都没有可用新数据，"
            "所以我不能提供当前温湿度或光照值。"
        )
    return message


def _device_freshness(snapshot: dict[str, object], *, stale_after_sec: int = 20) -> dict[str, object]:
    timestamp = snapshot.get("last_seen")
    if not isinstance(timestamp, (int, float)):
        return {"online": False, "age_sec": None, "stale_after_sec": stale_after_sec}
    age_sec = max(0, int(time.time() - float(timestamp)))
    return {
        "online": age_sec <= stale_after_sec,
        "age_sec": age_sec,
        "stale_after_sec": stale_after_sec,
    }


def _normalize_device_presence_claim(message: str, settings: Settings) -> str:
    snapshot = device_state_store.snapshot(settings.device_id)
    freshness = _device_freshness(snapshot)
    if freshness["online"]:
        return message
    if not any(token in message for token in ("已连接", "在线", "connected", "powered on")):
        return message

    cleaned = message
    patterns = [
        r"我看到你已连接了设备\s*\*{0,2}[^*。\n]+?\*{0,2}[。.]?",
        r"你已连接了设备\s*\*{0,2}[^*。\n]+?\*{0,2}[。.]?",
        r"当前设备(?:已经)?在线[。.]?",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    if snapshot.get("last_seen") is None:
        correction = (
            f"更正一下：云端现在只是选中了默认设备 ID `{settings.device_id}`，"
            "并没有看到它在线。当前 `last_seen` 为空，说明服务器还没有收到这台设备的上电或遥测上报。"
        )
    else:
        correction = (
            f"更正一下：云端现在只是保留了设备 ID `{settings.device_id}`，"
            f"但最近一次上报已经是约 {freshness['age_sec']} 秒前，所以不能把它说成当前在线。"
        )
    return correction if not cleaned else f"{correction}\n\n{cleaned}"


def _try_llm_first_web_hardware_action(
    text: str,
    settings: Settings,
    orchestrator: AgentOrchestrator,
    *,
    conversation_history: list[dict[str, object]],
    automation_context: dict[str, object] | None = None,
) -> dict[str, object]:
    context = _web_device_context(settings)
    direct_task = automation_task_from_text(text)
    latest_task = None
    if automation_context is not None and _may_reference_existing_task(text):
        service = get_automation_task_service(settings)
        latest_task = service.latest_conversation_task(
            str(automation_context.get("owner_channel") or ""),
            str(automation_context.get("owner_id") or ""),
            str(automation_context.get("conversation_id") or ""),
        )
    contextual_task = contextual_automation_task_from_text(
        text,
        conversation_history=conversation_history,
        latest_task=latest_task,
    )
    preference_response = _try_servo_preference_only_update(
        text,
        settings,
        automation_context,
    )
    if preference_response is not None:
        return preference_response
    if (
        contextual_task is not None
        and automation_context is not None
        and (
            contextual_task.get("operation") != "create"
            or direct_task is None
        )
    ):
        return _handle_automation_task(
            text,
            contextual_task,
            settings,
            automation_context=automation_context,
            assistant_message="已结合当前对话中的任务上下文更新。",
            confidence=1.0,
            reasoning_summary="conversation-scoped deterministic task context",
            tool_trace=["conversation_task_context"],
            knowledge_sources=[],
        )
    parsed_task = direct_task
    if (
        parsed_task is not None
        and parsed_task.get("operation") == "clarify"
        and automation_context is not None
    ):
        return _automation_clarification_response(str(parsed_task.get("question") or "请补充任务周期。"))
    try:
        decision = decide_web_hardware_action(
            text,
            settings,
            conversation_history=conversation_history,
            device_context=context,
        )
    except Exception as exc:
        parsed_task = contextual_task
        if parsed_task is not None and automation_context is not None:
            return _handle_automation_task(
                text,
                parsed_task,
                settings,
                automation_context=automation_context,
                assistant_message="已按你的自然语言要求解析任务。",
                confidence=0.88,
                reasoning_summary=f"LLM unavailable; deterministic automation parser used: {exc}",
                tool_trace=["llm_failed", "local_automation_parser"],
                knowledge_sources=[],
            )
        fallback = _try_web_hardware_deploy(text, settings, orchestrator)
        if fallback is not None:
            hardware_control = fallback.get("hardware_control")
            if isinstance(hardware_control, dict):
                hardware_control["intent_source"] = "llm_failed:local_hardware_fallback"
                hardware_control["reasoning_summary"] = (
                    f"LLM unavailable, used local hardware fallback: {exc}"
                )[:400]
                hardware_control["tool_trace"] = ["llm_failed", str(exc)[:160], "local_hardware_fallback"]
            return fallback
        conversational = _try_contextual_web_conversation_answer(
            text,
            settings,
            conversation_history=conversation_history,
            automation_context=automation_context,
        )
        if conversational is not None:
            return conversational
        return _local_contextual_conversation_response(
            text,
            settings,
            conversation_history=conversation_history,
            automation_context=automation_context,
            model_error=str(exc),
        )

    if decision.action_kind == "none":
        assistant_message = _normalize_device_presence_claim(decision.assistant_message, settings)
        provider_label = (
            "hermes-agent"
            if settings.llm_provider.lower() == "hermes_official"
            else f"deepseek:{settings.deepseek_model}"
        )
        return {
            "ok": True,
            "assistant_message": assistant_message,
            "source": f"{provider_label}+web_hardware_agent",
            "created_at": int(time.time()),
            "hardware_control": {
                "enabled": True,
                "action_kind": "none",
                "intent_source": "llm_first_web_hardware_agent",
                "intent_confidence": decision.confidence,
                "reasoning_summary": decision.reasoning_summary,
                "tool_trace": decision.tool_trace,
                "knowledge_sources": decision.knowledge_sources,
            },
        }
    if decision.action_kind == "observation_query":
        return _build_observation_query_response(
            settings,
            query=decision.observation_query,
            user_text=text,
            source="llm_first_web_hardware_agent:observation_query",
            confidence=decision.confidence,
            reasoning_summary=decision.reasoning_summary,
            tool_trace=decision.tool_trace,
            knowledge_sources=decision.knowledge_sources,
            conversation_history=conversation_history,
        )
    if decision.action_kind == "manual_action":
        assert decision.manual_action is not None
        auto_reset = _resolve_servo_auto_reset(
            text,
            settings,
            automation_context,
        )
        return _deploy_manual_action(
            {
                "angle": decision.manual_action.angle,
                "times": decision.manual_action.times,
                "duration_ms": decision.manual_action.duration_ms,
                "direction": decision.manual_action.direction,
                "auto_reset": auto_reset,
            },
            settings,
            source="llm_first_web_hardware_agent:manual_action",
            confidence=decision.confidence,
            reasoning_summary=decision.reasoning_summary,
            tool_trace=decision.tool_trace,
            knowledge_sources=decision.knowledge_sources,
        )
    if decision.action_kind == "automation_task":
        if automation_context is None:
            raise HTTPException(status_code=422, detail="automation task context is required")
        return _handle_automation_task(
            text,
            decision.automation_task,
            settings,
            automation_context=automation_context,
            assistant_message=decision.assistant_message,
            confidence=decision.confidence,
            reasoning_summary=decision.reasoning_summary,
            tool_trace=decision.tool_trace,
            knowledge_sources=decision.knowledge_sources,
        )
    if decision.action_kind == "rule_program":
        assert decision.program is not None
        return _deploy_rule_program(
            decision.program,
            settings,
            orchestrator,
            source="llm_first_web_hardware_agent:rule_program",
            confidence=decision.confidence,
            assistant_message=decision.assistant_message,
            reasoning_summary=decision.reasoning_summary,
            tool_trace=decision.tool_trace,
            knowledge_sources=decision.knowledge_sources,
        )
    raise HTTPException(status_code=502, detail=f"unsupported LLM hardware action_kind: {decision.action_kind}")


def _handle_automation_task(
    text: str,
    decision_payload: dict[str, Any] | None,
    settings: Settings,
    *,
    automation_context: dict[str, object],
    assistant_message: str,
    confidence: float,
    reasoning_summary: str,
    tool_trace: list[str],
    knowledge_sources: list[str],
) -> dict[str, object]:
    parsed = automation_task_from_text(text)
    request = _normalize_model_automation_task(decision_payload)
    if parsed is not None:
        request.update(parsed)
    operation = str(request.get("operation") or "").strip().lower()
    if operation == "clarify":
        return _automation_clarification_response(
            str(request.get("question") or "请确认这个任务是每天执行，还是仅今天执行一次。")
        )
    owner_channel = str(automation_context.get("owner_channel") or "")
    owner_id = str(automation_context.get("owner_id") or "")
    conversation_id = str(automation_context.get("conversation_id") or "")
    device_id = str(automation_context.get("device_id") or settings.device_id)
    control_enabled = bool(automation_context.get("control_enabled"))
    if not owner_channel or not owner_id or not conversation_id:
        raise HTTPException(status_code=422, detail="automation task owner context is incomplete")

    service = get_automation_task_service(settings)
    if operation == "list":
        tasks = service.list_tasks(owner_channel, owner_id)
        if tasks:
            lines = [
                f"- `{task['task_id']}`：{task['name']}（{'启用' if task['enabled'] else '停用'}）"
                for task in tasks
            ]
            message = "当前有效任务：\n" + "\n".join(lines)
        else:
            message = "当前没有有效的长期或短期任务。"
        return _automation_task_response(
            message,
            operation=operation,
            tasks=tasks,
            enabled=control_enabled,
            confidence=confidence,
            reasoning_summary=reasoning_summary,
            tool_trace=tool_trace,
            knowledge_sources=knowledge_sources,
        )

    if operation == "cancel":
        task_id = str(request.get("task_id") or "")
        cancelled = bool(task_id) and service.cancel_task(task_id, owner_channel, owner_id)
        message = f"已取消任务 `{task_id}`。" if cancelled else f"没有找到可取消的任务 `{task_id}`。"
        return _automation_task_response(
            message,
            operation=operation,
            tasks=[],
            enabled=control_enabled,
            confidence=confidence,
            reasoning_summary=reasoning_summary,
            tool_trace=tool_trace,
            knowledge_sources=knowledge_sources,
            extra={"task_id": task_id, "cancelled": cancelled},
        )

    if operation == "update":
        task_id = str(request.get("task_id") or "")
        spec = request.get("spec")
        updated = service.update_task(
            task_id,
            owner_channel,
            owner_id,
            spec=spec if isinstance(spec, dict) else None,
            schedule_kind=str(request.get("schedule_kind") or "once"),
            next_run_at=request.get("next_run_at") if isinstance(request.get("next_run_at"), int) else None,
            survives_conversation=bool(request.get("survives_conversation")),
            enabled=True,
        )
        if updated is None:
            message = f"没有找到可修改的任务 `{task_id}`。"
            tasks: list[dict[str, Any]] = []
        else:
            run_text = (
                datetime.fromtimestamp(int(updated["next_run_at"]), _LOCAL_TZ).strftime(
                    "%Y-%m-%d %H:%M:%S %z"
                )
                if isinstance(updated.get("next_run_at"), int)
                else "条件满足时"
            )
            message = f"已更新任务 `{task_id}`：{updated['name']}，下次执行时间 {run_text}。"
            tasks = [updated]
        return _automation_task_response(
            message,
            operation=operation,
            tasks=tasks,
            enabled=control_enabled,
            confidence=confidence,
            reasoning_summary=reasoning_summary,
            tool_trace=tool_trace,
            knowledge_sources=knowledge_sources,
            extra={"task_id": task_id, "updated": updated is not None},
        )

    if operation != "create":
        raise HTTPException(status_code=422, detail="automation task operation must be create, update, list, or cancel")
    task_type = str(request.get("task_type") or "")
    if task_type in {"sensor_rule", "scheduled_action"} and not control_enabled:
        return {
            "ok": True,
            "assistant_message": (
                f"{assistant_message}\n\n"
                "已理解这个传感器触发条件，但当前入口未启用硬件控制，因此没有建立会驱动舵机的任务。"
            ),
            "source": "automation_task_service:control_disabled",
            "created_at": int(time.time()),
            "hardware_control": {
                "enabled": False,
                "read_only": True,
                "action_kind": "disabled",
                "requested_action_kind": "automation_task",
                "intent_confidence": confidence,
                "reasoning_summary": reasoning_summary,
                "tool_trace": tool_trace,
                "knowledge_sources": knowledge_sources,
            },
        }
    if task_type not in {"sensor_rule", "scheduled_report", "scheduled_action"}:
        raise HTTPException(status_code=422, detail="unsupported automation task_type")
    spec = request.get("spec")
    if not isinstance(spec, dict):
        raise HTTPException(status_code=422, detail="automation task spec is required")
    if task_type in {"sensor_rule", "scheduled_action"}:
        spec["auto_reset"] = _resolve_servo_auto_reset(
            text,
            settings,
            automation_context,
            explicit_default=bool(spec.get("auto_reset")),
        )
    if task_type in {"sensor_rule", "scheduled_action"}:
        direction = str(spec.get("direction") or "both")
        try:
            angle = int(spec.get("angle"))
            times = int(spec.get("times"))
            duration_ms = int(spec.get("duration_ms") or 350)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="servo automation task has invalid numeric fields") from exc
        if direction not in {"both", "left", "right"}:
            raise HTTPException(status_code=422, detail="unsupported servo direction")
        if not 1 <= angle <= 90 or not 1 <= times <= 10 or not 50 <= duration_ms <= 5000:
            raise HTTPException(status_code=422, detail="servo automation action is out of range")
        spec.update(
            {
                "direction": direction,
                "angle": angle,
                "times": times,
                "duration_ms": duration_ms,
            }
        )
    if task_type == "sensor_rule":
        capability = str(spec.get("capability") or "")
        operator = str(spec.get("operator") or "")
        try:
            threshold = float(spec.get("value"))
            cooldown_sec = int(spec.get("cooldown_sec") or 30)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="sensor automation task has invalid numeric fields") from exc
        if capability not in {"env.temperature", "env.humidity", "env.light.lux"}:
            raise HTTPException(status_code=422, detail="unsupported sensor automation capability")
        if operator not in {">", ">=", "<", "<=", "=="}:
            raise HTTPException(status_code=422, detail="unsupported sensor automation operator")
        spec = {
            "capability": capability,
            "operator": operator,
            "value": threshold,
            "direction": spec["direction"],
            "angle": spec["angle"],
            "times": spec["times"],
            "duration_ms": spec["duration_ms"],
            "auto_reset": bool(spec.get("auto_reset")),
            "cooldown_sec": max(0, cooldown_sec),
        }
    next_run_at = request.get("next_run_at")
    if task_type in {"scheduled_report", "scheduled_action"} and not isinstance(next_run_at, int):
        raise HTTPException(status_code=422, detail="scheduled task requires a valid future time")

    task = service.create_task(
        owner_channel=owner_channel,
        owner_id=owner_id,
        conversation_id=conversation_id,
        device_id=device_id,
        task_type=task_type,
        name=str(request.get("name") or assistant_message or "自动化任务"),
        spec=spec,
        schedule_kind=str(request.get("schedule_kind") or ""),
        next_run_at=next_run_at if isinstance(next_run_at, int) else None,
        survives_conversation=bool(request.get("survives_conversation")),
    )
    if task_type == "sensor_rule":
        message = f"已建立传感器联动任务 `{task['task_id']}`：{task['name']}。三个传感器规则可并行存在，互不覆盖。"
    elif task_type == "scheduled_report":
        run_text = datetime.fromtimestamp(int(task["next_run_at"]), _LOCAL_TZ).strftime(
            "%Y-%m-%d %H:%M:%S %z"
        )
        cycle = "每天" if task["schedule_kind"] == "daily" else "一次"
        message = f"已建立{cycle}汇报任务 `{task['task_id']}`，下次执行时间为 {run_text}。"
    else:
        run_text = datetime.fromtimestamp(int(task["next_run_at"]), _LOCAL_TZ).strftime(
            "%Y-%m-%d %H:%M:%S %z"
        )
        cycle = "每天" if task["schedule_kind"] == "daily" else "仅一次"
        reset_text = "执行后自动回到 90 度" if task["spec"].get("auto_reset") else "执行后保持目标角度"
        message = f"已建立{cycle}舵机任务 `{task['task_id']}`，执行时间 {run_text}；{reset_text}。"
    return _automation_task_response(
        message,
        operation=operation,
        tasks=[task],
        enabled=control_enabled,
        confidence=confidence,
        reasoning_summary=reasoning_summary,
        tool_trace=tool_trace,
        knowledge_sources=knowledge_sources,
    )


def _normalize_model_automation_task(payload: dict[str, Any] | None) -> dict[str, Any]:
    request: dict[str, Any] = dict(payload or {})
    if request.get("operation"):
        normalized = request
    elif isinstance(request.get("trigger"), dict) and (
        isinstance(request.get("action"), dict)
        or isinstance(request.get("actions"), list)
        or request.get("direction")
    ):
        trigger = dict(request["trigger"])
        action = dict(request["action"]) if isinstance(request.get("action"), dict) else {}
        actions = request.get("actions")
        first_action = actions[0] if isinstance(actions, list) and actions and isinstance(actions[0], dict) else {}
        first_params = first_action.get("params") if isinstance(first_action, dict) else {}
        first_params = first_params if isinstance(first_params, dict) else {}
        cooldown_ms = request.get("cooldown_ms")
        cooldown_sec = (
            int(cooldown_ms) // 1000
            if isinstance(cooldown_ms, (int, float))
            else request.get("cooldown_sec", 30)
        )
        sensor = str(trigger.get("capability") or trigger.get("sensor") or "")
        capability = {
            "AHT20.temp": "env.temperature",
            "AHT20.temperature": "env.temperature",
            "AHT20.humidity": "env.humidity",
            "BH1750.lux": "env.light.lux",
        }.get(sensor, sensor)
        normalized = {
            "operation": "create",
            "task_type": "sensor_rule",
            "name": str(request.get("name") or request.get("description") or "传感器联动任务"),
            "spec": {
                "capability": capability,
                "operator": str(trigger.get("operator") or ">="),
                "value": trigger.get("value"),
                "direction": str(action.get("direction") or request.get("direction") or "both"),
                "angle": action.get("angle", request.get("amplitude_deg", 30)),
                "times": action.get("times", request.get("repeat", 1)),
                "duration_ms": action.get("duration_ms", first_params.get("duration_ms", 350)),
                "cooldown_sec": cooldown_sec,
            },
        }
    else:
        schedule = request.get("schedule")
        if isinstance(schedule, dict):
            normalized = {
                "operation": "create",
                "task_type": "scheduled_report",
                "name": str(request.get("name") or "环境汇报任务"),
                "schedule_kind": str(schedule.get("kind") or schedule.get("schedule_kind") or "once"),
                "spec": {"local_time": str(schedule.get("local_time") or "")},
                "next_run_at": schedule.get("next_run_at"),
            }
        else:
            normalized = request
    if normalized.get("task_type") == "scheduled_report":
        spec = normalized.get("spec")
        local_time = str(spec.get("local_time") or "") if isinstance(spec, dict) else ""
        if local_time and not isinstance(normalized.get("next_run_at"), int):
            try:
                normalized["next_run_at"] = automation_next_run(local_time)
            except (TypeError, ValueError):
                pass
    return normalized


def _automation_task_response(
    message: str,
    *,
    operation: str,
    tasks: list[dict[str, Any]],
    enabled: bool,
    confidence: float,
    reasoning_summary: str,
    tool_trace: list[str],
    knowledge_sources: list[str],
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    hardware_control: dict[str, object] = {
        "enabled": enabled,
        "action_kind": "automation_task",
        "operation": operation,
        "tasks": tasks,
        "intent_source": "llm_first_web_hardware_agent+validated_automation_service",
        "intent_confidence": confidence,
        "reasoning_summary": reasoning_summary,
        "tool_trace": tool_trace,
        "knowledge_sources": knowledge_sources,
    }
    if extra:
        hardware_control.update(extra)
    return {
        "ok": True,
        "assistant_message": message,
        "source": "automation_task_service",
        "created_at": int(time.time()),
        "hardware_control": hardware_control,
    }


def _automation_clarification_response(question: str) -> dict[str, object]:
    return {
        "ok": True,
        "assistant_message": question,
        "source": "automation_task_service:clarification",
        "created_at": int(time.time()),
        "hardware_control": {
            "enabled": False,
            "action_kind": "none",
            "requires_clarification": True,
            "task_created": False,
        },
    }


@router.get("/web/conversations")
def web_conversations(
    store: AuthStore = Depends(get_auth_store),
    user: AuthenticatedUser = Depends(current_user),
) -> dict[str, object]:
    return {"ok": True, "conversations": store.list_conversations(user.id)}


@router.post("/web/conversations")
def web_create_conversation(
    store: AuthStore = Depends(get_auth_store),
    user: AuthenticatedUser = Depends(csrf_user),
) -> dict[str, object]:
    conversation = store.create_conversation(user.id)
    conversation.pop("_internal_id", None)
    return {"ok": True, "conversation": conversation}


@router.delete("/web/conversations/{conversation_id}")
def web_delete_conversation(
    conversation_id: str,
    settings: Settings = Depends(get_settings),
    store: AuthStore = Depends(get_auth_store),
    user: AuthenticatedUser = Depends(csrf_user),
) -> dict[str, object]:
    cancelled_tasks = get_automation_task_service(settings).cancel_conversation_tasks(
        "web",
        str(user.id),
        conversation_id,
    )
    store.delete_conversation(user.id, conversation_id)
    return {"ok": True, "cancelled_tasks": cancelled_tasks}


@router.patch("/web/conversations/{conversation_id}")
def web_update_conversation(
    conversation_id: str,
    payload: ConversationUpdateRequest,
    store: AuthStore = Depends(get_auth_store),
    user: AuthenticatedUser = Depends(csrf_user),
) -> dict[str, object]:
    result: dict[str, object] = {"id": conversation_id}
    if payload.title is not None:
        result.update(store.rename_conversation(user.id, conversation_id, payload.title))
    if payload.is_pinned is not None:
        result.update(store.set_conversation_pinned(user.id, conversation_id, payload.is_pinned))
    if payload.title is None and payload.is_pinned is None:
        raise HTTPException(status_code=422, detail="no conversation updates supplied")
    return {"ok": True, "conversation": result}


@router.get("/web/conversations/{conversation_id}/messages")
def web_chat_history(
    conversation_id: str,
    store: AuthStore = Depends(get_auth_store),
    user: AuthenticatedUser = Depends(current_user),
) -> dict[str, object]:
    return {
        "ok": True,
        "messages": store.chat_history(user.id, conversation_id),
    }


def _web_hardware_control_allowed(settings: Settings, user: AuthenticatedUser) -> bool:
    if not settings.web_hardware_control_enabled:
        return False
    roles = {
        role.strip().lower()
        for role in settings.web_hardware_control_roles.split(",")
        if role.strip()
    }
    return user.role.lower() in roles


def _try_web_hardware_deploy(
    text: str,
    settings: Settings,
    orchestrator: AgentOrchestrator,
) -> dict[str, object] | None:
    observation = _try_observation_query(text, settings)
    if observation is not None:
        return observation

    manual_action = _try_manual_action_deploy(text, settings)
    if manual_action is not None:
        return manual_action

    if not _looks_like_explicit_rule_program(text):
        return None

    try:
        parsed = interpret_text_to_rule_program(text, Settings(llm_provider="template"))
    except ValueError:
        return None

    return _deploy_rule_program(
        parsed.program,
        settings,
        orchestrator,
        source=parsed.source,
        confidence=parsed.confidence,
        reasoning_summary="legacy conservative hardware route",
    )


def _deploy_rule_program(
    program: RuleProgram,
    settings: Settings,
    orchestrator: AgentOrchestrator,
    *,
    source: str,
    confidence: float,
    assistant_message: str | None = None,
    reasoning_summary: str = "",
    tool_trace: list[str] | None = None,
    knowledge_sources: list[str] | None = None,
) -> dict[str, object]:
    request_id = _web_request_id()
    try:
        response = orchestrator.deploy_rule_program(
            ProgramDeployRequest(
                request_id=request_id,
                device_id=settings.device_id,
                program=program,
                need_confirm=True,
                wait_for_ack=settings.web_hardware_wait_for_ack,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    deploy_view = _finalize_web_deploy_view(
        {"ok": True, **response.model_dump(mode="json")},
        wait_for_ack=settings.web_hardware_wait_for_ack,
        intent_source=source,
        intent_confidence=confidence,
    )
    stage_label = deploy_view.get("delivery_stage_label") or _delivery_stage_label(str(deploy_view.get("delivery_stage") or ""))
    final_message = assistant_message or _hardware_deploy_reply(program, deploy_view, str(stage_label))
    return {
        "ok": True,
        "assistant_message": final_message,
        "source": source,
        "created_at": int(time.time()),
        "hardware_control": {
            "enabled": True,
            "action_kind": "rule_program",
            "request_id": request_id,
            "device_id": settings.device_id,
            "delivery_stage": deploy_view.get("delivery_stage"),
            "delivery_stage_label": stage_label,
            "status": deploy_view.get("status"),
            "program": program.model_dump(mode="json"),
            "deployment": deploy_view,
            "intent_source": source,
            "intent_confidence": confidence,
            "reasoning_summary": reasoning_summary,
            "tool_trace": tool_trace or [],
            "knowledge_sources": knowledge_sources or [],
        },
    }


def _try_observation_query(
    text: str,
    settings: Settings,
    *,
    source: str = "web_hardware_router:observation_query_v1",
) -> dict[str, object] | None:
    normalized = _normalize_web_text(text)
    wants_aht20 = any(token in normalized for token in ("aht20", "温湿度", "温度", "湿度"))
    wants_light = any(token in normalized for token in ("光照", "亮度", "lux", "照度", "bh1750"))
    wants_read = any(token in normalized for token in ("读取", "查询", "查看", "看看", "回传", "获取", "现在", "当前", "情况"))
    if not wants_read or not (wants_aht20 or wants_light):
        return None

    devices: list[str] = []
    capabilities: list[str] = []
    if wants_aht20:
        devices.append("AHT20")
        capabilities.extend(["env.temperature", "env.humidity"])
    if wants_light:
        devices.append("BH1750")
        capabilities.append("env.light.lux")

    return _build_observation_query_response(
        settings,
        query=WebObservationQuery(
            devices=devices,
            capabilities=capabilities,
        ),
        source=source,
        confidence=0.55,
        reasoning_summary="local observation fallback route",
    )


def _build_observation_query_response(
    settings: Settings,
    *,
    query: WebObservationQuery | None = None,
    user_text: str | None = None,
    source: str,
    confidence: float,
    reasoning_summary: str = "",
    tool_trace: list[str] | None = None,
    knowledge_sources: list[str] | None = None,
    conversation_history: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    query = query or WebObservationQuery()
    devices = _observation_query_devices(query)
    if devices == ["BH1750"]:
        response = _build_light_observation_query_response(
            settings,
            query=query,
            source=source,
            confidence=confidence,
            reasoning_summary=reasoning_summary,
            tool_trace=tool_trace,
            knowledge_sources=knowledge_sources,
        )
        return _finalize_observation_response_message(
            response,
            settings,
            query=query,
            user_text=user_text,
            conversation_history=conversation_history,
        )
    if devices == ["AHT20"]:
        response = _build_aht20_observation_query_response(
            settings,
            source=source,
            confidence=confidence,
            reasoning_summary=reasoning_summary,
            tool_trace=tool_trace,
            knowledge_sources=knowledge_sources,
        )
        return _finalize_observation_response_message(
            response,
            settings,
            query=query,
            user_text=user_text,
            conversation_history=conversation_history,
        )
    response = _build_multi_observation_query_response(
        settings,
        query=query,
        source=source,
        confidence=confidence,
        reasoning_summary=reasoning_summary,
        tool_trace=tool_trace,
        knowledge_sources=knowledge_sources,
    )
    return _finalize_observation_response_message(
        response,
        settings,
        query=query,
        user_text=user_text,
        conversation_history=conversation_history,
    )


def _observation_query_devices(query: WebObservationQuery) -> list[str]:
    devices = [str(device) for device in (query.devices or []) if device]
    if query.device and query.device not in devices:
        devices.insert(0, query.device)
    return devices or ["AHT20"]


def _finalize_observation_response_message(
    response: dict[str, object],
    settings: Settings,
    *,
    query: WebObservationQuery,
    user_text: str | None,
    conversation_history: list[dict[str, object]] | None,
) -> dict[str, object]:
    if not user_text:
        return response
    try:
        assistant_message = synthesize_observation_reply(
            user_text,
            settings,
            query=query,
            observation_result=dict(response.get("hardware_control", {})).get("result", {}),
            conversation_history=conversation_history,
            device_context=_web_device_context(settings),
        )
    except Exception:
        return response
    response["assistant_message"] = _normalize_device_presence_claim(assistant_message, settings)
    return response


def _build_aht20_observation_query_response(
    settings: Settings,
    *,
    source: str,
    confidence: float,
    reasoning_summary: str = "",
    tool_trace: list[str] | None = None,
    knowledge_sources: list[str] | None = None,
) -> dict[str, object]:
    snapshot = device_state_store.snapshot(settings.device_id)
    diagnostics = _device_diagnostics(snapshot)
    observation = latest_aht20_observation(snapshot.get("last_status"), snapshot.get("last_telemetry"))
    aht20 = observation.get("payload") if isinstance(observation.get("payload"), dict) else {}
    sample_source = str(observation.get("source") or "none")
    sample_timestamp = (
        observation.get("timestamp")
        if observation.get("timestamp") is not None
        else snapshot.get("last_seen")
    )
    sample_time_text = _format_sample_timestamp(sample_timestamp)
    freshness = _device_freshness(snapshot)
    device_online = bool(freshness["online"])
    age_sec = freshness["age_sec"]
    temperature = aht20.get("temp")
    humidity = aht20.get("humidity")
    sample_online = aht20.get("status") == "online" and temperature is not None and humidity is not None
    online = sample_online and device_online

    if online:
        assistant_message = f"已读取 I2C Bus S1 下 AHT20 的最近上报：温度 {temperature} C，湿度 {humidity}%。"
    elif sample_online:
        age_text = f"{age_sec} 秒前" if isinstance(age_sec, int) else sample_time_text
        assistant_message = (
            f"云端当前没有收到设备的实时上报。最后一次 AHT20 缓存样本是：温度 {temperature} C，湿度 {humidity}%，"
            f"上报时间 {sample_time_text}（约 {age_text}）。\n\n"
            "这说明 RA8P1 屏幕本地读数可能仍在变化，但 ESP32 -> MQTT -> 云端这条链路当前没有新数据。"
        )
    else:
        diag = str(aht20.get("diag") or diagnostics.get("aht20", {}).get("diag") or "no fresh sample")
        assistant_message = (
            "已识别为观测查询，但云端当前还没有收到 AHT20 的在线温湿度样本。\n\n"
            f"当前云端诊断：{diag}。"
        )

    return {
        "ok": True,
        "assistant_message": assistant_message,
        "source": source,
        "created_at": int(time.time()),
        "hardware_control": {
            "enabled": True,
            "action_kind": "observation_query",
            "device_id": settings.device_id,
            "query": {
                "version": "observation_query.v1",
                "channel": "i2c.s1",
                "pins": {"sda": "P309", "scl": "P306"},
                "device": "AHT20",
                "capabilities": ["env.temperature", "env.humidity"],
            },
            "result": {
                "online": online,
                "temperature": temperature,
                "humidity": humidity,
                "aht20": aht20,
                "diagnostics": diagnostics,
                "source": sample_source,
                "fresh": online,
                "sample_online": sample_online,
                "device_online": device_online,
                "age_sec": age_sec,
                "timestamp": sample_timestamp,
                "sample_time": sample_time_text,
            },
            "intent_source": source,
            "intent_confidence": confidence,
            "reasoning_summary": reasoning_summary,
            "tool_trace": tool_trace or [],
            "knowledge_sources": knowledge_sources or [],
        },
    }


def _build_multi_observation_query_response(
    settings: Settings,
    *,
    query: WebObservationQuery,
    source: str,
    confidence: float,
    reasoning_summary: str = "",
    tool_trace: list[str] | None = None,
    knowledge_sources: list[str] | None = None,
) -> dict[str, object]:
    devices = _observation_query_devices(query)
    requested_capabilities = list(dict.fromkeys(query.capabilities))
    observations: dict[str, dict[str, object]] = {}

    if "AHT20" in devices:
        aht20_response = _build_aht20_observation_query_response(
            settings,
            source=source,
            confidence=confidence,
            reasoning_summary=reasoning_summary,
            tool_trace=tool_trace,
            knowledge_sources=knowledge_sources,
        )
        aht20_result = dict(aht20_response.get("hardware_control", {})).get("result", {})
        if isinstance(aht20_result, dict):
            observations["AHT20"] = aht20_result

    if "BH1750" in devices:
        light_response = _build_light_observation_query_response(
            settings,
            query=WebObservationQuery(device="BH1750", capabilities=["env.light.lux"]),
            source=source,
            confidence=confidence,
            reasoning_summary=reasoning_summary,
            tool_trace=tool_trace,
            knowledge_sources=knowledge_sources,
        )
        light_result = dict(light_response.get("hardware_control", {})).get("result", {})
        if isinstance(light_result, dict):
            observations["BH1750"] = light_result

    fresh_flags = [bool(item.get("fresh")) for item in observations.values()]
    timestamps = [
        item.get("timestamp")
        for item in observations.values()
        if isinstance(item.get("timestamp"), (int, float))
    ]
    latest_timestamp = max(timestamps) if timestamps else None
    overall_result: dict[str, object] = {
        "online": bool(fresh_flags) and all(fresh_flags),
        "fresh": bool(fresh_flags) and all(fresh_flags),
        "partial_fresh": any(fresh_flags),
        "device_online": any(bool(item.get("device_online")) for item in observations.values()),
        "sample_online": bool(fresh_flags) and all(bool(item.get("sample_online")) for item in observations.values()),
        "age_sec": min(
            (
                int(item.get("age_sec"))
                for item in observations.values()
                if isinstance(item.get("age_sec"), int)
            ),
            default=None,
        ),
        "timestamp": latest_timestamp,
        "sample_time": _format_sample_timestamp(latest_timestamp),
        "requested_devices": devices,
        "requested_capabilities": requested_capabilities,
        "observations": observations,
    }
    aht20 = observations.get("AHT20", {})
    light = observations.get("BH1750", {})
    if aht20:
        overall_result["temperature"] = aht20.get("temperature")
        overall_result["humidity"] = aht20.get("humidity")
        overall_result["aht20"] = aht20.get("aht20")
    if light:
        overall_result["light"] = light.get("light")
        overall_result["unit"] = light.get("unit")

    parts: list[str] = []
    if "env.temperature" in requested_capabilities and "env.humidity" in requested_capabilities:
        if aht20.get("fresh"):
            parts.append(
                f"温度 {aht20.get('temperature')} C，湿度 {aht20.get('humidity')}%。"
            )
        elif aht20.get("temperature") is not None and aht20.get("humidity") is not None:
            parts.append(
                f"温湿度只有历史样本：温度 {aht20.get('temperature')} C，湿度 {aht20.get('humidity')}%，"
                f"时间 {aht20.get('sample_time')}。"
            )
        else:
            parts.append("温湿度当前没有可用上报。")
    if "env.light.lux" in requested_capabilities:
        if light.get("fresh"):
            parts.append(f"光照 {light.get('light')} {light.get('unit') or 'lux'}。")
        elif light.get("light") is not None:
            parts.append(
                f"光照只有历史样本：{light.get('light')} {light.get('unit') or 'lux'}，"
                f"时间 {light.get('sample_time')}。"
            )
        else:
            parts.append("光照当前没有可用上报。")

    assistant_message = "已读取当前环境数据：" + " ".join(parts) if parts else "已完成观测查询。"
    return {
        "ok": True,
        "assistant_message": assistant_message,
        "source": source,
        "created_at": int(time.time()),
        "hardware_control": {
            "enabled": True,
            "action_kind": "observation_query",
            "device_id": settings.device_id,
            "query": {
                "version": "observation_query.v2",
                "channel": query.channel,
                "pins": {"sda": "P309", "scl": "P306"},
                "device": query.device,
                "devices": devices,
                "capabilities": requested_capabilities,
            },
            "result": overall_result,
            "intent_source": source,
            "intent_confidence": confidence,
            "reasoning_summary": reasoning_summary,
            "tool_trace": tool_trace or [],
            "knowledge_sources": knowledge_sources or [],
        },
    }


def _build_light_observation_query_response(
    settings: Settings,
    *,
    query: WebObservationQuery,
    source: str,
    confidence: float,
    reasoning_summary: str = "",
    tool_trace: list[str] | None = None,
    knowledge_sources: list[str] | None = None,
) -> dict[str, object]:
    snapshot = device_state_store.snapshot(settings.device_id)
    freshness = _device_freshness(snapshot)
    candidates: list[tuple[float, dict[str, object], object]] = []
    for message in (snapshot.get("last_telemetry"), snapshot.get("last_status")):
        payload = _message_payload(message)
        sample = _find_sample(payload, "env.light.lux", port_id="i2c.s1", module_type="BH1750")
        if not sample:
            continue
        sample_clock = sample.get("ts_ms")
        score = float(sample_clock) if isinstance(sample_clock, (int, float)) else 0.0
        message_timestamp = message.get("timestamp") if isinstance(message, dict) else None
        candidates.append((score, sample, message_timestamp))

    selected = max(candidates, key=lambda item: item[0]) if candidates else None
    sample = selected[1] if selected else {}
    sample_timestamp = selected[2] if selected else snapshot.get("last_seen")
    value = sample.get("value")
    unit = str(sample.get("unit") or "lux")
    sample_online = value is not None
    device_online = bool(freshness["online"])
    online = device_online and sample_online
    if online:
        assistant_message = f"已读取 I2C Bus S1 下 BH1750 的最近上报：光照 {value} {unit}。"
    elif sample_online:
        assistant_message = (
            f"最近一次 BH1750 历史样本为 {value} {unit}，"
            f"时间 {_format_sample_timestamp(sample_timestamp)}；设备当前没有新鲜上报，不能代表现在。"
        )
    else:
        assistant_message = "云端当前没有收到 BH1750 的有效光照样本。"

    return {
        "ok": True,
        "assistant_message": assistant_message,
        "source": source,
        "created_at": int(time.time()),
        "hardware_control": {
            "enabled": True,
            "action_kind": "observation_query",
            "device_id": settings.device_id,
            "query": {
                "version": "observation_query.v1",
                "channel": query.channel,
                "device": query.device,
                "capabilities": query.capabilities,
            },
            "result": {
                "online": online,
                "light": value,
                "unit": unit,
                "fresh": online,
                "sample_online": sample_online,
                "device_online": device_online,
                "age_sec": freshness["age_sec"],
                "timestamp": sample_timestamp,
                "sample_time": _format_sample_timestamp(sample_timestamp),
            },
            "intent_source": source,
            "intent_confidence": confidence,
            "reasoning_summary": reasoning_summary,
            "tool_trace": tool_trace or [],
            "knowledge_sources": knowledge_sources or [],
        },
    }


def _format_sample_timestamp(value: object) -> str:
    if isinstance(value, (int, float)):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(value)))
    if value is not None:
        text = str(value).strip()
        if text:
            return text
    return "未知"


def _try_manual_action_deploy(text: str, settings: Settings) -> dict[str, object] | None:
    parsed = _parse_servo_manual_action(text)
    if parsed is None:
        return None

    return _deploy_manual_action(
        parsed,
        settings,
        source="web_hardware_router:manual_action_v1",
        confidence=0.93,
        reasoning_summary="legacy manual action route",
    )


def _deploy_manual_action(
    parsed: dict[str, Any],
    settings: Settings,
    *,
    source: str,
    confidence: float,
    reasoning_summary: str = "",
    tool_trace: list[str] | None = None,
    knowledge_sources: list[str] | None = None,
) -> dict[str, object]:
    request_id = _web_request_id()
    timestamp = int(time.time())
    direction = str(parsed.get("direction") or "both")
    auto_reset = bool(parsed.get("auto_reset"))
    sequence = _build_servo_sweep_sequence(
        parsed["angle"],
        parsed["times"],
        parsed["duration_ms"],
        direction=direction,
        auto_reset=auto_reset,
    )
    manual_action = {
        "version": "manual_action.v1",
        "target": {
            "device": "SG90",
            "channel": "pwm.servo.1",
            "pin": "P105",
            "capability": "servo.sweep",
        },
        "params": {
            "angle": parsed["angle"],
            "times": parsed["times"],
            "duration_ms": parsed["duration_ms"],
            "direction": direction,
            "auto_reset": auto_reset,
            "return_angle": 90 if auto_reset else None,
        },
        "actions": [
            {
                "device": "SG90",
                "method": "servo_set",
                "capability": "motor.servo.angle",
                "params": {"angle": angle, "duration_ms": duration_ms},
            }
            for angle, duration_ms in sequence
        ],
    }
    lua_code = "manual_action:SG90.servo_sweep"
    checksum = "sha256:" + hashlib.sha256(
        f"{manual_action}:{lua_code}".encode("utf-8")
    ).hexdigest()
    script_id = "manual_" + hashlib.sha256(
        f"{request_id}:{checksum}".encode("utf-8")
    ).hexdigest()[:12]
    if settings.mqtt_enabled and not settings.mqtt_script_secret:
        raise HTTPException(status_code=502, detail="mqtt_script_secret is required when MQTT publishing is enabled")

    payload = {
        "script_id": script_id,
        "intent_type": "manual_action",
        "version": "manual_action.v1",
        "lua_code": lua_code,
        "need_confirm": True,
        "checksum": checksum,
        "target_device_id": settings.device_id,
        "auth_signature": build_script_signature(
            settings.mqtt_script_secret or "preview-secret",
            request_id,
            script_id,
            "manual_action",
            checksum,
            timestamp,
            settings.device_id,
        ),
        "manual_action": manual_action,
    }
    message = MqttEnvelope(
        request_id=request_id,
        type="deploy_script",
        timestamp=timestamp,
        payload=payload,
    )
    publisher = MqttPublisher(settings)
    try:
        publish_result = publisher.publish_script(settings.device_id, message)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    ack = None
    if publish_result.published and settings.web_hardware_wait_for_ack:
        ack = device_state_store.wait_for_deploy_ack(
            device_id=settings.device_id,
            request_id=request_id,
            timeout_sec=settings.deploy_ack_timeout_sec,
        )
    deploy_view = _finalize_web_deploy_view(
        {
            "ok": True,
            "request_id": request_id,
            "device_id": settings.device_id,
            "topic": publish_result.topic,
            "mqtt_enabled": settings.mqtt_enabled,
            "message": message.model_dump(mode="json"),
            "published": publish_result.published,
            "ack_received": ack is not None,
            "ack": ack,
        },
        wait_for_ack=settings.web_hardware_wait_for_ack,
        intent_source=source,
        intent_confidence=confidence,
    )
    stage_label = deploy_view.get("delivery_stage_label") or _delivery_stage_label(str(deploy_view.get("delivery_stage") or ""))
    direction_label = {"both": "左右往复", "left": "向左", "right": "向右"}.get(direction, "左右往复")
    finish_label = "最后自动回到 90 度" if auto_reset else f"执行后保持在 {sequence[-1][0]} 度"
    assistant_message = (
        f"已识别为独立执行器控制：通过 PWM P105 控制 SG90，"
        f"按 {parsed['angle']} 度摆幅{direction_label} {parsed['times']} 次，{finish_label}。\n\n"
        f"下发状态：{stage_label}，{deploy_view.get('message') or ''}"
    ).strip()
    return {
        "ok": True,
        "assistant_message": assistant_message,
        "source": source,
        "created_at": int(time.time()),
        "hardware_control": {
            "enabled": True,
            "action_kind": "manual_action",
            "request_id": request_id,
            "device_id": settings.device_id,
            "delivery_stage": deploy_view.get("delivery_stage"),
            "delivery_stage_label": stage_label,
            "status": deploy_view.get("status"),
            "manual_action": manual_action,
            "deployment": deploy_view,
            "intent_source": source,
            "intent_confidence": confidence,
            "reasoning_summary": reasoning_summary,
            "tool_trace": tool_trace or [],
            "knowledge_sources": knowledge_sources or [],
        },
    }


def _parse_servo_manual_action(text: str) -> dict[str, Any] | None:
    normalized = _normalize_web_text(text)
    if not any(token in normalized for token in ("舵机", "sg90", "servo")):
        return None
    if any(token in normalized for token in ("温度", "湿度", "光照", "照度", "lux", "达到", "超过", "大于", "小于", "低于", "当")):
        return None
    if not any(token in normalized for token in ("转动", "旋转", "摆动", "来回", "往复")):
        return None

    angle = _extract_int_before_unit(normalized, "度", default=60)
    times = _extract_repeat_count(normalized, default=1)
    duration_ms = _extract_duration_ms(normalized, default=350)
    if not 1 <= times <= 10:
        raise HTTPException(status_code=422, detail="manual SG90 sweep times must be between 1 and 10")
    if not 1 <= angle <= 90:
        raise HTTPException(status_code=422, detail="manual SG90 sweep angle must be between 1 and 90")
    if not 50 <= duration_ms <= 5000:
        raise HTTPException(status_code=422, detail="manual SG90 duration_ms must be between 50 and 5000")
    has_left = "向左" in normalized or "左转" in normalized
    has_right = "向右" in normalized or "右转" in normalized
    direction = "left" if has_left and not has_right else "right" if has_right and not has_left else "both"
    return {
        "angle": angle,
        "times": times,
        "duration_ms": duration_ms,
        "direction": direction,
        "auto_reset": any(token in normalized for token in ("自动复位", "自动回中", "回中", "回到90")),
    }


def _build_servo_sweep_sequence(
    angle: int,
    times: int,
    duration_ms: int,
    *,
    direction: str = "both",
    auto_reset: bool = False,
) -> list[tuple[int, int]]:
    low = max(0, 90 - angle)
    high = min(180, 90 + angle)
    sequence: list[tuple[int, int]] = []
    for index in range(times):
        if direction in {"both", "left"}:
            sequence.append((low, duration_ms))
        if direction == "both":
            sequence.append((high, duration_ms))
        elif direction == "left":
            if index < times - 1 or auto_reset:
                sequence.append((90, duration_ms))
        elif direction == "right":
            sequence.append((high, duration_ms))
            if index < times - 1 or auto_reset:
                sequence.append((90, duration_ms))
    if auto_reset and (not sequence or sequence[-1][0] != 90):
        sequence.append((90, max(120, min(duration_ms, 800))))
    return sequence


def _extract_int_before_unit(text: str, unit: str, *, default: int) -> int:
    match = re.search(rf"(\d+)\s*{re.escape(unit)}", text)
    return int(match.group(1)) if match else default


def _extract_repeat_count(text: str, *, default: int) -> int:
    match = re.search(r"(\d+)\s*(?:次|遍|回)", text)
    if match:
        return int(match.group(1))
    chinese_numbers = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5}
    for token, value in chinese_numbers.items():
        if f"{token}次" in text or f"{token}遍" in text or f"{token}回" in text:
            return value
    return default


def _extract_duration_ms(text: str, *, default: int) -> int:
    match = re.search(r"(\d+)\s*(?:ms|毫秒)", text)
    if match:
        return int(match.group(1))
    return default


def _normalize_web_text(text: str) -> str:
    return text.strip().lower().replace("，", ",").replace("；", ";").replace("。", ".")


def _looks_like_explicit_rule_program(text: str) -> bool:
    normalized = _normalize_web_text(text)
    if len(normalized) < 8:
        return False
    has_sensor = any(token in normalized for token in ("aht20", "温度", "temperature"))
    has_condition = any(
        token in normalized
        for token in ("当", "达到", "到达", "超过", "大于", "高于", "低于", "小于", ">=", "<=", ">", "<")
    )
    has_actuator = any(token in normalized for token in ("舵机", "sg90", "servo"))
    has_action = any(token in normalized for token in ("转动", "旋转", "摆动", "来回", "往复", "驱动", "控制"))
    return has_sensor and has_condition and has_actuator and has_action


def _hardware_deploy_reply(program: RuleProgram, deploy_view: dict[str, object], stage_label: str) -> str:
    trigger = program.trigger
    angles = [str(action.params.get("angle")) for action in program.actions]
    message = str(deploy_view.get("message") or "").strip()
    detail = (
        f"已识别为硬件控制规则：当 {trigger.sensor} {trigger.operator} {trigger.value:g} 时，"
        f"按 {', '.join(angles)} 度序列驱动 SG90。"
    )
    if message:
        return f"{detail}\n\n下发状态：{stage_label}，{message}"
    return f"{detail}\n\n下发状态：{stage_label}"


def _web_request_id() -> str:
    return f"web_{int(time.time() * 1000) % 1000000000:09d}"
