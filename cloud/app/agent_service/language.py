from __future__ import annotations

import re
from dataclasses import dataclass

from cloud.app.config import Settings
from cloud.app.agent_service.deepseek import generate_intent_with_deepseek
from cloud.app.agent_service.hermes_official import generate_intent_with_hermes_official
from cloud.app.knowledge_base import get_project_knowledge
from cloud.app.models import Action, Condition, Intent, IntentType


_THRESHOLD_PATTERNS = [
    (re.compile(r"(?:温度|temperature).*?(?:超过|大于|高于|>)\s*(\d+(?:\.\d+)?)"), ">"),
    (re.compile(r"(?:温度|temperature).*?(?:到达|达到|到|不低于|至少|>=)\s*(\d+(?:\.\d+)?)"), ">="),
    (re.compile(r"(?:温度|temperature).*?(?:低于|小于|<)\s*(\d+(?:\.\d+)?)"), "<"),
    (re.compile(r"(?:温度|temperature).*?(?:不超过|至多|<=)\s*(\d+(?:\.\d+)?)"), "<="),
]
_SERVO_PATTERN = re.compile(r"(?:舵机|servo).*?(\d{1,3})\s*(?:度|degree|degrees)?")
_BUZZER_FREQ_PATTERN = re.compile(r"(?:蜂鸣|蜂鸣器|buzzer).*?(\d{2,5})\s*(?:hz|赫兹)", re.IGNORECASE)
_BUZZER_MS_PATTERN = re.compile(r"(?:蜂鸣|蜂鸣器|buzzer).*?(\d{1,5})\s*(?:ms|毫秒)", re.IGNORECASE)
_LOOP_SECONDS_PATTERN = re.compile(r"(?:每|间隔|周期|interval).*?(\d+(?:\.\d+)?)\s*(?:秒|s|sec|second|seconds)", re.IGNORECASE)
_LOOP_MS_PATTERN = re.compile(r"(?:每|间隔|周期|interval).*?(\d+(?:\.\d+)?)\s*(?:毫秒|ms)", re.IGNORECASE)
_QUOTED_TEXT_PATTERN = re.compile(r"[\"“”']([^\"“”']{1,64})[\"“”']")


@dataclass(frozen=True)
class ParsedIntent:
    intent: Intent
    source: str
    confidence: float
    notes: list[str]


def interpret_text_to_intent(text: str, settings: Settings | None = None) -> ParsedIntent:
    provider = settings.llm_provider.lower() if settings is not None else ""

    if provider == "hermes_official":
        result = generate_intent_with_hermes_official(text, settings)
        return _validated_parsed_intent(
            intent=result.intent,
            source=f"hermes_official:{settings.hermes_official_model}+gbrain",
            confidence=0.86,
            notes=["Official Hermes generated intent JSON; cloud validated it against GBrain and manifests"],
        )

    # Prefer the deterministic parser for the currently supported grammar so
    # the public UI is not blocked on LLM latency for simple board commands.
    try:
        fast_path = _interpret_text_to_intent_rule_based(text)
    except ValueError:
        fast_path = None
    else:
        if provider == "deepseek":
            return ParsedIntent(
                intent=fast_path.intent,
                source=f"{fast_path.source}+fastpath",
                confidence=max(fast_path.confidence, 0.78),
                notes=[*fast_path.notes, "rule-based fast path matched a supported command grammar"],
            )
        return fast_path

    if provider == "deepseek":
        try:
            result = generate_intent_with_deepseek(text, settings)
            return _validated_parsed_intent(
                intent=result.intent,
                source=f"deepseek:{settings.deepseek_model}+gbrain",
                confidence=0.82,
                notes=["DeepSeek generated intent JSON; cloud validated it against GBrain and manifests"],
            )
        except ValueError as exc:
            if settings.app_env.lower() not in {"dev", "test"}:
                raise
            raise ValueError(f"DeepSeek fallback reason: {exc}") from exc
    return _interpret_text_to_intent_rule_based(text)


def _interpret_text_to_intent_rule_based(text: str) -> ParsedIntent:
    normalized = _normalize(text)
    screen_text = _parse_screen_text(normalized)
    if screen_text is not None:
        intent = Intent(
            intent_type=IntentType.screen_text,
            target_devices=["SCREEN"],
            actions=[Action(device="SCREEN", method="screen_text", params={"text": screen_text})],
        )
        return _validated_parsed_intent(
            intent=intent,
            source="rule_based_screen_text+gbrain",
            confidence=0.76,
            notes=["rule_based_screen_text supports direct screen text display"],
        )

    condition = _parse_threshold_condition(normalized)
    actions = _parse_actions(normalized)
    if not actions:
        raise ValueError("no supported action found; mention servo, buzzer, or LED")

    intent = Intent(
        intent_type=IntentType.threshold_control,
        target_devices=_target_devices(actions),
        conditions=condition,
        actions=actions,
        loop_interval_ms=_parse_loop_interval_ms(normalized),
    )
    return _validated_parsed_intent(
        intent=intent,
        source="rule_based_v1+gbrain",
        confidence=0.72,
        notes=["rule_based_v1 supports temperature threshold control only"],
    )


def _validated_parsed_intent(intent: Intent, source: str, confidence: float, notes: list[str]) -> ParsedIntent:
    knowledge_validation = get_project_knowledge().validate_intent(intent)
    if not knowledge_validation["ok"]:
        raise ValueError("; ".join(str(error) for error in knowledge_validation["errors"]))
    return ParsedIntent(
        intent=intent,
        source=source,
        confidence=confidence,
        notes=[
            *notes,
            "intent validated against LLM Wiki, GBrain, and manifest constraints",
            *[str(warning) for warning in knowledge_validation["warnings"]],
        ],
    )


def _normalize(text: str) -> str:
    return text.strip().replace("，", ",").replace("。", ".").replace("：", ":")


def _parse_threshold_condition(text: str) -> Condition:
    for pattern, operator in _THRESHOLD_PATTERNS:
        match = pattern.search(text)
        if match:
            return Condition(sensor="AHT20.temp", operator=operator, value=float(match.group(1)))
    raise ValueError("no supported temperature threshold found")


def _parse_actions(text: str) -> list[Action]:
    actions: list[Action] = []
    servo_match = _SERVO_PATTERN.search(text)
    if "舵机" in text or "servo" in text.lower():
        angle = int(servo_match.group(1)) if servo_match else 180
        actions.append(Action(device="SG90", method="servo_set", params={"angle": angle}))

    if "蜂鸣" in text or "buzzer" in text.lower():
        freq_match = _BUZZER_FREQ_PATTERN.search(text)
        ms_match = _BUZZER_MS_PATTERN.search(text)
        freq = int(freq_match.group(1)) if freq_match else 2000
        ms = int(ms_match.group(1)) if ms_match else 300
        actions.append(Action(device="BUZZER", method="buzzer", params={"freq": freq, "ms": ms}))

    led_params = _parse_led_params(text)
    if led_params is not None:
        actions.append(Action(device="RGB_LED", method="led_rgb", params=led_params))

    return actions


def _parse_screen_text(text: str) -> str | None:
    lower = text.lower()
    if "screen" not in lower and "屏幕" not in text and "显示" not in text:
        return None

    quoted = _QUOTED_TEXT_PATTERN.search(text)
    if quoted:
        return quoted.group(1).strip()

    markers = ["屏幕显示", "显示", "screen text", "screen_text"]
    for marker in markers:
        index = lower.find(marker) if marker.isascii() else text.find(marker)
        if index >= 0:
            candidate = text[index + len(marker):].strip(" :：,，。.")
            if candidate:
                return candidate[:64]
    return "Hello from cloud"


def _parse_led_params(text: str) -> dict[str, int] | None:
    lower = text.lower()
    if "led" not in lower and "灯" not in text:
        return None
    if "红" in text or "red" in lower:
        return {"r": 255, "g": 0, "b": 0}
    if "绿" in text or "green" in lower:
        return {"r": 0, "g": 255, "b": 0}
    if "蓝" in text or "blue" in lower:
        return {"r": 0, "g": 0, "b": 255}
    return {"r": 255, "g": 255, "b": 255}


def _parse_loop_interval_ms(text: str) -> int:
    ms_match = _LOOP_MS_PATTERN.search(text)
    if ms_match:
        return _bounded_interval(int(float(ms_match.group(1))))
    seconds_match = _LOOP_SECONDS_PATTERN.search(text)
    if seconds_match:
        return _bounded_interval(int(float(seconds_match.group(1)) * 1000))
    return 1000


def _bounded_interval(value: int) -> int:
    return max(100, min(value, 60000))


def _target_devices(actions: list[Action]) -> list[str]:
    devices = ["AHT20"]
    for action in actions:
        if action.device not in devices:
            devices.append(action.device)
    return devices
