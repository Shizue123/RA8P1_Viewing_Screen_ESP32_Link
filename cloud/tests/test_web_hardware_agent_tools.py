from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from cloud.app.agent_service.web_hardware_agent import (
    _parse_structured_object,
    decide_web_hardware_action,
)
from cloud.app.agent_service.web_hardware_tools import (
    execute_web_hardware_tool,
    validate_rule_program_semantics,
)
from cloud.app.config import Settings


USER_TEXT = (
    "当所测到的温度达到30度以上时，让舵机以中轴90度为基准来回转动60度，"
    "往复三次，每次速度均匀下降"
)


def tool_call(call_id: str, name: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
            }
        ],
    }


def valid_program() -> dict[str, object]:
    return {
        "version": "rule_program.v1",
        "trigger": {"sensor": "AHT20.temp", "operator": ">=", "value": 30},
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
        "description": "30度触发三次减速往复",
    }


def device_context() -> dict[str, object]:
    return {
        "device_id": "ra8p1_test",
        "latest_device_state": {"_device_online": True},
        "signal_model": {
            "channels": [
                {"id": "i2c:s1", "hardware": [{"hardware_type": "AHT20", "status": "online"}]},
                {"id": "pwm:servo.1", "hardware": [{"hardware_type": "SG90", "status": "configured"}]},
            ]
        },
        "diagnostics": {},
    }


class WebHardwareAgentToolsTest(unittest.TestCase):
    def test_structured_parser_accepts_safe_python_style_dict(self) -> None:
        parsed = _parse_structured_object(
            "{'assistant_message': '普通对话', 'action_kind': 'none', 'confidence': 0.8}"
        )
        self.assertEqual("none", parsed["action_kind"])

    def test_semantic_validator_rejects_fixed_speed_for_deceleration(self) -> None:
        program = valid_program()
        for action in program["actions"]:
            action["params"]["duration_ms"] = 350

        result = validate_rule_program_semantics(program, USER_TEXT, device_context())

        self.assertFalse(result["ok"])
        self.assertIn("speed profile mismatch", " ".join(result["errors"]))

    def test_semantic_validator_accepts_matching_plan(self) -> None:
        result = validate_rule_program_semantics(valid_program(), USER_TEXT, device_context())

        self.assertTrue(result["ok"])
        self.assertEqual(3, result["requirements"]["repeat"])
        self.assertEqual(60, result["requirements"]["amplitude"])
        self.assertEqual("linear_deceleration", result["requirements"]["speed_profile"])

    def test_semantic_validator_counts_sweeps_without_assuming_final_center(self) -> None:
        program = valid_program()
        program["actions"] = program["actions"][:-1]

        result = validate_rule_program_semantics(
            program,
            "温度达到30度以上时，舵机来回转动60度，往复三次，每次速度均匀下降",
            device_context(),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(3, result["requirements"]["repeat"])

    def test_semantic_validator_requires_center_return_when_requested(self) -> None:
        program = valid_program()
        program["actions"] = program["actions"][:-1]

        result = validate_rule_program_semantics(program, USER_TEXT, device_context())

        self.assertFalse(result["ok"])
        self.assertIn("final action must return SG90 to 90 degrees", " ".join(result["errors"]))

    def test_rule_trigger_normalizes_capability_to_wire_sensor(self) -> None:
        program = valid_program()
        program["trigger"] = {
            "sensor": "AHT20",
            "capability": "env.temperature",
            "operator": ">=",
            "value": 30,
        }

        result = validate_rule_program_semantics(program, USER_TEXT, device_context())

        self.assertTrue(result["ok"])
        self.assertEqual("AHT20.temp", result["program"]["trigger"]["sensor"])

    def test_tool_agent_inspects_validates_and_submits(self) -> None:
        decision = {
            "assistant_message": "已查询设备和能力，并验证了三次线性减速往复规则。",
            "action_kind": "rule_program",
            "confidence": 0.94,
            "requires_confirmation": True,
            "reasoning_summary": "设备支持 AHT20 观测和 SG90 PWM 控制，候选计划已通过语义验证。",
            "program": valid_program(),
        }
        responses = [
            tool_call("call_device", "inspect_selected_device", {}),
            tool_call("call_caps", "list_hardware_capabilities", {"query": "AHT20 SG90"}),
            tool_call(
                "call_validate",
                "validate_rule_program",
                {"user_text": USER_TEXT, "program": valid_program()},
            ),
            tool_call("call_submit", "submit_hardware_decision", decision),
        ]

        with patch(
            "cloud.app.agent_service.web_hardware_agent._post_chat_completion_message",
            side_effect=responses,
        ):
            result = decide_web_hardware_action(
                USER_TEXT,
                Settings(
                    llm_provider="deepseek",
                    deepseek_api_key="test",
                    deepseek_model="deepseek-v4-pro",
                ),
                conversation_history=[],
                device_context=device_context(),
            )

        self.assertEqual("rule_program", result.action_kind)
        self.assertEqual(
            [
                "inspect_selected_device",
                "list_hardware_capabilities",
                "validate_rule_program",
                "submit_hardware_decision",
            ],
            result.tool_trace,
        )
        self.assertEqual([300, 300, 350, 350, 400, 400, 400], [
            action.params["duration_ms"] for action in result.program.actions
        ])

    def test_tool_agent_rejects_bad_submission_and_allows_model_revision(self) -> None:
        bad_program = valid_program()
        for action in bad_program["actions"]:
            action["params"]["duration_ms"] = 350
        bad_decision = {
            "assistant_message": "先提交一个固定速度方案。",
            "action_kind": "rule_program",
            "confidence": 0.7,
            "program": bad_program,
        }
        good_decision = {
            "assistant_message": "根据验证结果修订为逐次减速方案。",
            "action_kind": "rule_program",
            "confidence": 0.94,
            "program": valid_program(),
        }

        with patch(
            "cloud.app.agent_service.web_hardware_agent._post_chat_completion_message",
            side_effect=[
                tool_call("call_bad", "submit_hardware_decision", bad_decision),
                tool_call("call_good", "submit_hardware_decision", good_decision),
            ],
        ):
            result = decide_web_hardware_action(
                USER_TEXT,
                Settings(llm_provider="deepseek", deepseek_api_key="test"),
                conversation_history=[],
                device_context=device_context(),
            )

        self.assertEqual(
            ["submit_hardware_decision", "submit_hardware_decision"],
            result.tool_trace,
        )
        self.assertIn("修订", result.assistant_message)

    def test_tool_agent_allows_plain_language_after_information_tools(self) -> None:
        with patch(
            "cloud.app.agent_service.web_hardware_agent._post_chat_completion_message",
            side_effect=[
                tool_call("call_caps", "list_hardware_capabilities", {}),
                {"role": "assistant", "content": "当前支持 AHT20 温湿度观测与 SG90 舵机控制。"},
            ],
        ):
            result = decide_web_hardware_action(
                "当前支持哪些硬件？不要控制设备。",
                Settings(llm_provider="deepseek", deepseek_api_key="test"),
                conversation_history=[],
                device_context=device_context(),
            )

        self.assertEqual("none", result.action_kind)
        self.assertFalse(result.requires_confirmation)
        self.assertEqual(["list_hardware_capabilities"], result.tool_trace)

    def test_local_knowledge_tool_returns_aht20_sources(self) -> None:
        result = execute_web_hardware_tool(
            "search_project_knowledge",
            {"query": "AHT20 0x38", "limit": 3},
            user_text="",
            device_context=device_context(),
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["matches"])
        self.assertTrue(any("AHT20" in item["snippet"] or "aht20" in item["snippet"].lower() for item in result["matches"]))

    def test_public_source_reader_blocks_private_networks(self) -> None:
        result = execute_web_hardware_tool(
            "read_public_hardware_source",
            {"url": "https://127.0.0.1/internal"},
            user_text="",
            device_context=device_context(),
        )

        self.assertFalse(result["ok"])
        self.assertIn("blocked", result["error"])


if __name__ == "__main__":
    unittest.main()
