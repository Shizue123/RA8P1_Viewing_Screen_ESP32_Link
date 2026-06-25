from __future__ import annotations

import unittest

from fastapi import HTTPException

from cloud.app.api.routes import interpret_text
from cloud.app.models import InterpretRequest


class LanguageApiTest(unittest.TestCase):
    def test_interpret_endpoint_returns_intent(self) -> None:
        body = interpret_text(
            InterpretRequest(text="温度超过30度时让舵机转到180度并蜂鸣"),
            None,
            None,
        )

        self.assertTrue(body["ok"])
        self.assertEqual("threshold_control", body["intent"]["intent_type"])
        self.assertEqual(["AHT20", "SG90", "BUZZER"], body["intent"]["target_devices"])

    def test_interpret_endpoint_rejects_unsupported_text(self) -> None:
        with self.assertRaises(HTTPException) as context:
            interpret_text(InterpretRequest(text="让舵机转到90度"), None, None)

        self.assertEqual(422, context.exception.status_code)
        self.assertIn("temperature threshold", str(context.exception.detail))


if __name__ == "__main__":
    unittest.main()
