from __future__ import annotations

import json
import secrets
import ast
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

from cloud.app.agent_service.deepseek import (
    _extract_json_object,
    _post_chat_completion_message,
)
from cloud.app.agent_service.hermes_official import run_hermes_gateway_prompt
from cloud.app.agent_service.web_hardware_tools import (
    execute_web_hardware_tool,
    validate_rule_program_semantics,
    web_hardware_tool_definitions,
)
from cloud.app.config import Settings
from cloud.app.models import RuleProgram


JsonObject = dict[str, Any]
_LOCAL_TZ = ZoneInfo("Asia/Shanghai")
ObservationDevice = Literal["AHT20", "BH1750"]
ObservationCapability = Literal["env.temperature", "env.humidity", "env.light.lux"]

_DEVICE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "AHT20": ("env.temperature", "env.humidity"),
    "BH1750": ("env.light.lux",),
}
_CAPABILITY_DEVICE: dict[str, str] = {
    "env.temperature": "AHT20",
    "env.humidity": "AHT20",
    "env.light.lux": "BH1750",
}


class WebObservationQuery(BaseModel):
    device: ObservationDevice | None = "AHT20"
    devices: list[ObservationDevice] = Field(default_factory=list, max_length=4)
    channel: Literal["i2c.s1"] = "i2c.s1"
    capabilities: list[ObservationCapability] = Field(
        default_factory=lambda: ["env.temperature", "env.humidity"]
    )

    @model_validator(mode="before")
    @classmethod
    def drop_default_device_for_capability_only_requests(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if (
            payload.get("capabilities")
            and "device" not in payload
            and "devices" not in payload
        ):
            payload["device"] = None
        return payload

    @model_validator(mode="after")
    def normalize_targets(self) -> "WebObservationQuery":
        devices: list[str] = []
        if self.device:
            devices.append(self.device)
        devices.extend(self.devices)
        devices = list(dict.fromkeys(devices))

        capabilities = list(dict.fromkeys(self.capabilities))
        if not devices and not capabilities:
            devices = ["AHT20"]
        if not capabilities:
            for device in devices:
                capabilities.extend(_DEVICE_CAPABILITIES.get(device, ()))
        capabilities = list(dict.fromkeys(capabilities))
        for capability in capabilities:
            mapped = _CAPABILITY_DEVICE.get(capability)
            if mapped and mapped not in devices:
                devices.append(mapped)
        if not devices:
            devices = ["AHT20"]
        if not capabilities:
            capabilities = list(_DEVICE_CAPABILITIES["AHT20"])

        self.devices = [device for device in devices if device in _DEVICE_CAPABILITIES]
        self.capabilities = [
            capability for capability in capabilities if capability in _CAPABILITY_DEVICE
        ]
        self.device = self.devices[0] if self.devices else "AHT20"
        return self


class WebManualAction(BaseModel):
    device: Literal["SG90"] = "SG90"
    channel: Literal["pwm.servo.1"] = "pwm.servo.1"
    method: Literal["servo_sweep"] = "servo_sweep"
    angle: int = Field(default=60, ge=1, le=90)
    times: int = Field(default=1, ge=1, le=10)
    duration_ms: int = Field(default=350, ge=50, le=5000)
    direction: Literal["both", "left", "right"] = "both"

    @field_validator("device", mode="before")
    @classmethod
    def normalize_device(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        normalized = value.strip().upper().replace("-", "").replace("_", "")
        return "SG90" if normalized in {"AG90", "SG90SERVO", "SERVO"} else value


class WebHardwareDecision(BaseModel):
    assistant_message: str = Field(min_length=1, max_length=1200)
    action_kind: Literal["none", "observation_query", "manual_action", "rule_program", "automation_task"] = "none"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    requires_confirmation: bool = True
    reasoning_summary: str = Field(default="", max_length=400)
    observation_query: WebObservationQuery | None = None
    manual_action: WebManualAction | None = None
    program: RuleProgram | None = None
    automation_task: dict[str, Any] | None = None
    tool_trace: list[str] = Field(default_factory=list, max_length=32)
    knowledge_sources: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_action_payload(self) -> "WebHardwareDecision":
        if self.action_kind == "observation_query" and self.observation_query is None:
            raise ValueError("observation_query action requires observation_query")
        if self.action_kind == "manual_action" and self.manual_action is None:
            raise ValueError("manual_action action requires manual_action")
        if self.action_kind == "rule_program" and self.program is None:
            raise ValueError("rule_program action requires program")
        if self.action_kind == "automation_task" and self.automation_task is None:
            raise ValueError("automation_task action requires automation_task")
        if self.action_kind == "none":
            self.observation_query = None
            self.manual_action = None
            self.program = None
            self.automation_task = None
        return self


def decide_web_hardware_action(
    text: str,
    settings: Settings,
    *,
    conversation_history: list[JsonObject],
    device_context: JsonObject,
) -> WebHardwareDecision:
    provider = settings.llm_provider.lower()
    if provider not in {"deepseek", "hermes_official"}:
        raise ValueError("LLM-first web hardware control requires a cloud DeepSeek-compatible provider")
    if not settings.deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY is required for LLM-first web hardware control")
    if provider == "hermes_official":
        try:
            return _decide_web_hardware_action_with_hermes(
                text,
                settings,
                conversation_history=conversation_history,
                device_context=device_context,
            )
        except Exception as hermes_exc:
            fallback_settings = settings.model_copy(update={"llm_provider": "deepseek"})
            try:
                decision = decide_web_hardware_action(
                    text,
                    fallback_settings,
                    conversation_history=conversation_history,
                    device_context=device_context,
                )
            except Exception as fallback_exc:
                raise ValueError(
                    "Hermes structured decision failed and DeepSeek fallback also failed: "
                    f"hermes={hermes_exc}; deepseek={fallback_exc}"
                ) from fallback_exc
            decision.tool_trace = [
                "hermes_structured_output_failed",
                str(hermes_exc)[:160],
                "deepseek_direct_fallback",
                *decision.tool_trace,
            ][:32]
            if decision.reasoning_summary:
                decision.reasoning_summary = (
                    f"{decision.reasoning_summary} [Hermes fallback to DeepSeek Direct]"
                )[:400]
            else:
                decision.reasoning_summary = "Hermes fallback to DeepSeek Direct"
            return decision
    model = settings.deepseek_model if provider == "deepseek" else settings.hermes_official_model
    messages: list[JsonObject] = [
        {
            "role": "system",
            "content": (
                "You are an autonomous cloud hardware agent. Use tools to inspect live device state, registered "
                "capabilities, approved project knowledge, and public documentation when needed. You decide which "
                "tools are useful and may make several tool calls before proposing a plan. For a hardware action, "
                "call validate_rule_program and revise the candidate until validation succeeds, then call "
                "submit_hardware_decision. Do not claim execution before the server returns execution evidence. "
                "A selected or registered device_id is not proof that hardware is powered on, connected, or online. "
                "Only say a device is online/connected when current evidence shows latest_device_state._device_online "
                "is true and last_seen is fresh. If the device is offline or last_seen is missing, say that the cloud "
                "only has a selected default device ID and no live online evidence yet. "
                "Never output or execute arbitrary MCU source, Lua, shell commands, credentials, or MQTT topics. "
                "For persistent sensor-triggered automation, scheduled SG90 actions, or time-based reports, choose action_kind=automation_task. "
                "If a time is given without saying today/once versus every day, do not create a task; ask the user to clarify the recurrence. "
                "Immediate SG90 actions hold the final angle by default; only request auto reset when explicitly asked. "
                "Sensor automation may use env.temperature, env.humidity, or env.light.lux independently. "
                "Safety validation limits execution; it must not replace semantic understanding."
            ),
        },
        {"role": "user", "content": _build_agent_request(text, conversation_history, device_context)},
    ]
    tools = [*web_hardware_tool_definitions(), _submit_decision_tool()]
    tool_trace: list[str] = []
    knowledge_sources: list[str] = []

    max_tool_rounds = 12
    for _round in range(max_tool_rounds):
        message = _post_chat_completion_message(
            settings,
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "temperature": 0,
            },
        )
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list) or not tool_calls:
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                try:
                    decoded = json.loads(_extract_json_object(content))
                    decision = WebHardwareDecision.model_validate(decoded)
                except (ValueError, json.JSONDecodeError):
                    decision = WebHardwareDecision(
                        assistant_message=content.strip()[:1200],
                        action_kind="none",
                        confidence=0.8,
                        requires_confirmation=False,
                        reasoning_summary="Completed an informational hardware query without scheduling control.",
                    )
                else:
                    validation = _validate_submitted_decision(decision, text, device_context)
                    if not validation["ok"]:
                        raise ValueError(
                            "hardware agent returned an invalid direct decision: "
                            + "; ".join(str(item) for item in validation.get("errors", []))
                        )
                decision.tool_trace = tool_trace
                decision.knowledge_sources = knowledge_sources
                return decision
            raise ValueError("hardware agent returned neither tool calls nor a decision")

        messages.append(_assistant_tool_message(message))
        for tool_call in tool_calls:
            call_id, name, arguments = _parse_tool_call(tool_call)
            tool_trace.append(name)
            if name == "submit_hardware_decision":
                try:
                    decision = WebHardwareDecision.model_validate(arguments)
                except Exception as exc:
                    result = {"ok": False, "errors": [str(exc)]}
                else:
                    result = _validate_submitted_decision(decision, text, device_context)
                    if result["ok"]:
                        decision.tool_trace = tool_trace
                        decision.knowledge_sources = knowledge_sources
                        return decision
                messages.append(_tool_result_message(call_id, name, result))
                continue

            result = execute_web_hardware_tool(
                name,
                arguments,
                user_text=text,
                device_context=device_context,
            )
            if name == "search_project_knowledge":
                knowledge_sources.extend(
                    str(item.get("path"))
                    for item in result.get("matches", [])
                    if isinstance(item, dict) and item.get("path")
                )
            elif name == "research_hardware_online":
                knowledge_sources.extend(
                    str(item.get("url"))
                    for item in result.get("results", [])
                    if isinstance(item, dict) and item.get("url")
                )
            elif name == "read_public_hardware_source" and result.get("ok") and result.get("url"):
                knowledge_sources.append(str(result["url"]))
            messages.append(_tool_result_message(call_id, name, result))

    raise ValueError(
        f"hardware agent did not produce a validated decision within {max_tool_rounds} tool rounds"
    )


def _decide_web_hardware_action_with_hermes(
    text: str,
    settings: Settings,
    *,
    conversation_history: list[JsonObject],
    device_context: JsonObject,
) -> WebHardwareDecision:
    instructions = (
        "You are the Hermes orchestration layer for a RA8P1 hardware cloud service. "
        "Use the supplied device capability context as authoritative. Return exactly one JSON object "
        "matching decision_schema. For temperature or humidity observations choose AHT20 with "
        "env.temperature/env.humidity. For light or illuminance observations choose BH1750 with "
        "env.light.lux. If the user asks for both temperature/humidity and light in one sentence, "
        "return one observation_query with devices [\"AHT20\", \"BH1750\"] and all requested "
        "capabilities together. Any request for a current sensor measurement must use observation_query; "
        "the server will read the newest sample after your decision. Never put sensor values in "
        "assistant_message from memory or context. Use action_kind=none for normal conversation, observation_query for sensor "
        "reads, manual_action for an immediate bounded SG90 move, automation_task for sensor rules, scheduled SG90 actions, "
        "one-time reports, daily reports, task listing, or task cancellation, and rule_program only when the user "
        "explicitly requests the legacy board-side single-rule path. A bare time such as 21:26 is ambiguous: "
        "ask whether it is today only or every day and return action_kind=none until clarified. "
        "SG90 holds its final target angle by default and auto-resets only when the user explicitly requests it. "
        "automation_task payload examples: "
        "{\"operation\":\"create\",\"task_type\":\"sensor_rule\",\"name\":\"...\",\"spec\":{\"capability\":\"env.humidity\","
        "\"operator\":\">=\",\"value\":60,\"direction\":\"left\",\"angle\":60,\"times\":2,\"duration_ms\":350,"
        "\"cooldown_sec\":30}}; or {\"operation\":\"create\",\"task_type\":\"scheduled_report\",\"name\":\"...\","
        "\"schedule_kind\":\"daily\",\"next_run_at\":null,\"spec\":{\"local_time\":\"08:00\"}}. "
        "Never invent telemetry or execution evidence."
    )
    latest_state = device_context.get("latest_device_state")
    latest_state = latest_state if isinstance(latest_state, dict) else {}
    context = {
        "temporal_context": _temporal_context(),
        "decision_schema": WebHardwareDecision.model_json_schema(),
        "conversation_history": conversation_history[-12:],
        "selected_device": {
            "device_id": device_context.get("device_id"),
            "online": latest_state.get("_device_online"),
            "last_seen": latest_state.get("last_seen"),
            "diagnostics": device_context.get("diagnostics"),
            "module_bindings": device_context.get("module_bindings"),
            "hardware_control_enabled": device_context.get("hardware_control_enabled"),
            "latest_device_state": latest_state,
            "signal_model": device_context.get("signal_model"),
        },
    }
    decision: WebHardwareDecision | None = None
    last_error: Exception | None = None
    for attempt in range(2):
        attempt_instructions = instructions
        if attempt:
            attempt_instructions += (
                " Your previous response was not valid strict JSON. Retry with double-quoted JSON keys and strings, "
                "no comments, no markdown fences, and no text before or after the single JSON object."
            )
        raw = run_hermes_gateway_prompt(
            text,
            settings,
            conversation=(
                f"web-hardware:{device_context.get('device_id') or 'default'}:"
                f"{secrets.token_hex(6)}"
            ),
            instructions=attempt_instructions,
            context=context,
            store=False,
        )
        try:
            decision = WebHardwareDecision.model_validate(
                _parse_structured_object(raw)
            )
            break
        except (ValueError, SyntaxError, json.JSONDecodeError) as exc:
            last_error = exc
    if decision is None:
        raise ValueError(f"Hermes did not return a valid structured decision: {last_error}")
    validation = _validate_submitted_decision(decision, text, device_context)
    if not validation["ok"]:
        raise ValueError(
            "Hermes returned an invalid hardware decision: "
            + "; ".join(str(item) for item in validation.get("errors", []))
        )
    decision.tool_trace = ["hermes_gateway", *decision.tool_trace]
    return decision


def _parse_structured_object(raw: str) -> dict[str, Any]:
    extracted = _extract_json_object(raw)
    try:
        decoded = json.loads(extracted)
    except json.JSONDecodeError:
        decoded = ast.literal_eval(extracted)
    if not isinstance(decoded, dict):
        raise ValueError("structured model response must be an object")
    return decoded


def synthesize_observation_reply(
    user_text: str,
    settings: Settings,
    *,
    query: WebObservationQuery,
    observation_result: JsonObject,
    conversation_history: list[JsonObject] | None = None,
    device_context: JsonObject | None = None,
) -> str:
    provider = settings.llm_provider.lower()
    prompt_payload = {
        "user_request": user_text,
        "conversation_history": [
            {
                "role": str(item.get("role") or ""),
                "content": str(item.get("content") or "")[:400],
            }
            for item in (conversation_history or [])[-8:]
            if isinstance(item, dict)
        ],
        "observation_query": query.model_dump(mode="json"),
        "observation_result": observation_result,
    }
    instructions = (
        "You are a Chinese hardware assistant for the RA8P1 project. "
        "First understand the user's natural-language intent, then answer using only the provided "
        "observation_result. Do not invent device connectivity, sensor values, freshness, or history. "
        "If some requested data is unavailable or stale, say that directly. If the user asked for multiple "
        "items, cover all requested items in one coherent reply. Keep the answer natural and concise. "
        "Do not output JSON, markdown tables, or pretend to have values that are missing."
    )
    if provider == "hermes_official":
        raw = run_hermes_gateway_prompt(
            user_text,
            settings,
            conversation=f"web-observation-reply:{secrets.token_hex(6)}",
            instructions=instructions,
            context={
                "device_context": device_context or {},
                "observation_prompt": prompt_payload,
            },
            store=False,
        )
        reply = raw.strip()
    else:
        message = _post_chat_completion_message(
            settings,
            {
                "model": settings.deepseek_model,
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)},
                ],
                "temperature": 0,
            },
        )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("DeepSeek observation synthesis returned empty content")
        reply = content.strip()
    return reply[:1200]


def _build_agent_request(
    text: str,
    conversation_history: list[JsonObject],
    device_context: JsonObject,
) -> str:
    compact_history = [
        {
            "role": str(item.get("role") or ""),
            "content": str(item.get("content") or "")[:900],
            "created_at": item.get("created_at"),
        }
        for item in conversation_history[-12:]
        if isinstance(item, dict)
    ]
    return json.dumps(
        {
            "current_user_text": text,
            "temporal_context": _temporal_context(),
            "conversation_history": compact_history,
            "selected_device_id": device_context.get("device_id"),
            "device_online": device_context.get("latest_device_state", {}).get("_device_online"),
            "device_last_seen": device_context.get("latest_device_state", {}).get("last_seen"),
            "task": (
                "Understand the user's actual goal. Decide whether to answer, observe, control SG90 now, or create "
                "a persistent temperature/humidity/light automation task or a one-time/daily report. Inspect tools "
                "instead of assuming hardware facts. Preserve threshold, direction, repeat count, amplitude, center "
                "semantics, schedule time, recurrence, and speed profile in the final structured payload."
            ),
        },
        ensure_ascii=False,
    )


def _temporal_context() -> JsonObject:
    now = datetime.now(_LOCAL_TZ)
    return {
        "timezone": "Asia/Shanghai",
        "utc_offset": "+08:00",
        "current_local_iso": now.isoformat(timespec="seconds"),
        "current_date": now.date().isoformat(),
        "current_time": now.time().isoformat(timespec="seconds"),
        "weekday": now.strftime("%A"),
        "instruction": (
            "Resolve 今天/明天/后天 and clock expressions against current_local_iso. "
            "Preserve year, month, day, hour, minute, and second in one-time schedules."
        ),
    }


def _submit_decision_tool() -> JsonObject:
    schema = WebHardwareDecision.model_json_schema()
    schema.pop("title", None)
    return {
        "type": "function",
        "function": {
            "name": "submit_hardware_decision",
            "description": (
                "Submit the final answer or validated hardware decision. For rule_program decisions, call "
                "validate_rule_program first and fix all errors."
            ),
            "parameters": schema,
        },
    }


def _assistant_tool_message(message: JsonObject) -> JsonObject:
    result: JsonObject = {
        "role": "assistant",
        "content": message.get("content"),
        "tool_calls": message.get("tool_calls"),
    }
    if message.get("reasoning_content") is not None:
        result["reasoning_content"] = message.get("reasoning_content")
    return result


def _parse_tool_call(tool_call: object) -> tuple[str, str, JsonObject]:
    if not isinstance(tool_call, dict):
        raise ValueError("tool call must be an object")
    function = tool_call.get("function")
    if not isinstance(function, dict):
        raise ValueError("tool call function must be an object")
    name = str(function.get("name") or "")
    raw_arguments = function.get("arguments")
    if isinstance(raw_arguments, str):
        arguments = json.loads(raw_arguments or "{}")
    elif isinstance(raw_arguments, dict):
        arguments = raw_arguments
    else:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ValueError(f"tool arguments for {name} must be an object")
    return str(tool_call.get("id") or name), name, arguments


def _tool_result_message(call_id: str, name: str, result: JsonObject) -> JsonObject:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": name,
        "content": json.dumps(result, ensure_ascii=False),
    }


def _validate_submitted_decision(
    decision: WebHardwareDecision,
    user_text: str,
    device_context: JsonObject,
) -> JsonObject:
    if decision.action_kind != "rule_program":
        return {"ok": True}
    if decision.program is None:
        return {"ok": False, "errors": ["rule_program decision requires program"]}
    validation = validate_rule_program_semantics(
        decision.program.model_dump(mode="json"),
        user_text,
        device_context,
    )
    if not validation["ok"]:
        return validation
    return {"ok": True, "validation": validation}
