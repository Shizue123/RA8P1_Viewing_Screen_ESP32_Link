from __future__ import annotations

import unittest

from cloud.app.models import Intent
from cloud.app.template_compiler.compiler import build_deploy_payload, compile_intent_to_lua


class TemplateCompilerTest(unittest.TestCase):
    def test_threshold_control_compiles_to_whitelisted_lua(self) -> None:
        intent = Intent.model_validate(
            {
                "intent_type": "threshold_control",
                "target_devices": ["AHT20", "SG90", "BUZZER"],
                "conditions": {"sensor": "AHT20.temp", "operator": ">", "value": 30},
                "actions": [
                    {"device": "SG90", "method": "servo_set", "params": {"angle": 180}},
                    {"device": "BUZZER", "method": "buzzer", "params": {"freq": 2000, "ms": 300}},
                ],
                "loop_interval_ms": 1000,
            }
        )

        lua_code, validation = compile_intent_to_lua(intent)
        payload = build_deploy_payload(intent, lua_code, need_confirm=True)

        self.assertTrue(validation["ok"])
        self.assertIn("aht20_read()", lua_code)
        self.assertIn("servo_set(180)", lua_code)
        self.assertTrue(payload.checksum.startswith("sha256:"))

    def test_rejects_out_of_range_servo_angle(self) -> None:
        intent = Intent.model_validate(
            {
                "intent_type": "threshold_control",
                "conditions": {"sensor": "AHT20.temp", "operator": ">", "value": 30},
                "actions": [{"device": "SG90", "method": "servo_set", "params": {"angle": 181}}],
            }
        )

        with self.assertRaisesRegex(ValueError, "servo_set angle"):
            compile_intent_to_lua(intent)

    def test_screen_text_compiles_to_whitelisted_lua(self) -> None:
        intent = Intent.model_validate(
            {
                "intent_type": "screen_text",
                "target_devices": ["SCREEN"],
                "actions": [{"device": "SCREEN", "method": "screen_text", "params": {"text": "Hello from cloud"}}],
            }
        )

        lua_code, validation = compile_intent_to_lua(intent)
        payload = build_deploy_payload(intent, lua_code, need_confirm=True)

        self.assertTrue(validation["ok"])
        self.assertEqual('screen_text("Hello from cloud")', lua_code)
        self.assertEqual("screen_text", payload.intent_type)


if __name__ == "__main__":
    unittest.main()
