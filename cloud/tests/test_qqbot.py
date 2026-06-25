from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cloud.app.api.qqbot_routes import router
from cloud.app.api.web_routes import get_device_registry, get_orchestrator
from cloud.app.config import Settings, get_settings
from cloud.app.device_registry import DeviceRegistry
from cloud.app.device_state.store import device_state_store
from cloud.app.qqbot import QQBotMessageEvent, qqbot_build_validation_response
from cloud.app.qqbot_runtime import (
    _finalize_qqbot_response,
    _select_qqbot_device_id,
    generate_qqbot_reply,
)


def build_settings(directory: str, **overrides: object) -> Settings:
    base = Path(directory)
    values: dict[str, object] = {
        "auth_db_path": str(base / "auth.sqlite3"),
        "module_binding_db_path": str(base / "module_bindings.sqlite3"),
        "device_registry_db_path": str(base / "device_registry.sqlite3"),
        "automation_task_db_path": str(base / "automation_tasks.sqlite3"),
        "qqbot_enabled": True,
        "qqbot_app_id": "1904490384",
        "qqbot_app_secret": "qqbot-secret-for-tests",
    }
    values.update(overrides)
    return Settings(**values)


def sign_payload(bot_secret: str, timestamp: str, body: bytes) -> str:
    seed = bot_secret
    while len(seed.encode("utf-8")) < 32:
        seed = seed + seed
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = Ed25519PrivateKey.from_private_bytes(seed.encode("utf-8")[:32])
    return private_key.sign(timestamp.encode("utf-8") + body).hex()


class QQBotRouteTest(unittest.TestCase):
    def test_selects_freshest_online_registered_device(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = build_settings(directory, device_id="ra8p1_demo_001")
            registry = DeviceRegistry(settings)
            registry.ensure_default_device()
            real_device_id = "ra8p1_e1b82bb84da7"
            registry.touch_observed(real_device_id)
            device_state_store.update_from_mqtt(
                f"cloudbridge/{real_device_id}/status",
                {
                    "device_id": real_device_id,
                    "timestamp": int(time.time()),
                    "status": "online",
                },
            )

            selected = _select_qqbot_device_id(settings, registry)

        self.assertEqual(real_device_id, selected)

    def test_validation_response_uses_expected_signature_scheme(self) -> None:
        response = qqbot_build_validation_response(
            bot_secret="qqbot-secret-for-tests",
            plain_token="plain-token-123",
            event_ts="1725442341",
        )
        self.assertEqual("plain-token-123", response["plain_token"])
        self.assertEqual(128, len(response["signature"]))

    def test_finalize_preserves_mixed_multi_sensor_reply(self) -> None:
        settings = Settings(device_id="ra8p1_e1b82bb84da7")
        response = {
            "assistant_message": "当前温湿度有实时值，但光照暂时没有新的上报。",
            "hardware_control": {
                "action_kind": "observation_query",
                "result": {
                    "observations": {
                        "AHT20": {
                            "fresh": True,
                            "device_online": True,
                            "sample_online": True,
                        },
                        "BH1750": {
                            "fresh": False,
                            "device_online": True,
                            "sample_online": False,
                        },
                    }
                },
            },
        }

        reply = _finalize_qqbot_response("看看温湿度和光照", response, settings)

        self.assertEqual("当前温湿度有实时值，但光照暂时没有新的上报。", reply)

    def test_generate_reply_prefers_grounded_hermes_for_observation_chat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = build_settings(
                directory,
                device_id="ra8p1_e1b82bb84da7",
                qqbot_hardware_control_enabled=True,
            )
            registry = DeviceRegistry(settings)
            registry.ensure_default_device()
            event = QQBotMessageEvent(
                event_type="C2C_MESSAGE_CREATE",
                msg_id="msg-hermes-observation",
                text="看看现在温湿度和光照怎么样",
                conversation_key="qqbot:c2c:user-openid-1",
                user_openid="user-openid-1",
            )
            observation_response = {
                "assistant_message": "已读取传感器。",
                "hardware_control": {
                    "action_kind": "observation_query",
                    "result": {
                        "observations": {
                            "AHT20": {
                                "fresh": True,
                                "device_online": True,
                                "sample_online": True,
                            }
                        }
                    },
                },
            }
            grounded_response = {
                "assistant_message": "现在温度 27.1 C，湿度 54.1%，光照暂时没有新的上报。",
                "hardware_control": {
                    "action_kind": "none",
                },
            }

            with patch(
                "cloud.app.qqbot_runtime._try_llm_first_web_hardware_action",
                return_value=observation_response,
            ) as hardware_route:
                with patch(
                    "cloud.app.qqbot_runtime._try_qqbot_hermes_grounded_reply",
                    return_value=grounded_response,
                ) as grounded_route:
                    reply = generate_qqbot_reply(event, settings, object(), registry)

        self.assertEqual("现在温度 27.1 C，湿度 54.1%，光照暂时没有新的上报。", reply)
        hardware_route.assert_called_once()
        grounded_route.assert_called_once()

    def test_generate_reply_preserves_manual_action_execution_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = build_settings(
                directory,
                device_id="ra8p1_e1b82bb84da7",
                qqbot_hardware_control_enabled=True,
            )
            registry = DeviceRegistry(settings)
            registry.ensure_default_device()
            event = QQBotMessageEvent(
                event_type="C2C_MESSAGE_CREATE",
                msg_id="msg-hermes-action",
                text="把舵机转到90度",
                conversation_key="qqbot:c2c:user-openid-1",
                user_openid="user-openid-1",
            )
            manual_action_response = {
                "assistant_message": "已为你下发舵机动作。",
                "hardware_control": {
                    "action_kind": "manual_action",
                },
            }

            with patch(
                "cloud.app.qqbot_runtime._try_llm_first_web_hardware_action",
                return_value=manual_action_response,
            ) as hardware_route:
                with patch("cloud.app.qqbot_runtime._try_qqbot_hermes_grounded_reply") as grounded_route:
                    reply = generate_qqbot_reply(event, settings, object(), registry)

        self.assertEqual("已为你下发舵机动作。", reply)
        hardware_route.assert_called_once()
        grounded_route.assert_not_called()

    def test_callback_handles_validation_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = build_settings(directory)
            app = FastAPI()
            app.include_router(router)
            app.dependency_overrides[get_settings] = lambda: settings
            app.dependency_overrides[get_orchestrator] = lambda: object()
            app.dependency_overrides[get_device_registry] = lambda: object()
            client = TestClient(app)

            payload = {
                "op": 13,
                "d": {
                    "plain_token": "Arq0D5A61EgUu4OxUvOp",
                    "event_ts": "1725442341",
                },
            }
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            timestamp = "1725442341"
            signature = sign_payload(settings.qqbot_app_secret, timestamp, body)

            response = client.post(
                "/qqbot/callback",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature-Ed25519": signature,
                    "X-Signature-Timestamp": timestamp,
                    "X-Bot-Appid": settings.qqbot_app_id,
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            qqbot_build_validation_response(
                bot_secret=settings.qqbot_app_secret,
                plain_token="Arq0D5A61EgUu4OxUvOp",
                event_ts="1725442341",
            ),
            response.json(),
        )

    def test_callback_replies_to_c2c_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = build_settings(directory)
            app = FastAPI()
            app.include_router(router)
            app.dependency_overrides[get_settings] = lambda: settings
            app.dependency_overrides[get_orchestrator] = lambda: object()
            app.dependency_overrides[get_device_registry] = lambda: object()
            client = TestClient(app)

            payload = {
                "op": 0,
                "t": "C2C_MESSAGE_CREATE",
                "d": {
                    "id": "msg-001",
                    "content": "读取温湿度",
                    "author": {"user_openid": "user-openid-1"},
                    "timestamp": "2026-06-22T16:00:00+08:00",
                },
            }
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            timestamp = "1725442341"
            signature = sign_payload(settings.qqbot_app_secret, timestamp, body)

            with patch("cloud.app.api.qqbot_routes.generate_qqbot_reply", return_value="已收到你的请求") as generate:
                with patch("cloud.app.api.qqbot_routes.qqbot_send_text_reply", return_value={"id": "reply-1"}) as send:
                    response = client.post(
                        "/qqbot/callback",
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Signature-Ed25519": signature,
                            "X-Signature-Timestamp": timestamp,
                            "X-Bot-Appid": settings.qqbot_app_id,
                        },
                    )

        self.assertEqual(200, response.status_code)
        self.assertEqual({"op": 12}, response.json())
        generate.assert_called_once()
        send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
