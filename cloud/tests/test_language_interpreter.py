from __future__ import annotations

import unittest

from cloud.app.agent_service.language import interpret_text_to_intent
from cloud.app.template_compiler.compiler import compile_intent_to_lua


class LanguageInterpreterTest(unittest.TestCase):
    def test_interprets_chinese_temperature_servo_and_buzzer_command(self) -> None:
        parsed = interpret_text_to_intent("温度超过30度时让舵机转到180度并蜂鸣，每1秒检查一次")

        intent = parsed.intent

        self.assertEqual("threshold_control", intent.intent_type)
        self.assertEqual(">", intent.conditions.operator)
        self.assertEqual(30, intent.conditions.value)
        self.assertEqual(1000, intent.loop_interval_ms)
        self.assertEqual(["AHT20", "SG90", "BUZZER"], intent.target_devices)
        self.assertEqual("servo_set", intent.actions[0].method)
        self.assertEqual({"angle": 180}, intent.actions[0].params)
        self.assertEqual("buzzer", intent.actions[1].method)

    def test_interpreted_intent_compiles_to_lua(self) -> None:
        parsed = interpret_text_to_intent("temperature > 28 servo 90 degrees and buzzer 1500Hz 500ms")

        lua_code, validation = compile_intent_to_lua(parsed.intent)

        self.assertTrue(validation["ok"])
        self.assertIn("data.temp > 28", lua_code)
        self.assertIn("servo_set(90)", lua_code)
        self.assertIn("buzzer(1500, 500)", lua_code)

    def test_rejects_text_without_supported_threshold(self) -> None:
        with self.assertRaisesRegex(ValueError, "temperature threshold"):
            interpret_text_to_intent("让舵机转到90度")

    def test_interprets_screen_text_command(self) -> None:
        parsed = interpret_text_to_intent('请在屏幕显示"Hello from cloud"')

        intent = parsed.intent

        self.assertEqual("screen_text", intent.intent_type)
        self.assertEqual(["SCREEN"], intent.target_devices)
        self.assertEqual("screen_text", intent.actions[0].method)
        self.assertEqual({"text": "Hello from cloud"}, intent.actions[0].params)


if __name__ == "__main__":
    unittest.main()
