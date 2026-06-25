from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from cloud.app.agent_service.hermes_official import chat_with_hermes_gateway
from cloud.app.config import Settings


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(
            {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "服务器资料已找到。"}],
                    }
                ]
            },
            ensure_ascii=False,
        ).encode("utf-8")


class HermesGatewayTest(unittest.TestCase):
    def test_extracts_responses_api_text(self) -> None:
        settings = Settings(
            hermes_gateway_url="http://127.0.0.1:8642",
            hermes_gateway_api_key="internal-secret",
        )
        with patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            result = chat_with_hermes_gateway(
                "查找硬件资料",
                settings,
                conversation="ra8p1-web-user-1",
                context={"hardware_control_enabled": False},
            )
        self.assertEqual("服务器资料已找到。", result)
        request = urlopen.call_args.args[0]
        self.assertEqual("Bearer internal-secret", request.headers["Authorization"])
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual("ra8p1-web-user-1", body["conversation"])
        self.assertTrue(body["store"])


if __name__ == "__main__":
    unittest.main()
