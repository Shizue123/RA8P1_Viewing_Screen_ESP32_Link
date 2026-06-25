from __future__ import annotations

import json
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from cloud.app.agent_service.action_plan import interpret_text_to_rule_program
from cloud.app.agent_service.orchestrator import AgentOrchestrator
from cloud.app.agent_service.web_hardware_agent import (
    WebHardwareDecision,
    WebManualAction,
    WebObservationQuery,
    decide_web_hardware_action,
)
from cloud.app.auth import AuthStore, ChangePasswordRequest, CreateUserRequest, LoginRequest
from cloud.app.automation_tasks import close_automation_task_service
from cloud.app.api.web_routes import (
    ModuleBindingConfirmRequest,
    WebChatRequest,
    _build_observation_query_response,
    _device_web_time_alignment,
    _try_llm_first_web_hardware_action,
    _try_llm_first_web_readonly_action,
    _try_observation_query,
    _try_web_hardware_deploy,
    web_chat,
    web_confirm_module_binding,
    web_context,
    web_create_model_profile,
    web_model_config,
    web_update_model_config,
)
from cloud.app.config import Settings
from cloud.app.device_state.store import device_state_store
from cloud.app.device_registry import DeviceRegistry
from cloud.app.module_binding_store import ModuleBindingStore
from cloud.app.model_config import ModelProfileRequest, ModelSelectionRequest, effective_model_settings
from cloud.app.mqtt_service.client import MqttPublisher


def request_with_cookie(token: str, csrf_token: str = "") -> Request:
    headers = [(b"cookie", f"ra8p1_session={token}".encode("ascii"))]
    if csrf_token:
        headers.append((b"x-csrf-token", csrf_token.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": headers,
            "client": ("127.0.0.1", 1234),
        }
    )


def build_test_settings(directory: str, **overrides: object) -> Settings:
    base = Path(directory)
    values: dict[str, object] = {
        "auth_db_path": str(base / "auth.sqlite3"),
        "module_binding_db_path": str(base / "module_bindings.sqlite3"),
        "device_registry_db_path": str(base / "device_registry.sqlite3"),
        "automation_task_db_path": str(base / "automation_tasks.sqlite3"),
    }
    values.update(overrides)
    return Settings(**values)


class WebAuthTest(unittest.TestCase):
    def test_generic_chat_never_exposes_structured_model_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = build_test_settings(
                directory,
                llm_provider="hermes_official",
                mqtt_enabled=False,
            )
            with patch(
                "cloud.app.api.web_routes.decide_web_hardware_action",
                side_effect=ValueError("structured JSON failed; upstream HTTP 402"),
            ):
                response = _try_llm_first_web_hardware_action(
                    "你上报的路线在哪里，不会输入对话框吗",
                    settings,
                    AgentOrchestrator(settings, MqttPublisher(settings)),
                    conversation_history=[
                        {"role": "user", "content": "今天10点25汇报温湿度和光照"},
                        {"role": "assistant", "content": "已建立一次性汇报任务。"},
                        {"role": "user", "content": "你上报的路线在哪里，不会输入对话框吗"},
                    ],
                    automation_context={
                        "owner_channel": "web",
                        "owner_id": "1",
                        "conversation_id": "conversation-1",
                        "device_id": settings.device_id,
                        "control_enabled": True,
                    },
                )
            self.assertTrue(response["ok"])
            self.assertEqual("none", response["hardware_control"]["action_kind"])
            self.assertNotIn("402", response["assistant_message"])
            self.assertIn("同一对话框", response["assistant_message"])
            close_automation_task_service(settings)

    def test_web_time_alignment_compares_full_device_date_time(self) -> None:
        alignment = _device_web_time_alignment(
            {
                "last_telemetry": {
                    "payload": {
                        "clock": {
                            "local_iso": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(
                                timespec="seconds"
                            )
                        }
                    }
                }
            }
        )
        self.assertIsNotNone(alignment["device_time"])
        self.assertLessEqual(abs(float(alignment["skew_sec"])), 2.0)
        self.assertTrue(alignment["aligned"])

    def test_web_context_exposes_pending_module_confirmation_for_candidate_i2c_module(self) -> None:
        device_id = "web_auth_module_binding_candidate"
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/status",
            {
                "type": "status",
                "timestamp": 200,
                "payload": {
                    "ports": [
                        {
                            "port_id": "i2c.s1",
                            "physical_port": "I2C-1",
                            "channel": "Bus S1",
                            "type": "i2c",
                            "status": "online",
                            "activation": "channel_active",
                            "diag": "env_probe_candidate",
                            "last_sample_ms": 1234,
                            "module": {
                                "module_id": "env_probe",
                                "module_type": "unknown",
                                "module_class": "env.th",
                                "driver": "probe_only",
                                "model_state": "candidate",
                                "binding_source": "auto_detected",
                                "device_key": "i2c.s1:0x38:ENV",
                            },
                            "capabilities": [
                                {"id": "env.temperature", "unit": "C", "access": "read", "status": "online"},
                                {"id": "env.humidity", "unit": "%RH", "access": "read", "status": "online"},
                            ],
                        }
                    ]
                },
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = build_test_settings(directory, device_id=device_id)
            store = AuthStore(settings)
            store.register_first_admin("owner", "correct-horse-battery")
            _token, user = store.login("owner", "correct-horse-battery")
            registry = DeviceRegistry(settings)
            context = web_context(
                settings=settings,
                registry=registry,
                binding_store=ModuleBindingStore(settings),
                user=user,
            )

        endpoint = context["signal_topology"]["channels"][0]["hardware"][0]
        metadata = endpoint["metadata"]
        self.assertTrue(metadata["needs_user_confirmation"])
        self.assertEqual("温湿度模块", metadata["display_title"])
        self.assertIn("model.aht20", [item["id"] for item in metadata["binding_options"]])
        self.assertIn("model.sht30", [item["id"] for item in metadata["binding_options"]])

    def test_web_confirm_module_binding_persists_and_surfaces_user_choice(self) -> None:
        device_id = "web_auth_module_binding_confirmed"
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/status",
            {
                "type": "status",
                "timestamp": 240,
                "payload": {
                    "ports": [
                        {
                            "port_id": "i2c.s1",
                            "physical_port": "I2C-1",
                            "channel": "Bus S1",
                            "type": "i2c",
                            "status": "online",
                            "activation": "channel_active",
                            "diag": "env_probe_candidate",
                            "last_sample_ms": 1250,
                            "module": {
                                "module_id": "env_probe",
                                "module_type": "unknown",
                                "module_class": "env.th",
                                "driver": "probe_only",
                                "model_state": "candidate",
                                "binding_source": "auto_detected",
                                "device_key": "i2c.s1:0x44:ENV",
                            },
                            "capabilities": [
                                {"id": "env.temperature", "unit": "C", "access": "read", "status": "online"},
                                {"id": "env.humidity", "unit": "%RH", "access": "read", "status": "online"},
                            ],
                        }
                    ]
                },
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = build_test_settings(directory, device_id=device_id)
            store = AuthStore(settings)
            store.register_first_admin("owner", "correct-horse-battery")
            _token, user = store.login("owner", "correct-horse-battery")
            registry = DeviceRegistry(settings)
            binding_store = ModuleBindingStore(settings)

            response = web_confirm_module_binding(
                ModuleBindingConfirmRequest(
                    device_id=device_id,
                    port_id="i2c.s1",
                    binding_key="i2c.s1:0x44:ENV",
                    option_id="model.sht30",
                ),
                settings=settings,
                registry=registry,
                binding_store=binding_store,
                user=user,
            )
            context = web_context(
                settings=settings,
                registry=registry,
                binding_store=binding_store,
                user=user,
            )

        self.assertTrue(response["ok"])
        self.assertEqual("model.sht30", response["binding"]["option_id"])
        endpoint = context["signal_topology"]["channels"][0]["hardware"][0]
        metadata = endpoint["metadata"]
        self.assertEqual("温湿度模块", metadata["display_title"])
        self.assertEqual("SHT30", metadata["display_model"])
        self.assertEqual("model.sht30", metadata["user_binding"]["option_id"])
        self.assertEqual("model.sht30", context["diagnostics"]["module_bindings"][0]["option_id"])

    def test_bootstrap_login_csrf_and_chat_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = build_test_settings(directory, auth_cookie_name="ra8p1_session")
            store = AuthStore(settings)
            self.assertTrue(store.bootstrap_required())
            store.register_first_admin("owner", "correct-horse-battery",)
            self.assertFalse(store.bootstrap_required())

            token, user = store.login("owner", "correct-horse-battery")
            authenticated = store.authenticate(request_with_cookie(token))
            self.assertEqual("owner", authenticated.username)
            self.assertEqual("admin", authenticated.role)

            with self.assertRaises(HTTPException):
                store.authenticate(request_with_cookie(token), require_csrf=True)
            csrf_user = store.authenticate(
                request_with_cookie(token, user.csrf_token),
                require_csrf=True,
            )
            self.assertEqual(user.id, csrf_user.id)

            conversation = store.create_conversation(user.id)
            conversation_id = str(conversation["id"])
            store.append_chat_message(user.id, conversation_id, "user", "项目资料在哪里？")
            store.append_chat_message(user.id, conversation_id, "assistant", "资料在服务器工作区。")
            history = store.chat_history(user.id, conversation_id)
            self.assertEqual(["user", "assistant"], [item["role"] for item in history])
            conversations = store.list_conversations(user.id)
            self.assertEqual(1, len(conversations))
            self.assertEqual("项目资料在哪里？", conversations[0]["title"])

            second = store.create_conversation(user.id)
            self.assertEqual([], store.chat_history(user.id, str(second["id"])))
            self.assertEqual(2, len(store.list_conversations(user.id)))
            store.rename_conversation(user.id, str(second["id"]), "新的标题")
            store.set_conversation_pinned(user.id, str(second["id"]), True)
            self.assertEqual("新的标题", store.list_conversations(user.id)[0]["title"])
            self.assertTrue(store.list_conversations(user.id)[0]["is_pinned"])
            store.delete_conversation(user.id, conversation_id)
            self.assertEqual(1, len(store.list_conversations(user.id)))
            with self.assertRaises(HTTPException) as deleted:
                store.chat_history(user.id, conversation_id)
            self.assertEqual(404, deleted.exception.status_code)

    def test_login_locks_after_repeated_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AuthStore(build_test_settings(directory))
            store.register_first_admin("owner", "correct-horse-battery")
            for _ in range(5):
                with self.assertRaises(HTTPException):
                    store.login("owner", "wrong-password")
            with self.assertRaises(HTTPException) as locked:
                store.login("owner", "correct-horse-battery")
            self.assertEqual(423, locked.exception.status_code)

    def test_password_requests_accept_six_character_passwords(self) -> None:
        login = LoginRequest(username="owner", password="Ab!123")
        create = CreateUserRequest(username="member", password="Cd#456", role="member")
        change = ChangePasswordRequest(current_password="Ab!123", new_password="Cd#456")

        self.assertEqual("Ab!123", login.password)
        self.assertEqual("Cd#456", create.password)
        self.assertEqual("Cd#456", change.new_password)

        with self.assertRaises(ValidationError):
            LoginRequest(username="owner", password="12345")

    def test_admin_can_delete_member_but_not_self(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AuthStore(build_test_settings(directory))
            store.register_first_admin("owner", "Ab!123")
            member = store.create_user("member", "Cd#456", "member")
            _token, admin = store.login("owner", "Ab!123")

            deleted = store.delete_user(admin, int(member["id"]))

            self.assertEqual("member", deleted["username"])
            self.assertEqual(["owner"], [item["username"] for item in store.list_users()])
            with self.assertRaises(HTTPException) as self_delete:
                store.delete_user(admin, admin.id)
            self.assertEqual(400, self_delete.exception.status_code)

    def test_admin_web_chat_can_deploy_bounded_rule_program_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = build_test_settings(
                directory,
                log_db_path=":memory:",
                llm_provider="deepseek",
                deepseek_api_key="test-key",
                web_hardware_control_enabled=True,
                mqtt_enabled=False,
            )
            store = AuthStore(settings)
            store.register_first_admin("owner", "correct-horse-battery")
            _token, user = store.login("owner", "correct-horse-battery")
            conversation = store.create_conversation(user.id)
            parsed = interpret_text_to_rule_program("当温度达到30度时，舵机来回转动", Settings(llm_provider="template"))
            with patch(
                "cloud.app.api.web_routes.decide_web_hardware_action",
                return_value=WebHardwareDecision(
                    assistant_message="模型判断这是 30 度温度触发的 SG90 规则。",
                    action_kind="rule_program",
                    confidence=0.91,
                    reasoning_summary="explicit sensor condition plus servo action",
                    program=parsed.program,
                ),
            ):
                body = web_chat(
                    WebChatRequest(
                        text="当温度达到30度时，舵机来回转动",
                        conversation_id=str(conversation["id"]),
                    ),
                    settings,
                    store,
                    AgentOrchestrator(settings, MqttPublisher(settings)),
                    user,
                )
            close_automation_task_service(settings)

        self.assertTrue(body["ok"])
        self.assertEqual("rule_program", body["hardware_control"]["action_kind"])
        self.assertEqual("ra8p1_demo_001", body["hardware_control"]["device_id"])
        self.assertEqual(
            [30, 150, 90],
            [item["params"]["angle"] for item in body["hardware_control"]["program"]["actions"]],
        )
        self.assertIn("30", body["assistant_message"])

    def test_admin_web_chat_observation_query_reads_aht20_without_deploying(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = build_test_settings(
                directory,
                log_db_path=":memory:",
                llm_provider="deepseek",
                deepseek_api_key="test-key",
                web_hardware_control_enabled=True,
                mqtt_enabled=False,
            )
            store = AuthStore(settings)
            store.register_first_admin("owner", "correct-horse-battery")
            _token, user = store.login("owner", "correct-horse-battery")
            conversation = store.create_conversation(user.id)
            with patch(
                "cloud.app.api.web_routes.decide_web_hardware_action",
                return_value=WebHardwareDecision(
                    assistant_message="模型判断这是 AHT20 观测查询。",
                    action_kind="observation_query",
                    confidence=0.92,
                    reasoning_summary="read current temperature and humidity",
                    observation_query=WebObservationQuery(),
                ),
            ):
                body = web_chat(
                    WebChatRequest(
                        text="读取当前AHT20温湿度并回传",
                        conversation_id=str(conversation["id"]),
                    ),
                    settings,
                    store,
                    AgentOrchestrator(settings, MqttPublisher(settings)),
                    user,
                )

        self.assertTrue(body["ok"])
        self.assertEqual("observation_query", body["hardware_control"]["action_kind"])
        self.assertEqual("AHT20", body["hardware_control"]["query"]["device"])
        self.assertEqual({"sda": "P309", "scl": "P306"}, body["hardware_control"]["query"]["pins"])
        self.assertNotIn("program", body["hardware_control"])

    def test_admin_web_chat_observation_query_uses_latest_aht20_sample(self) -> None:
        now = int(time.time())
        device_id = "web_auth_latest_aht20_sample"
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/telemetry",
            {
                "type": "telemetry",
                "timestamp": now - 5,
                "payload": {"aht20": {"status": "online", "temp": 28.4, "humidity": 49.5, "crc_ok": True}},
            },
        )
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/status",
            {
                "type": "status",
                "timestamp": now,
                "payload": {"aht20": {"status": "online", "temp": 28.8, "humidity": 50.1, "crc_ok": True}},
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = build_test_settings(
                directory,
                log_db_path=":memory:",
                llm_provider="deepseek",
                deepseek_api_key="test-key",
                web_hardware_control_enabled=True,
                mqtt_enabled=False,
                device_id=device_id,
            )
            store = AuthStore(settings)
            store.register_first_admin("owner", "correct-horse-battery")
            _token, user = store.login("owner", "correct-horse-battery")
            conversation = store.create_conversation(user.id)
            with patch(
                "cloud.app.api.web_routes.decide_web_hardware_action",
                return_value=WebHardwareDecision(
                    assistant_message="模型判断这是 AHT20 观测查询。",
                    action_kind="observation_query",
                    confidence=0.92,
                    reasoning_summary="read current temperature and humidity",
                    observation_query=WebObservationQuery(),
                ),
            ):
                body = web_chat(
                    WebChatRequest(
                        text="告诉我现在硬件上检测到的温湿度",
                        conversation_id=str(conversation["id"]),
                    ),
                    settings,
                    store,
                    AgentOrchestrator(settings, MqttPublisher(settings)),
                    user,
                )

        result = body["hardware_control"]["result"]
        self.assertEqual(28.8, result["temperature"])
        self.assertEqual(50.1, result["humidity"])
        self.assertEqual("status", result["source"])
        self.assertEqual(float(now), result["timestamp"])
        self.assertNotIn("数据源", body["assistant_message"])
        self.assertNotIn("上报时间", body["assistant_message"])

    def test_light_observation_query_reads_latest_bh1750_sample(self) -> None:
        now = int(time.time())
        device_id = "web_auth_latest_bh1750_sample"
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/telemetry",
            {
                "type": "telemetry",
                "timestamp": now,
                "payload": {
                    "samples": [
                        {
                            "port_id": "i2c.s1",
                            "module_type": "BH1750",
                            "capability": "env.light.lux",
                            "value": 155.8,
                            "unit": "lux",
                            "ts_ms": 1000,
                        }
                    ]
                },
            },
        )
        settings = Settings(device_id=device_id)

        body = _build_observation_query_response(
            settings,
            query=WebObservationQuery(
                device="BH1750",
                capabilities=["env.light.lux"],
            ),
            source="test:bh1750",
            confidence=1.0,
        )

        self.assertEqual(155.8, body["hardware_control"]["result"]["light"])
        self.assertTrue(body["hardware_control"]["result"]["online"])
        self.assertIn("BH1750", body["assistant_message"])

    def test_observation_query_normalizes_multi_sensor_targets(self) -> None:
        query = WebObservationQuery(
            capabilities=["env.temperature", "env.humidity", "env.light.lux"],
        )

        self.assertEqual("AHT20", query.device)
        self.assertEqual(["AHT20", "BH1750"], query.devices)
        self.assertEqual(
            ["env.temperature", "env.humidity", "env.light.lux"],
            query.capabilities,
        )

    def test_observation_query_derives_bh1750_for_light_only_capability(self) -> None:
        query = WebObservationQuery(capabilities=["env.light.lux"])

        self.assertEqual("BH1750", query.device)
        self.assertEqual(["BH1750"], query.devices)

    def test_build_observation_query_response_combines_temperature_humidity_and_light(self) -> None:
        now = int(time.time())
        device_id = "web_auth_multi_sensor_observation"
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/status",
            {
                "type": "status",
                "timestamp": now,
                "payload": {
                    "aht20": {"status": "online", "temp": 27.1, "humidity": 54.1, "crc_ok": True},
                    "samples": [
                        {
                            "port_id": "i2c.s1",
                            "module_type": "BH1750",
                            "capability": "env.light.lux",
                            "value": 96.7,
                            "unit": "lux",
                            "ts_ms": now * 1000,
                        }
                    ],
                },
            },
        )
        settings = Settings(device_id=device_id)

        body = _build_observation_query_response(
            settings,
            query=WebObservationQuery(
                devices=["AHT20", "BH1750"],
                capabilities=["env.temperature", "env.humidity", "env.light.lux"],
            ),
            source="test:multi",
            confidence=1.0,
        )

        result = body["hardware_control"]["result"]
        self.assertEqual(["AHT20", "BH1750"], body["hardware_control"]["query"]["devices"])
        self.assertEqual(27.1, result["temperature"])
        self.assertEqual(54.1, result["humidity"])
        self.assertEqual(96.7, result["light"])
        self.assertIn("光照", body["assistant_message"])
        self.assertIn("温度", body["assistant_message"])

    def test_web_chat_multi_sensor_request_uses_synthesized_reply(self) -> None:
        now = int(time.time())
        device_id = "web_auth_multi_sensor_chat"
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/status",
            {
                "type": "status",
                "timestamp": now,
                "payload": {
                    "aht20": {"status": "online", "temp": 27.1, "humidity": 54.1, "crc_ok": True},
                    "samples": [
                        {
                            "port_id": "i2c.s1",
                            "module_type": "BH1750",
                            "capability": "env.light.lux",
                            "value": 96.7,
                            "unit": "lux",
                            "ts_ms": now * 1000,
                        }
                    ],
                },
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = build_test_settings(
                directory,
                log_db_path=":memory:",
                llm_provider="deepseek",
                deepseek_api_key="test-key",
                web_hardware_control_enabled=True,
                mqtt_enabled=False,
                device_id=device_id,
            )
            store = AuthStore(settings)
            store.register_first_admin("owner", "correct-horse-battery")
            _token, user = store.login("owner", "correct-horse-battery")
            conversation = store.create_conversation(user.id)
            with patch(
                "cloud.app.api.web_routes.decide_web_hardware_action",
                return_value=WebHardwareDecision(
                    assistant_message="我来同时读取温湿度和光照。",
                    action_kind="observation_query",
                    confidence=0.95,
                    reasoning_summary="read the full environment snapshot",
                    observation_query=WebObservationQuery(
                        devices=["AHT20", "BH1750"],
                        capabilities=["env.temperature", "env.humidity", "env.light.lux"],
                    ),
                ),
            ):
                with patch(
                    "cloud.app.api.web_routes.synthesize_observation_reply",
                    return_value="当前环境温度 27.1 C，湿度 54.1%，光照 96.7 lux。",
                ):
                    body = web_chat(
                        WebChatRequest(
                            text="看看温湿度和光照的情况",
                            conversation_id=str(conversation["id"]),
                        ),
                        settings,
                        store,
                        AgentOrchestrator(settings, MqttPublisher(settings)),
                        user,
                        DeviceRegistry(settings),
                        ModuleBindingStore(settings),
                    )

        self.assertTrue(body["ok"])
        self.assertEqual("当前环境温度 27.1 C，湿度 54.1%，光照 96.7 lux。", body["assistant_message"])
        self.assertEqual(96.7, body["hardware_control"]["result"]["light"])
        self.assertEqual(27.1, body["hardware_control"]["result"]["temperature"])

    def test_try_observation_query_detects_combined_temp_humidity_and_light(self) -> None:
        now = int(time.time())
        device_id = "web_auth_local_combined_observation"
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/status",
            {
                "type": "status",
                "timestamp": now,
                "payload": {
                    "aht20": {"status": "online", "temp": 26.8, "humidity": 53.0, "crc_ok": True},
                    "samples": [
                        {
                            "port_id": "i2c.s1",
                            "module_type": "BH1750",
                            "capability": "env.light.lux",
                            "value": 88.5,
                            "unit": "lux",
                            "ts_ms": now * 1000,
                        }
                    ],
                },
            },
        )
        settings = Settings(device_id=device_id)

        body = _try_observation_query("看看温湿度和光照的情况", settings)

        self.assertIsNotNone(body)
        assert body is not None
        self.assertEqual(["AHT20", "BH1750"], body["hardware_control"]["query"]["devices"])
        self.assertEqual(88.5, body["hardware_control"]["result"]["light"])
        self.assertEqual(26.8, body["hardware_control"]["result"]["temperature"])

    def test_readonly_llm_failure_falls_back_to_local_observation(self) -> None:
        now = int(time.time())
        device_id = "web_auth_readonly_llm_fallback"
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/status",
            {
                "type": "status",
                "timestamp": now,
                "payload": {
                    "aht20": {"status": "online", "temp": 26.6, "humidity": 52.7, "crc_ok": True},
                    "samples": [
                        {
                            "port_id": "i2c.s1",
                            "module_type": "BH1750",
                            "capability": "env.light.lux",
                            "value": 84.2,
                            "unit": "lux",
                            "ts_ms": now * 1000,
                        }
                    ],
                },
            },
        )
        settings = Settings(
            device_id=device_id,
            llm_provider="hermes_official",
            deepseek_api_key="deepseek-key",
        )

        with patch(
            "cloud.app.api.web_routes.run_hermes_gateway_prompt",
            side_effect=ValueError("Hermes gateway unavailable"),
        ):
            body = _try_llm_first_web_readonly_action(
                "看看温湿度和光照的情况",
                settings,
                conversation_history=[],
            )

        self.assertTrue(body["ok"])
        self.assertFalse(body["hardware_control"]["enabled"])
        self.assertTrue(body["hardware_control"]["read_only"])
        self.assertEqual(["AHT20", "BH1750"], body["hardware_control"]["query"]["devices"])
        self.assertEqual(84.2, body["hardware_control"]["result"]["light"])
        self.assertIn("local_observation_fallback", body["hardware_control"]["tool_trace"])

    def test_readonly_followup_now_reuses_previous_observation_request(self) -> None:
        now = int(time.time())
        device_id = "web_auth_readonly_followup_fallback"
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/status",
            {
                "type": "status",
                "timestamp": now,
                "payload": {
                    "aht20": {"status": "online", "temp": 26.0, "humidity": 51.2, "crc_ok": True},
                    "samples": [
                        {
                            "port_id": "i2c.s1",
                            "module_type": "BH1750",
                            "capability": "env.light.lux",
                            "value": 78.6,
                            "unit": "lux",
                            "ts_ms": now * 1000,
                        }
                    ],
                },
            },
        )
        settings = Settings(
            device_id=device_id,
            llm_provider="hermes_official",
            deepseek_api_key="deepseek-key",
        )

        with patch(
            "cloud.app.api.web_routes.run_hermes_gateway_prompt",
            side_effect=ValueError("Hermes gateway unavailable"),
        ):
            body = _try_llm_first_web_readonly_action(
                "现在呢",
                settings,
                conversation_history=[
                    {"role": "user", "content": "看看温湿度和光照的情况"},
                    {"role": "assistant", "content": "上一轮答复"},
                    {"role": "user", "content": "现在呢"},
                ],
            )

        self.assertEqual(["AHT20", "BH1750"], body["hardware_control"]["query"]["devices"])
        self.assertEqual(78.6, body["hardware_control"]["result"]["light"])
        self.assertEqual(26.0, body["hardware_control"]["result"]["temperature"])

    def test_hermes_readonly_uses_grounded_uploaded_data_answer(self) -> None:
        now = int(time.time())
        device_id = "web_auth_hermes_grounded_readonly"
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/status",
            {
                "type": "status",
                "timestamp": now,
                "payload": {
                    "aht20": {"status": "online", "temp": 26.2, "humidity": 51.8, "crc_ok": True},
                    "samples": [
                        {
                            "port_id": "i2c.s1",
                            "module_type": "BH1750",
                            "capability": "env.light.lux",
                            "value": 80.4,
                            "unit": "lux",
                            "ts_ms": now * 1000,
                        }
                    ],
                },
            },
        )
        settings = Settings(
            device_id=device_id,
            llm_provider="hermes_official",
            deepseek_api_key="deepseek-key",
            hermes_gateway_url="http://127.0.0.1:8642",
            api_server_key="gateway-key",
        )

        with patch(
            "cloud.app.api.web_routes.run_hermes_gateway_prompt",
            return_value="当前温度 26.2°C，湿度 51.8%，光照 80.4 lux。",
        ):
            body = _try_llm_first_web_readonly_action(
                "看看温湿度和光照的情况",
                settings,
                conversation_history=[],
            )

        self.assertTrue(body["ok"])
        self.assertEqual("hermes_grounded_uploaded_data", body["source"])
        self.assertEqual("none", body["hardware_control"]["action_kind"])
        self.assertIn("80.4 lux", body["assistant_message"])

    def test_hermes_readonly_provider_error_text_falls_back_to_local_observation(self) -> None:
        now = int(time.time())
        device_id = "web_auth_hermes_402_fallback"
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/status",
            {
                "type": "status",
                "timestamp": now,
                "payload": {
                    "aht20": {"status": "online", "temp": 26.1, "humidity": 51.6, "crc_ok": True},
                    "samples": [
                        {
                            "port_id": "i2c.s1",
                            "module_type": "BH1750",
                            "capability": "env.light.lux",
                            "value": 79.8,
                            "unit": "lux",
                            "ts_ms": now * 1000,
                        }
                    ],
                },
            },
        )
        settings = Settings(
            device_id=device_id,
            llm_provider="hermes_official",
            deepseek_api_key="deepseek-key",
            hermes_gateway_url="http://127.0.0.1:8642",
            api_server_key="gateway-key",
        )

        with patch(
            "cloud.app.api.web_routes.run_hermes_gateway_prompt",
            return_value="Error code: 402 - {'error': {'message': 'Insufficient Balance'}}",
        ):
            body = _try_llm_first_web_readonly_action(
                "看看温湿度和光照的情况",
                settings,
                conversation_history=[],
            )

        self.assertEqual(["AHT20", "BH1750"], body["hardware_control"]["query"]["devices"])
        self.assertEqual(79.8, body["hardware_control"]["result"]["light"])
        self.assertIn("local_observation_fallback", body["hardware_control"]["tool_trace"])

    def test_hermes_readonly_sanitizes_historical_numbers_when_no_uploaded_data(self) -> None:
        device_id = "web_auth_hermes_sanitize_offline"
        settings = Settings(
            device_id=device_id,
            llm_provider="hermes_official",
            deepseek_api_key="deepseek-key",
            hermes_gateway_url="http://127.0.0.1:8642",
            api_server_key="gateway-key",
        )

        with patch(
            "cloud.app.api.web_routes.run_hermes_gateway_prompt",
            return_value=(
                "设备还是离线状态。上次有数据的时候温度 27°C、湿度 54.1%、光照 90.8 lux，"
                "但现在获取不了新数据。"
            ),
        ):
            body = _try_llm_first_web_readonly_action(
                "现在呢",
                settings,
                conversation_history=[
                    {"role": "user", "content": "看看温湿度和光照的情况"},
                    {"role": "assistant", "content": "上一轮答复"},
                    {"role": "user", "content": "现在呢"},
                ],
                conversation_key="sanitize-offline",
            )

        self.assertEqual("hermes_grounded_uploaded_data", body["source"])
        self.assertNotIn("90.8", body["assistant_message"])
        self.assertIn("没有收到这台设备的实时上报", body["assistant_message"])

    def test_hermes_agent_selects_bh1750_observation(self) -> None:
        settings = Settings(
            llm_provider="hermes_official",
            deepseek_api_key="deepseek-key",
            hermes_gateway_url="http://127.0.0.1:8642",
            api_server_key="gateway-key",
        )
        hermes_decision = """
        {
          "assistant_message": "我来读取当前光照。",
          "action_kind": "observation_query",
          "confidence": 0.98,
          "requires_confirmation": false,
          "reasoning_summary": "用户请求读取 BH1750 光照",
          "observation_query": {
            "device": "BH1750",
            "channel": "i2c.s1",
            "capabilities": ["env.light.lux"]
          }
        }
        """
        with patch(
            "cloud.app.agent_service.web_hardware_agent.run_hermes_gateway_prompt",
            return_value=hermes_decision,
        ) as gateway:
            decision = decide_web_hardware_action(
                "读取光照",
                settings,
                conversation_history=[],
                device_context={
                    "device_id": "ra8p1_live",
                    "latest_device_state": {"_device_online": True, "last_seen": int(time.time())},
                },
            )

        gateway.assert_called_once()
        self.assertEqual("observation_query", decision.action_kind)
        self.assertEqual("BH1750", decision.observation_query.device)
        self.assertIn("hermes_gateway", decision.tool_trace)

    def test_hermes_invalid_structured_output_falls_back_to_deepseek(self) -> None:
        settings = Settings(
            llm_provider="hermes_official",
            deepseek_api_key="deepseek-key",
            deepseek_model="deepseek-v4-pro",
            hermes_gateway_url="http://127.0.0.1:8642",
            api_server_key="gateway-key",
        )
        deepseek_message = {
            "content": "",
            "tool_calls": [
                {
                    "id": "call-submit",
                    "type": "function",
                    "function": {
                        "name": "submit_hardware_decision",
                        "arguments": json.dumps(
                            {
                                "assistant_message": "我来读取当前温湿度和光照。",
                                "action_kind": "observation_query",
                                "confidence": 0.96,
                                "requires_confirmation": False,
                                "reasoning_summary": "fallback structured decision",
                                "observation_query": {
                                    "devices": ["AHT20", "BH1750"],
                                    "channel": "i2c.s1",
                                    "capabilities": [
                                        "env.temperature",
                                        "env.humidity",
                                        "env.light.lux",
                                    ],
                                },
                            },
                            ensure_ascii=False,
                        ),
                    },
                }
            ],
        }

        with patch(
            "cloud.app.agent_service.web_hardware_agent.run_hermes_gateway_prompt",
            return_value="{'assistant_message': 'bad json', 'action_kind': 'observation_query'}",
        ):
            with patch(
                "cloud.app.agent_service.web_hardware_agent._post_chat_completion_message",
                return_value=deepseek_message,
            ):
                decision = decide_web_hardware_action(
                    "看看温湿度和光照的情况",
                    settings,
                    conversation_history=[],
                    device_context={
                        "device_id": "ra8p1_live",
                        "latest_device_state": {"_device_online": True, "last_seen": int(time.time())},
                    },
                )

        self.assertEqual("observation_query", decision.action_kind)
        self.assertEqual(["AHT20", "BH1750"], decision.observation_query.devices)
        self.assertIn("deepseek_direct_fallback", decision.tool_trace)
        self.assertIn("Hermes fallback to DeepSeek Direct", decision.reasoning_summary)

    def test_unavailable_hermes_runtime_is_not_switchable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = build_test_settings(
                directory,
                log_db_path=":memory:",
                llm_provider="hermes_official",
                hermes_official_enabled=False,
            )
            store = AuthStore(settings)
            store.register_first_admin("owner", "correct-horse-battery")
            _token, user = store.login("owner", "correct-horse-battery")
            runtime_path = Path(directory) / "model_config.json"

            with patch("cloud.app.model_config.RUNTIME_MODEL_CONFIG_PATH", runtime_path):
                config = web_model_config(settings, user)["model_config"]
                hermes = next(
                    item for item in config["configured"] if item["provider"] == "hermes_official"
                )
                with self.assertRaises(HTTPException) as unavailable:
                    web_update_model_config(
                        ModelSelectionRequest(
                            provider="hermes_official",
                            model=settings.hermes_official_model,
                        ),
                        settings,
                        user,
                    )

        self.assertFalse(hermes["ready"])
        self.assertEqual(422, unavailable.exception.status_code)

    def test_web_chat_uses_readonly_llm_agent_for_deepseek_observation_when_control_disabled(self) -> None:
        now = int(time.time())
        device_id = "web_auth_readonly_observation"
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/status",
            {
                "type": "status",
                "timestamp": now,
                "payload": {"aht20": {"status": "online", "temp": 29.1, "humidity": 51.5, "crc_ok": True}},
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            settings = build_test_settings(
                directory,
                log_db_path=":memory:",
                llm_provider="deepseek",
                deepseek_api_key="test-key",
                mqtt_enabled=False,
                device_id=device_id,
            )
            store = AuthStore(settings)
            store.register_first_admin("owner", "correct-horse-battery")
            _token, user = store.login("owner", "correct-horse-battery")
            conversation = store.create_conversation(user.id)
            with patch(
                "cloud.app.api.web_routes.decide_web_hardware_action",
                return_value=WebHardwareDecision(
                    assistant_message="我来读取当前温湿度。",
                    action_kind="observation_query",
                    confidence=0.93,
                    reasoning_summary="read-only live observation",
                    observation_query=WebObservationQuery(),
                    tool_trace=["read_live_signal_topology"],
                ),
            ):
                body = web_chat(
                    WebChatRequest(
                        text="你能读取得到开发板上的数据吗",
                        conversation_id=str(conversation["id"]),
                    ),
                    settings,
                    store,
                    AgentOrchestrator(settings, MqttPublisher(settings)),
                    user,
                    DeviceRegistry(settings),
                    ModuleBindingStore(settings),
                )

        self.assertTrue(body["ok"])
        self.assertEqual("observation_query", body["hardware_control"]["action_kind"])
        self.assertFalse(body["hardware_control"]["enabled"])
        self.assertTrue(body["hardware_control"]["read_only"])
        self.assertEqual(29.1, body["hardware_control"]["result"]["temperature"])
        self.assertEqual(51.5, body["hardware_control"]["result"]["humidity"])

    def test_web_chat_blocks_deepseek_control_actions_when_control_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = build_test_settings(
                directory,
                log_db_path=":memory:",
                llm_provider="deepseek",
                deepseek_api_key="test-key",
                mqtt_enabled=False,
            )
            store = AuthStore(settings)
            store.register_first_admin("owner", "correct-horse-battery")
            _token, user = store.login("owner", "correct-horse-battery")
            conversation = store.create_conversation(user.id)
            with patch(
                "cloud.app.api.web_routes.decide_web_hardware_action",
                return_value=WebHardwareDecision(
                    assistant_message="我建议让 SG90 来回摆动。",
                    action_kind="manual_action",
                    confidence=0.89,
                    reasoning_summary="requested servo action",
                    manual_action=WebManualAction(angle=60, times=2, duration_ms=300),
                ),
            ):
                body = web_chat(
                    WebChatRequest(
                        text="让舵机摆动两次",
                        conversation_id=str(conversation["id"]),
                    ),
                    settings,
                    store,
                    AgentOrchestrator(settings, MqttPublisher(settings)),
                    user,
                    DeviceRegistry(settings),
                    ModuleBindingStore(settings),
                )

        self.assertTrue(body["ok"])
        self.assertEqual("disabled", body["hardware_control"]["action_kind"])
        self.assertEqual("manual_action", body["hardware_control"]["requested_action_kind"])
        self.assertFalse(body["hardware_control"]["enabled"])
        self.assertIn("未启用硬件执行", body["assistant_message"])

    def test_admin_web_chat_can_deploy_manual_servo_action_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = build_test_settings(
                directory,
                log_db_path=":memory:",
                llm_provider="deepseek",
                deepseek_api_key="test-key",
                web_hardware_control_enabled=True,
                mqtt_enabled=False,
            )
            store = AuthStore(settings)
            store.register_first_admin("owner", "correct-horse-battery")
            _token, user = store.login("owner", "correct-horse-battery")
            conversation = store.create_conversation(user.id)
            with patch(
                "cloud.app.api.web_routes.decide_web_hardware_action",
                return_value=WebHardwareDecision(
                    assistant_message="模型判断这是独立 SG90 手动动作。",
                    action_kind="manual_action",
                    confidence=0.94,
                    reasoning_summary="explicit servo sweep request",
                    manual_action=WebManualAction(angle=60, times=3, duration_ms=350),
                ),
            ):
                body = web_chat(
                    WebChatRequest(
                        text="舵机来回转动60度，3次",
                        conversation_id=str(conversation["id"]),
                    ),
                    settings,
                    store,
                    AgentOrchestrator(settings, MqttPublisher(settings)),
                    user,
                )
            close_automation_task_service(settings)

        self.assertTrue(body["ok"])
        self.assertEqual("manual_action", body["hardware_control"]["action_kind"])
        manual_action = body["hardware_control"]["manual_action"]
        self.assertEqual("manual_action.v1", manual_action["version"])
        self.assertEqual("SG90", manual_action["target"]["device"])
        self.assertEqual("P105", manual_action["target"]["pin"])
        self.assertEqual([30, 150, 30, 150, 30, 150], [item["params"]["angle"] for item in manual_action["actions"]])
        self.assertEqual("planned", body["hardware_control"]["delivery_stage"])

    def test_admin_can_switch_runtime_model_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_path = Path(directory) / "model_config.json"
            settings = build_test_settings(
                directory,
                log_db_path=":memory:",
                llm_provider="hermes_official",
                hermes_official_model="deepseek-v4-pro",
                deepseek_model="deepseek-v4-pro",
                deepseek_api_key="test-key",
            )
            store = AuthStore(settings)
            store.register_first_admin("owner", "correct-horse-battery")
            _token, user = store.login("owner", "correct-horse-battery")

            with patch("cloud.app.model_config.RUNTIME_MODEL_CONFIG_PATH", runtime_path):
                before = web_model_config(settings, user)["model_config"]
                self.assertEqual("hermes_official", before["active"]["provider"])
                updated = web_update_model_config(
                    ModelSelectionRequest(provider="deepseek", model="deepseek-v4-pro"),
                    settings,
                    user,
                )["model_config"]
                effective = effective_model_settings(settings)

        self.assertEqual("deepseek", updated["active"]["provider"])
        self.assertEqual("deepseek", effective.llm_provider)
        self.assertEqual("deepseek-v4-pro", effective.deepseek_model)

    def test_admin_can_add_and_use_custom_openai_compatible_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_path = Path(directory) / "model_config.json"
            profiles_path = Path(directory) / "model_profiles.json"
            settings = build_test_settings(
                directory,
                log_db_path=":memory:",
                llm_provider="hermes_official",
                hermes_official_model="deepseek-v4-pro",
                deepseek_api_key="builtin-key",
            )
            store = AuthStore(settings)
            store.register_first_admin("owner", "correct-horse-battery")
            _token, user = store.login("owner", "correct-horse-battery")

            with (
                patch("cloud.app.model_config.RUNTIME_MODEL_CONFIG_PATH", runtime_path),
                patch("cloud.app.model_config.CUSTOM_MODEL_PROFILES_PATH", profiles_path),
            ):
                created = web_create_model_profile(
                    ModelProfileRequest(
                        label="千问 DashScope",
                        provider="qwen",
                        model="qwen-plus",
                        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                        api_key="qwen-secret-key",
                    ),
                    settings,
                    user,
                )["model_config"]
                self.assertTrue(any(item["provider"] == "qwen" for item in created["configured"]))
                updated = web_update_model_config(
                    ModelSelectionRequest(provider="qwen", model="qwen-plus"),
                    settings,
                    user,
                )["model_config"]
                effective = effective_model_settings(settings)

        self.assertEqual("qwen", updated["active"]["provider"])
        self.assertEqual("deepseek", effective.llm_provider)
        self.assertEqual("qwen-plus", effective.deepseek_model)
        self.assertEqual("https://dashscope.aliyuncs.com/compatible-mode/v1", effective.deepseek_base_url)
        self.assertEqual("qwen-secret-key", effective.deepseek_api_key)

    def test_web_chat_short_followup_uses_llm_decision_without_deploying(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = build_test_settings(
                directory,
                log_db_path=":memory:",
                llm_provider="deepseek",
                deepseek_api_key="test-key",
                web_hardware_control_enabled=True,
                mqtt_enabled=False,
            )
            store = AuthStore(settings)
            store.register_first_admin("owner", "correct-horse-battery")
            _token, user = store.login("owner", "correct-horse-battery")
            conversation = store.create_conversation(user.id)
            store.append_chat_message(user.id, str(conversation["id"]), "user", "告诉我当前温湿度")
            store.append_chat_message(user.id, str(conversation["id"]), "assistant", "温度 28.4 C，湿度 49.5%。")
            with patch(
                "cloud.app.api.web_routes.decide_web_hardware_action",
                return_value=WebHardwareDecision(
                    assistant_message="现在没有新的执行命令；如果要刷新温湿度，我可以只读取 AHT20。",
                    action_kind="none",
                    confidence=0.88,
                    reasoning_summary="short contextual follow-up is not an actuator command",
                ),
            ) as decision_call:
                body = web_chat(
                    WebChatRequest(text="现在呢", conversation_id=str(conversation["id"])),
                    settings,
                    store,
                    AgentOrchestrator(settings, MqttPublisher(settings)),
                    user,
                )

        self.assertEqual("none", body["hardware_control"]["action_kind"])
        self.assertIn("没有新的执行命令", body["assistant_message"])
        history = decision_call.call_args.kwargs["conversation_history"]
        self.assertTrue(any(item["content"] == "告诉我当前温湿度" for item in history))

    def test_short_context_followup_does_not_deploy_rule_program(self) -> None:
        settings = Settings(
            log_db_path=":memory:",
            web_hardware_control_enabled=True,
            mqtt_enabled=False,
        )
        result = _try_web_hardware_deploy(
            "现在呢",
            settings,
            AgentOrchestrator(settings, MqttPublisher(settings)),
        )

        self.assertIsNone(result)

if __name__ == "__main__":
    unittest.main()
