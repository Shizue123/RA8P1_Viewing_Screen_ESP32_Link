from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from cloud.app.agent_service.deepseek import generate_rule_program_with_deepseek
from cloud.app.agent_service.hermes_official import generate_rule_program_with_hermes_official
from cloud.app.config import Settings
from cloud.app.models import RuleProgram, RuleProgramAction, RuleProgramTrigger


_THRESHOLD_PATTERNS = [
    (re.compile(r"(?:温度|temperature).*?(?:超过|大于|高于|>)\s*(\d+(?:\.\d+)?)"), ">"),
    (re.compile(r"(?:温度|temperature).*?(?:到达|达到|到|不低于|至少|>=)\s*(\d+(?:\.\d+)?)"), ">="),
    (re.compile(r"(?:温度|temperature).*?(?:低于|小于|<)\s*(\d+(?:\.\d+)?)"), "<"),
    (re.compile(r"(?:温度|temperature).*?(?:不超过|至多|<=)\s*(\d+(?:\.\d+)?)"), "<="),
]
_SERVO_ANGLE_PATTERN = re.compile(r"(?:舵机|servo).*?(\d{1,3})\s*(?:度|degree|degrees)?", re.IGNORECASE)
_REPEAT_PATTERN = re.compile(r"([一二两三四五六七八九十\d]+)\s*(?:次|遍|rounds?|times?)", re.IGNORECASE)
_LOOP_SECONDS_PATTERN = re.compile(r"(?:每|间隔|周期|interval).*?(\d+(?:\.\d+)?)\s*(?:秒|s|sec|second|seconds)", re.IGNORECASE)
_LOOP_MS_PATTERN = re.compile(r"(?:每|间隔|周期|interval).*?(\d+(?:\.\d+)?)\s*(?:毫秒|ms)", re.IGNORECASE)
_COOLDOWN_SECONDS_PATTERN = re.compile(r"(?:冷却|间隔|cooldown).*?(\d+(?:\.\d+)?)\s*(?:秒|s|sec|second|seconds)", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedRuleProgram:
    program: RuleProgram
    source: str
    confidence: float
    notes: list[str]


def interpret_text_to_rule_program(text: str, settings: Settings | None = None) -> ParsedRuleProgram:
    provider = settings.llm_provider.lower() if settings is not None else ""

    if provider == "hermes_official":
        result = generate_rule_program_with_hermes_official(text, settings)
        return _validated_parsed_program(
            program=_with_program_id(result.program, text),
            source=f"hermes_official:{settings.hermes_official_model}+rule_program_v1",
            confidence=0.88,
            notes=["Official Hermes generated a restricted action plan; cloud schema validation accepted it"],
        )

    # For the verified temperature->SG90 grammar, prefer the deterministic path
    # so web deploys stay responsive even if the LLM is slow or unavailable.
    try:
        fast_path = _interpret_text_to_rule_program_rule_based(text)
    except ValueError:
        fast_path = None
    else:
        if provider == "deepseek":
            return ParsedRuleProgram(
                program=fast_path.program,
                source=f"{fast_path.source}+fastpath",
                confidence=max(fast_path.confidence, 0.8),
                notes=[*fast_path.notes, "rule-based fast path matched a supported rule_program grammar"],
            )
        return fast_path

    if provider == "deepseek":
        try:
            result = generate_rule_program_with_deepseek(text, settings)
            return _validated_parsed_program(
                program=_with_program_id(result.program, text),
                source=f"deepseek:{settings.deepseek_model}+rule_program_v1",
                confidence=0.84,
                notes=["DeepSeek generated a restricted action plan; cloud schema validation accepted it"],
            )
        except ValueError as exc:
            if settings.app_env.lower() not in {"dev", "test"}:
                raise
            raise ValueError(f"DeepSeek fallback reason: {exc}") from exc
    return _interpret_text_to_rule_program_rule_based(text)


def _interpret_text_to_rule_program_rule_based(text: str) -> ParsedRuleProgram:
    normalized = _normalize(text)
    trigger = _parse_trigger(normalized)
    actions = _parse_servo_actions(normalized)
    program = RuleProgram(
        program_id=_program_id_for_text(normalized),
        trigger=trigger,
        actions=actions,
        loop_interval_ms=_parse_loop_interval_ms(normalized),
        cooldown_ms=_parse_cooldown_ms(normalized),
        description=_compact_description(normalized),
    )
    return _validated_parsed_program(
        program=program,
        source="rule_based_action_plan_v1",
        confidence=0.74,
        notes=[
            "rule_based_action_plan_v1 maps natural temperature language to env.temperature with AHT20.temp wire compatibility",
            "rule_based_action_plan_v1 maps SG90 servo actions to motor.servo.angle with SG90.servo_set wire compatibility",
        ],
    )


def _validated_parsed_program(
    program: RuleProgram,
    source: str,
    confidence: float,
    notes: list[str],
) -> ParsedRuleProgram:
    return ParsedRuleProgram(
        program=RuleProgram.model_validate(program.model_dump(mode="json")),
        source=source,
        confidence=confidence,
        notes=[
            *notes,
            "program validated against rule_program.v1 safety bounds",
            "first hardware target is SG90 only; BUZZER and arbitrary code remain deferred",
        ],
    )


def _normalize(text: str) -> str:
    return text.strip().replace("，", ",").replace("。", ".").replace("：", ":")


def _parse_trigger(text: str) -> RuleProgramTrigger:
    for pattern, operator in _THRESHOLD_PATTERNS:
        match = pattern.search(text)
        if match:
            return RuleProgramTrigger(
                sensor="AHT20.temp",
                capability="env.temperature",
                operator=operator,
                value=float(match.group(1)),
            )
    raise ValueError("no supported temperature threshold found for rule_program")


def _parse_servo_actions(text: str) -> list[RuleProgramAction]:
    lower = text.lower()
    if "舵机" not in text and "servo" not in lower:
        raise ValueError("no supported SG90 servo action found for rule_program")

    if any(keyword in text for keyword in ("来回", "往返", "摆动")) or "back and forth" in lower:
        repeat = _parse_repeat_count(text)
        decelerating = _wants_decelerating_servo(text)
        actions: list[RuleProgramAction] = []
        for index in range(repeat):
            duration_ms = 300 + index * 50 if decelerating else 350
            actions.append(_servo_action(30, duration_ms))
            actions.append(_servo_action(150, duration_ms))
        actions.append(_servo_action(90, 300 + max(0, repeat - 1) * 50 if decelerating else 350))
        return actions

    angle_match = _SERVO_ANGLE_PATTERN.search(text)
    angle = int(angle_match.group(1)) if angle_match else 90
    return [_servo_action(angle)]


def _servo_action(angle: int, duration_ms: int = 350) -> RuleProgramAction:
    return RuleProgramAction(device="SG90", method="servo_set", params={"angle": angle, "duration_ms": duration_ms})


def _wants_decelerating_servo(text: str) -> bool:
    lower = text.lower()
    if "舵机" not in text and "servo" not in lower:
        return False
    return any(token in text or token in lower for token in ("速度", "速率", "speed")) and any(
        token in text or token in lower
        for token in ("下降", "降低", "减速", "变慢", "越来越慢", "decrease", "slower")
    )


def _parse_repeat_count(text: str) -> int:
    match = _REPEAT_PATTERN.search(text)
    if not match:
        return 1
    value = match.group(1)
    if value.isdigit():
        return _bounded_repeat(int(value))
    chinese_numbers = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    return _bounded_repeat(chinese_numbers.get(value, 1))


def _bounded_repeat(value: int) -> int:
    return max(1, min(value, 7))


def _parse_loop_interval_ms(text: str) -> int:
    ms_match = _LOOP_MS_PATTERN.search(text)
    if ms_match:
        return _bounded_interval(int(float(ms_match.group(1))))
    seconds_match = _LOOP_SECONDS_PATTERN.search(text)
    if seconds_match:
        return _bounded_interval(int(float(seconds_match.group(1)) * 1000))
    return 1000


def _parse_cooldown_ms(text: str) -> int:
    seconds_match = _COOLDOWN_SECONDS_PATTERN.search(text)
    if seconds_match:
        return max(0, min(int(float(seconds_match.group(1)) * 1000), 600000))
    return 30000


def _bounded_interval(value: int) -> int:
    return max(100, min(value, 60000))


def _program_id_for_text(text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    return f"rp_{digest}"


def _with_program_id(program: RuleProgram, text: str) -> RuleProgram:
    if program.program_id:
        return program
    data = program.model_dump(mode="json")
    data["program_id"] = _program_id_for_text(text)
    return RuleProgram.model_validate(data)


def _compact_description(text: str) -> str:
    return text[:160]
