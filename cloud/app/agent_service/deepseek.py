from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass

from cloud.app.config import Settings
from cloud.app.knowledge_base import get_project_knowledge
from cloud.app.models import Intent, RuleProgram


@dataclass(frozen=True)
class DeepSeekIntentResult:
    intent: Intent
    raw_text: str


@dataclass(frozen=True)
class DeepSeekRuleProgramResult:
    program: RuleProgram
    raw_text: str


def generate_intent_with_deepseek(text: str, settings: Settings) -> DeepSeekIntentResult:
    if not settings.deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek")

    prompt = _build_prompt(text)
    request_body = {
        "model": settings.deepseek_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You generate JSON intent for a RA8P1 restricted hardware agent. "
                    "Return only one JSON object. Do not generate Lua or MQTT payloads."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
    }
    raw = _post_chat_completion(settings, request_body)
    decoded = json.loads(_extract_json_object(raw))
    return DeepSeekIntentResult(intent=Intent.model_validate(decoded), raw_text=raw)


def generate_rule_program_with_deepseek(text: str, settings: Settings) -> DeepSeekRuleProgramResult:
    if not settings.deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek")

    prompt = _build_rule_program_prompt(text)
    request_body = {
        "model": settings.deepseek_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You generate restricted JSON rule_program for a RA8P1 hardware agent. "
                    "Return only one JSON object. Do not generate Lua, C, MQTT topics, secrets, or shell commands."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
    }
    raw = _post_chat_completion(settings, request_body)
    decoded = json.loads(_extract_json_object(raw))
    return DeepSeekRuleProgramResult(program=RuleProgram.model_validate(decoded), raw_text=raw)


def _post_chat_completion(settings: Settings, body: dict[str, object]) -> str:
    message = _post_chat_completion_message(settings, body)
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("DeepSeek message content must be a string")
    return content


def _post_chat_completion_message(settings: Settings, body: dict[str, object]) -> dict[str, object]:
    url = settings.deepseek_base_url.rstrip("/") + "/chat/completions"
    timeout_sec = 60
    attempts = 2
    payload: dict[str, object] | None = None
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.deepseek_api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"DeepSeek API failed: HTTP {exc.code}: {detail}") from exc
        except (TimeoutError, socket.timeout) as exc:
            last_error = exc
            if attempt >= attempts:
                raise ValueError(
                    f"DeepSeek API timed out after {attempts} attempts (timeout={timeout_sec}s)"
                ) from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt >= attempts:
                raise ValueError(f"DeepSeek API failed: {exc.reason}") from exc

    if payload is None:
        raise ValueError(f"DeepSeek API failed without a response payload: {last_error}")

    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("DeepSeek API returned an unexpected response shape") from exc
    if not isinstance(message, dict):
        raise ValueError("DeepSeek message must be an object")
    return message


def _build_prompt(text: str) -> str:
    skills = get_project_knowledge().skills()["skills"]
    available = [skill for skill in skills if skill.get("status") == "available"]
    return json.dumps(
        {
            "user_text": text,
            "available_runtime_skills": available,
            "output_schema": {
                "intent_type": "threshold_control",
                "target_devices": ["AHT20", "SG90", "BUZZER"],
                "conditions": {"sensor": "AHT20.temp", "operator": ">", "value": 30},
                "actions": [
                    {"device": "SG90", "method": "servo_set", "params": {"angle": 180}},
                    {"device": "BUZZER", "method": "buzzer", "params": {"freq": 2000, "ms": 300}},
                ],
                "loop_interval_ms": 1000,
            },
            "hard_rules": [
                "Use only available_runtime_skills.",
                "Use only supported devices and allowed_lua_api implied by the selected skill.",
                "Return JSON only.",
                "Do not include markdown fences.",
                "Do not generate Lua.",
                "Do not generate MQTT topics or payloads.",
            ],
        },
        ensure_ascii=False,
    )


def _build_rule_program_prompt(text: str) -> str:
    return json.dumps(
        {
            "user_text": text,
            "hardware_baseline": {
                "network_path": "ESP32 is the only network transport path",
                "sensor": "AHT20.temp",
                "actuator": "SG90",
                "verified_loop": "threshold_control -> SG90 -> execution_state",
            },
            "output_schema": {
                "program_id": "",
                "version": "rule_program.v1",
                "trigger": {"sensor": "AHT20.temp", "operator": ">=", "value": 35},
                "actions": [
                    {"device": "SG90", "method": "servo_set", "params": {"angle": 30, "duration_ms": 300}},
                    {"device": "SG90", "method": "servo_set", "params": {"angle": 150, "duration_ms": 300}},
                    {"device": "SG90", "method": "servo_set", "params": {"angle": 30, "duration_ms": 350}},
                    {"device": "SG90", "method": "servo_set", "params": {"angle": 150, "duration_ms": 350}},
                    {"device": "SG90", "method": "servo_set", "params": {"angle": 30, "duration_ms": 400}},
                    {"device": "SG90", "method": "servo_set", "params": {"angle": 150, "duration_ms": 400}},
                    {"device": "SG90", "method": "servo_set", "params": {"angle": 90, "duration_ms": 400}},
                ],
                "loop_interval_ms": 1000,
                "cooldown_ms": 30000,
                "description": "当温度到35度时，舵机来回旋转两次",
            },
            "hard_rules": [
                "Return JSON only.",
                "Use version rule_program.v1.",
                "Use only trigger.sensor AHT20.temp.",
                "Use only SG90 servo_set actions.",
                "Angle must be integer 0..180.",
                "duration_ms must be integer 50..5000.",
                "If the user asks for speed to decrease, get slower, or 均匀下降, make duration_ms increase linearly across repeated sweeps, for example 300, 350, 400 for three sweeps.",
                "actions length must be 1..16.",
                "loop_interval_ms must be 100..60000.",
                "cooldown_ms must be 0..600000.",
                "Do not include markdown fences.",
                "Do not generate Lua, C, MQTT topics, secrets, or shell commands.",
            ],
        },
        ensure_ascii=False,
    )


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("DeepSeek response did not contain a JSON object")
    return stripped[start : end + 1]
