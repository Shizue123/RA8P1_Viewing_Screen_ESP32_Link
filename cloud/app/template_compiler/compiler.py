from __future__ import annotations

import hashlib

from cloud.app.models import DeployScriptPayload, Intent, IntentType, RuleProgram
from cloud.app.registry.lua_api import validate_lua_api


def compile_intent_to_lua(intent: Intent) -> tuple[str, dict[str, object]]:
    if intent.intent_type == "screen_text":
        lua_code = _compile_screen_text(intent)
        validation = validate_lua_api(lua_code)
        if not validation["ok"]:
            raise ValueError("; ".join(str(error) for error in validation["errors"]))
        return lua_code, validation

    if intent.intent_type != "threshold_control":
        raise ValueError("only threshold_control is implemented in the V1 compiler")

    condition = intent.conditions
    if condition is None:
        raise ValueError("threshold_control requires conditions")
    lines = [
        "while true do",
        "  local data = aht20_read()",
        f"  if data.temp {condition.operator} {condition.value:g} then",
    ]

    for action in intent.actions:
        if action.method == "servo_set":
            angle = int(action.params.get("angle", 0))
            if not 0 <= angle <= 180:
                raise ValueError("servo_set angle must be in range 0..180")
            lines.append(f"    servo_set({angle})")
        elif action.method == "buzzer":
            freq = int(action.params.get("freq", 2000))
            ms = int(action.params.get("ms", 300))
            if not 20 <= freq <= 20000:
                raise ValueError("buzzer freq must be in range 20..20000")
            if not 1 <= ms <= 10000:
                raise ValueError("buzzer ms must be in range 1..10000")
            lines.append(f"    buzzer({freq}, {ms})")
        elif action.method == "led_rgb":
            r = _byte(action.params.get("r", 0), "r")
            g = _byte(action.params.get("g", 0), "g")
            b = _byte(action.params.get("b", 0), "b")
            lines.append(f"    led_rgb({r}, {g}, {b})")
        else:
            raise ValueError(f"unsupported action method: {action.method}")

    lines.extend(["  end", f"  delay({intent.loop_interval_ms})", "end"])
    lua_code = "\n".join(lines)
    validation = validate_lua_api(lua_code)
    if not validation["ok"]:
        raise ValueError("; ".join(str(error) for error in validation["errors"]))
    return lua_code, validation


def build_deploy_payload(intent: Intent, lua_code: str, need_confirm: bool) -> DeployScriptPayload:
    checksum = "sha256:" + hashlib.sha256(lua_code.encode("utf-8")).hexdigest()
    script_id = "script_" + hashlib.sha256(
        f"{intent.model_dump_json()}:{checksum}".encode("utf-8")
    ).hexdigest()[:12]
    return DeployScriptPayload(
        script_id=script_id,
        intent_type=intent.intent_type,
        version="v1",
        lua_code=lua_code,
        need_confirm=need_confirm,
        checksum=checksum,
    )


def compile_rule_program_to_lua(program: RuleProgram) -> tuple[str, dict[str, object]]:
    trigger = program.trigger
    lines = [
        "local last_run = 0",
        "while true do",
        "  local data = aht20_read()",
        f"  if data.temp {trigger.operator} {trigger.value:g} then",
        f"    if (millis() - last_run) >= {program.cooldown_ms} then",
    ]

    for action in program.actions:
        angle = int(action.params.get("angle", 90))
        duration_ms = int(action.params.get("duration_ms", 350))
        if not 0 <= angle <= 180:
            raise ValueError("rule_program servo_set angle must be in range 0..180")
        if not 50 <= duration_ms <= 5000:
            raise ValueError("rule_program duration_ms must be in range 50..5000")
        lines.append(f"    servo_set({angle})")
        lines.append(f"    delay({duration_ms})")

    lines.extend(["      last_run = millis()", "    end", "  end", f"  delay({program.loop_interval_ms})", "end"])
    lua_code = "\n".join(lines)
    validation = validate_lua_api(lua_code)
    if not validation["ok"]:
        raise ValueError("; ".join(str(error) for error in validation["errors"]))
    return lua_code, validation


def build_program_deploy_payload(program: RuleProgram, lua_code: str, need_confirm: bool) -> DeployScriptPayload:
    checksum = "sha256:" + hashlib.sha256(lua_code.encode("utf-8")).hexdigest()
    script_id = "script_" + hashlib.sha256(
        f"{program.model_dump_json()}:{checksum}".encode("utf-8")
    ).hexdigest()[:12]
    return DeployScriptPayload(
        script_id=script_id,
        intent_type=IntentType.rule_program,
        version="v1",
        lua_code=lua_code,
        need_confirm=need_confirm,
        checksum=checksum,
        rule_program=program,
    )


def _byte(value: object, label: str) -> int:
    number = int(value)
    if not 0 <= number <= 255:
        raise ValueError(f"led_rgb {label} must be in range 0..255")
    return number


def _compile_screen_text(intent: Intent) -> str:
    if len(intent.actions) != 1 or intent.actions[0].method != "screen_text":
        raise ValueError("screen_text intent requires one screen_text action")
    text = str(intent.actions[0].params.get("text", "")).strip()
    if not text:
        raise ValueError("screen_text text must not be empty")
    if len(text) > 64:
        raise ValueError("screen_text text must be 64 characters or fewer")
    return f"screen_text(\"{_lua_string(text)}\")"


def _lua_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " ")
