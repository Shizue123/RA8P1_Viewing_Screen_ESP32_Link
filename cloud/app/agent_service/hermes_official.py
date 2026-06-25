from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from cloud.app.config import Settings
from cloud.app.models import Intent, RuleProgram


@dataclass(frozen=True)
class HermesOfficialIntentResult:
    intent: Intent
    raw_text: str


@dataclass(frozen=True)
class HermesOfficialRuleProgramResult:
    program: RuleProgram
    raw_text: str


@dataclass(frozen=True)
class HermesOfficialChatResult:
    assistant_message: str
    action_kind: str
    session_id: str
    raw_text: str
    intent: Intent | None = None
    program: RuleProgram | None = None


def chat_with_hermes_gateway(
    text: str,
    settings: Settings,
    *,
    conversation: str,
    context: dict[str, object] | None = None,
) -> str:
    return run_hermes_gateway_prompt(
        text,
        settings,
        conversation=conversation,
        instructions=(
            "You are the server-side Hermes assistant for the RA8P1 project. "
            "Answer in Chinese unless the user asks otherwise. You may inspect files in the current "
            "server workspace when that improves accuracy. Never invent hardware state or claim a "
            "device is online without current evidence. The current web milestone is conversation "
            "and server knowledge access; do not deploy hardware actions."
        ),
        context=context,
        store=True,
    )


def run_hermes_gateway_prompt(
    text: str,
    settings: Settings,
    *,
    conversation: str,
    instructions: str,
    context: dict[str, object] | None = None,
    store: bool = False,
) -> str:
    gateway_url = settings.hermes_gateway_url.strip().rstrip("/")
    if not gateway_url:
        raise ValueError("HERMES_GATEWAY_URL is not configured")
    gateway_api_key = settings.hermes_gateway_api_key or settings.api_server_key
    if not gateway_api_key:
        raise ValueError("HERMES_GATEWAY_API_KEY is not configured")

    if context:
        instructions += "\nServer context:\n" + json.dumps(context, ensure_ascii=False)

    payload = json.dumps(
        {
            "model": "hermes-agent",
            "input": text,
            "instructions": instructions,
            "conversation": conversation,
            "store": store,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{gateway_url}/v1/responses",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {gateway_api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=max(10.0, settings.hermes_official_timeout_sec)) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"Hermes gateway returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ValueError(f"Hermes gateway is unavailable: {exc}") from exc

    output = decoded.get("output")
    if not isinstance(output, list):
        raise ValueError("Hermes gateway returned no output")
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "output_text" and part.get("text"):
                chunks.append(str(part["text"]))
    assistant_message = "\n".join(chunks).strip()
    if not assistant_message:
        raise ValueError("Hermes gateway returned an empty assistant message")
    return assistant_message


def generate_intent_with_hermes_official(text: str, settings: Settings) -> HermesOfficialIntentResult:
    if not settings.hermes_official_enabled:
        raise ValueError("HERMES_OFFICIAL_ENABLED is required when LLM_PROVIDER=hermes_official")
    raw = _run_hermes_oneshot(_build_intent_prompt(text), settings)
    decoded = json.loads(_extract_json_object(raw))
    return HermesOfficialIntentResult(intent=Intent.model_validate(decoded), raw_text=raw)


def generate_rule_program_with_hermes_official(text: str, settings: Settings) -> HermesOfficialRuleProgramResult:
    if not settings.hermes_official_enabled:
        raise ValueError("HERMES_OFFICIAL_ENABLED is required when LLM_PROVIDER=hermes_official")
    raw = _run_hermes_oneshot(_build_rule_program_prompt(text), settings)
    decoded = json.loads(_extract_json_object(raw))
    return HermesOfficialRuleProgramResult(program=RuleProgram.model_validate(decoded), raw_text=raw)


def chat_with_hermes_official(
    text: str,
    settings: Settings,
    *,
    session_id: str | None = None,
    device_context: dict[str, object] | None = None,
) -> HermesOfficialChatResult:
    if not settings.hermes_official_enabled:
        raise ValueError("HERMES_OFFICIAL_ENABLED is required when LLM_PROVIDER=hermes_official")
    before_session_id = _latest_session_id(settings)
    raw = _run_hermes_prompt(
        _build_chat_prompt(text, device_context or {}),
        settings,
        session_id=session_id,
    )
    resolved_session_id = session_id or _latest_session_id(settings)
    if not resolved_session_id or resolved_session_id == before_session_id and session_id is None:
        raise ValueError("Hermes official did not create a resumable session")

    try:
        decoded = json.loads(_extract_json_object(raw))
    except ValueError:
        assistant_message = raw.strip()
        if not assistant_message:
            raise
        return HermesOfficialChatResult(
            assistant_message=assistant_message,
            action_kind="none",
            session_id=resolved_session_id,
            raw_text=raw,
        )

    action_kind = str(decoded.get("action_kind") or "none")
    if action_kind not in {"none", "intent", "rule_program"}:
        raise ValueError(f"Hermes official returned unsupported action_kind: {action_kind}")
    assistant_message = str(decoded.get("assistant_message") or "").strip()
    if not assistant_message:
        raise ValueError("Hermes official returned an empty assistant_message")

    intent = None
    program = None
    if action_kind == "intent":
        intent_payload = decoded.get("intent")
        if not isinstance(intent_payload, dict):
            raise ValueError("Hermes official returned action_kind=intent without an intent object")
        intent = Intent.model_validate(intent_payload)
    elif action_kind == "rule_program":
        program_payload = decoded.get("program")
        if not isinstance(program_payload, dict):
            raise ValueError("Hermes official returned action_kind=rule_program without a program object")
        program = RuleProgram.model_validate(program_payload)

    return HermesOfficialChatResult(
        assistant_message=assistant_message,
        action_kind=action_kind,
        session_id=resolved_session_id,
        raw_text=raw,
        intent=intent,
        program=program,
    )


def _run_hermes_oneshot(prompt: str, settings: Settings) -> str:
    return _run_hermes_prompt(prompt, settings)


def _run_hermes_prompt(prompt: str, settings: Settings, *, session_id: str | None = None) -> str:
    uv_path = settings.hermes_official_uv_path.strip()
    if not uv_path:
        raise ValueError("HERMES_OFFICIAL_UV_PATH is not configured")

    workdir = settings.hermes_official_workdir.strip()
    if not workdir:
        raise ValueError("HERMES_OFFICIAL_WORKDIR is not configured")
    workdir_path = Path(workdir)
    if not workdir_path.exists():
        raise ValueError(f"Hermes workdir does not exist: {workdir_path}")

    if not settings.deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY is required when using hermes_official")

    env = os.environ.copy()
    env["DEEPSEEK_API_KEY"] = settings.deepseek_api_key
    env["DEEPSEEK_BASE_URL"] = _normalize_deepseek_base_url(settings.deepseek_base_url)
    env["HERMES_INFERENCE_MODEL"] = f"deepseek/{settings.hermes_official_model}"

    command = [
        uv_path,
        "run",
        "--extra",
        "web",
        "--extra",
        "mcp",
        "--extra",
        "acp",
        "hermes",
        "--ignore-user-config",
        "--provider",
        "deepseek",
        "-m",
        settings.hermes_official_model,
    ]
    if session_id:
        command.extend(["--resume", session_id])
    command.extend(["-z", prompt])

    try:
        completed = subprocess.run(
            command,
            cwd=str(workdir_path),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(10.0, settings.hermes_official_timeout_sec),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"Hermes official timed out after {settings.hermes_official_timeout_sec:.0f}s") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise ValueError(f"Hermes official failed: {detail or f'exit code {completed.returncode}'}")

    raw = completed.stdout.strip()
    if not raw:
        raise ValueError("Hermes official returned an empty response")
    return raw


def _latest_session_id(settings: Settings) -> str:
    completed = _run_hermes_internal_command(
        settings,
        [
            "sessions",
            "list",
            "--source",
            "cli",
            "--limit",
            "1",
        ],
    )
    session_pattern = re.compile(r"\b\d{8}_\d{6}_[0-9a-f]+\b")
    for line in completed.stdout.splitlines():
        match = session_pattern.search(line)
        if match:
            return match.group(0)
    return ""


def _run_hermes_internal_command(settings: Settings, args: list[str]) -> subprocess.CompletedProcess[str]:
    uv_path = settings.hermes_official_uv_path.strip()
    workdir = settings.hermes_official_workdir.strip()
    command = [
        uv_path,
        "run",
        "--extra",
        "web",
        "--extra",
        "mcp",
        "--extra",
        "acp",
        "hermes",
        "--ignore-user-config",
        *args,
    ]
    return subprocess.run(
        command,
        cwd=workdir,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(10.0, settings.hermes_official_timeout_sec),
        check=False,
    )


def _normalize_deepseek_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Hermes official response did not contain a JSON object")
    return stripped[start : end + 1]


def _build_intent_prompt(text: str) -> str:
    return json.dumps(
        {
            "task": "Interpret the user's request for the RA8P1 cloud agent.",
            "user_text": text,
            "workspace_expectation": (
                "You are running inside the embedded-agent cloud workspace. "
                "Use local project knowledge or tools only if it materially improves accuracy."
            ),
            "output_schema": {
                "intent_type": "threshold_control",
                "target_devices": ["AHT20", "SG90", "SCREEN", "BUZZER", "RGB_LED"],
                "conditions": {"sensor": "AHT20.temp", "operator": ">=", "value": 25},
                "actions": [
                    {"device": "SG90", "method": "servo_set", "params": {"angle": 180}},
                    {"device": "SCREEN", "method": "screen_text", "params": {"text": "Hello"}},
                ],
                "loop_interval_ms": 1000,
            },
            "hard_rules": [
                "Return exactly one JSON object and nothing else.",
                "Use only intent_type screen_text or threshold_control.",
                "For threshold_control, use only sensor AHT20.temp.",
                "Allowed action methods: servo_set, buzzer, led_rgb, screen_text.",
                "Do not generate Lua, shell commands, or MQTT payloads.",
            ],
        },
        ensure_ascii=False,
    )


def _build_rule_program_prompt(text: str) -> str:
    return json.dumps(
        {
            "task": "Plan a bounded RA8P1 hardware rule_program.",
            "user_text": text,
            "workspace_expectation": (
                "You are running inside the embedded-agent cloud workspace. "
                "Inspect local project knowledge or tools only when it helps produce a safer program."
            ),
            "output_schema": {
                "program_id": "",
                "version": "rule_program.v1",
                "trigger": {"sensor": "AHT20.temp", "operator": ">=", "value": 25},
                "actions": [
                    {"device": "SG90", "method": "servo_set", "params": {"angle": 30, "duration_ms": 300}},
                    {"device": "SG90", "method": "servo_set", "params": {"angle": 150, "duration_ms": 300}},
                    {"device": "SG90", "method": "servo_set", "params": {"angle": 30, "duration_ms": 350}},
                    {"device": "SG90", "method": "servo_set", "params": {"angle": 150, "duration_ms": 350}},
                    {"device": "SG90", "method": "servo_set", "params": {"angle": 90, "duration_ms": 350}},
                ],
                "loop_interval_ms": 1000,
                "cooldown_ms": 30000,
                "description": "当温度到25度时，舵机来回旋转一次",
            },
            "hard_rules": [
                "Return exactly one JSON object and nothing else.",
                "Use version rule_program.v1.",
                "Use only trigger.sensor AHT20.temp.",
                "Use only SG90 servo_set actions.",
                "Angle must be integer 0..180.",
                "duration_ms must be integer 50..5000.",
                "If the user asks for speed to decrease, get slower, or 均匀下降, make duration_ms increase linearly across repeated sweeps, for example 300, 350, 400 for three sweeps.",
                "actions length must be 1..16.",
                "Do not generate Lua, C, shell commands, or MQTT payloads.",
            ],
        },
        ensure_ascii=False,
    )


def _build_chat_prompt(text: str, device_context: dict[str, object]) -> str:
    return json.dumps(
        {
            "task": "Act as the cloud Hermes operator for the RA8P1 hardware system.",
            "user_text": text,
            "current_device_context": device_context,
            "hardware_reality": [
                "Temperature-triggered actions depend on AHT20 telemetry being online and sampled.",
                "If current_device_context.diagnostics shows AHT20 offline, a temperature rule can be deployed and armed but cannot truthfully be described as triggered.",
                "Use current_device_context.diagnostics.i2c and hardware_capabilities to understand what Bus S1 currently exposes; do not assume every 0x38 device is definitely AHT20 unless diagnostics say so.",
                "When reporting progress, distinguish answered vs planned vs published vs acked vs executed vs blocked by hardware.",
                "SG90 servo motion may require independent servo power; do not claim physical movement unless the device state proves execution.",
            ],
            "output_schema": {
                "assistant_message": "Explain what you understood and what you are doing.",
                "action_kind": "none",
                "intent": {
                    "intent_type": "screen_text",
                    "target_devices": ["SCREEN"],
                    "actions": [{"device": "SCREEN", "method": "screen_text", "params": {"text": "Hello"}}],
                    "loop_interval_ms": 1000,
                },
                "program": {
                    "program_id": "",
                    "version": "rule_program.v1",
                    "trigger": {"sensor": "AHT20.temp", "operator": ">=", "value": 25},
                    "actions": [{"device": "SG90", "method": "servo_set", "params": {"angle": 90, "duration_ms": 350}}],
                    "loop_interval_ms": 1000,
                    "cooldown_ms": 30000,
                    "description": "当温度到25度时，舵机回到90度",
                },
            },
            "policy": [
                "Return exactly one JSON object and nothing else.",
                "Always fill assistant_message with a natural-language reply for the user.",
                "If the user is asking a question, wants analysis, or the request should not trigger hardware, use action_kind=none.",
                "If the request fits screen_text, buzzer, led_rgb, or threshold_control intent JSON, use action_kind=intent.",
                "If the request needs a bounded SG90 temperature rule loop, use action_kind=rule_program.",
                "If SG90 speed should decrease over repeated sweeps, encode that as progressively larger duration_ms values.",
                "Use current_device_context.diagnostics when explaining hardware blockers or execution status.",
                "Never describe published or ACKed work as completed unless device state proves execution.",
                "Only use intent_type screen_text or threshold_control.",
                "For threshold_control and rule_program, sensor must be AHT20.temp.",
                "Do not generate Lua, shell commands, or MQTT payloads.",
            ],
        },
        ensure_ascii=False,
    )
