from __future__ import annotations

import unittest
from unittest.mock import patch

from cloud.app.agent_service.language import interpret_text_to_intent
from cloud.app.config import Settings


class DeepSeekIntentTest(unittest.TestCase):
    def test_deepseek_provider_uses_fastpath_for_supported_grammar(self) -> None:
        content = (
            '{"intent_type":"threshold_control","target_devices":["AHT20","SG90"],'
            '"conditions":{"sensor":"AHT20.temp","operator":">","value":31},'
            '"actions":[{"device":"SG90","method":"servo_set","params":{"angle":90}}],'
            '"loop_interval_ms":1000}'
        )

        with patch("cloud.app.agent_service.deepseek._post_chat_completion", return_value=content) as post_chat:
            parsed = interpret_text_to_intent(
                "温度超过31度时舵机转到90度",
                Settings(llm_provider="deepseek", deepseek_api_key="test", deepseek_model="deepseek-v4-pro"),
            )

        post_chat.assert_not_called()
        self.assertEqual("rule_based_v1+gbrain+fastpath", parsed.source)
        self.assertEqual(31, parsed.intent.conditions.value)
        self.assertEqual({"angle": 90}, parsed.intent.actions[0].params)

    def test_deepseek_provider_validates_model_intent_when_fastpath_does_not_match(self) -> None:
        content = (
            '{"intent_type":"threshold_control","target_devices":["AHT20","SG90"],'
            '"conditions":{"sensor":"AHT20.temp","operator":">","value":31},'
            '"actions":[{"device":"SG90","method":"servo_set","params":{"angle":90}}],'
            '"loop_interval_ms":1000}'
        )

        with patch("cloud.app.agent_service.deepseek._post_chat_completion", return_value=content) as post_chat:
            parsed = interpret_text_to_intent(
                "请生成一个硬件规则方案，返回标准 intent JSON。",
                Settings(llm_provider="deepseek", deepseek_api_key="test", deepseek_model="deepseek-v4-pro"),
            )

        post_chat.assert_called_once()
        self.assertEqual("deepseek:deepseek-v4-pro+gbrain", parsed.source)
        self.assertEqual(31, parsed.intent.conditions.value)
        self.assertEqual({"angle": 90}, parsed.intent.actions[0].params)

    def test_deepseek_provider_reports_clear_dev_error_when_call_fails_after_fastpath_miss(self) -> None:
        with patch("cloud.app.agent_service.deepseek._post_chat_completion", side_effect=ValueError("network")):
            with self.assertRaisesRegex(ValueError, "DeepSeek fallback reason: network"):
                interpret_text_to_intent(
                    "请生成一个硬件规则方案，返回标准 intent JSON。",
                    Settings(app_env="dev", llm_provider="deepseek", deepseek_api_key="test"),
                )


if __name__ == "__main__":
    unittest.main()
