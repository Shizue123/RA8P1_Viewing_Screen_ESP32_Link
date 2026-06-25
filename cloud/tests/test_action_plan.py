from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from cloud.app.agent_service.action_plan import interpret_text_to_rule_program
from cloud.app.agent_service.hermes_official import HermesOfficialChatResult, chat_with_hermes_official
from cloud.app.agent_service.orchestrator import AgentOrchestrator
from cloud.app.api.routes import (
    _device_diagnostics,
    _build_web_deploy_view,
    hermes_chat,
    interpret_and_deploy,
    interpret_program,
    interpret_program_and_deploy,
)
from cloud.app.config import Settings
from cloud.app.device_state.store import device_state_store
from cloud.app.hardware_catalog import catalog_status
from cloud.app.models import (
    HermesChatRequest,
    InterpretDeployRequest,
    ProgramInterpretDeployRequest,
    ProgramInterpretRequest,
    RuleProgram,
    RuleProgramAction,
    RuleProgramTrigger,
)
from cloud.app.mqtt_service.client import MqttPublisher


class ActionPlanTest(unittest.TestCase):
    def test_device_diagnostics_highlights_no_ack_on_bus_s1(self) -> None:
        diagnostics = _device_diagnostics(
            {
                "last_status": {
                    "payload": {
                        "uart": "online",
                        "script_state": "ACKED",
                        "i2c": {
                            "bus": "s1",
                            "diag": "ok",
                            "count": 0,
                            "devices": [],
                        },
                        "aht20": {"status": "offline", "crc_ok": False, "diag": "write addr nack"},
                        "hardware_list": [{"address": "0x38", "type": "AHT20", "status": "offline", "bus": "s1"}],
                    }
                }
            }
        )

        self.assertEqual("no_device_ack", diagnostics["i2c"]["interpretation"])
        self.assertEqual(
            "Check AHT20 SCL -> P306 and SDA -> P309 on Bus S1.",
            diagnostics["i2c"]["next_checks"][1],
        )
        self.assertIn("no device ACKed", diagnostics["blocking_conditions"][0]["detail"])
        self.assertEqual("platform.hardware_registry.v1", diagnostics["hardware_registry"]["schema"])
        self.assertIn("env.temperature", [item["id"] for item in diagnostics["platform_capabilities"]])

    def test_device_diagnostics_prefers_standard_ports_registry_when_present(self) -> None:
        diagnostics = _device_diagnostics(
            {
                "last_status": {
                    "timestamp": 200,
                    "payload": {
                        "script_state": "IDLE",
                        "ports": [
                            {
                                "port_id": "i2c.s1",
                                "physical_port": "I2C-1",
                                "channel": "Bus S1",
                                "type": "i2c",
                                "status": "offline",
                                "diag": "write addr nack",
                                "last_sample_ms": 1200,
                                "module": {
                                    "module_id": "aht20",
                                    "module_type": "AHT20",
                                    "driver": "aht20",
                                    "address": "0x38",
                                    "confidence": "exact",
                                },
                                "capabilities": [
                                    {"id": "env.temperature", "unit": "C", "access": "read", "status": "offline"},
                                    {"id": "env.humidity", "unit": "%RH", "access": "read", "status": "offline"},
                                ],
                            },
                            {
                                "port_id": "pwm.0",
                                "physical_port": "PWM-0",
                                "channel": "P105",
                                "type": "pwm",
                                "status": "configured",
                                "diag": "no_feedback_open_loop",
                                "last_sample_ms": 0,
                                "module": {
                                    "module_id": "sg90",
                                    "module_type": "SG90",
                                    "driver": "sg90_servo",
                                    "confidence": "user_confirmed",
                                },
                                "capabilities": [
                                    {"id": "motor.servo.angle", "unit": "degree", "access": "write", "status": "configured"},
                                ],
                            },
                            {
                                "port_id": "uart.bridge",
                                "physical_port": "UART-BRIDGE",
                                "channel": "UART0",
                                "type": "uart",
                                "status": "online",
                                "diag": "ok",
                                "last_sample_ms": 1500,
                                "module": {
                                    "module_id": "esp32_bridge",
                                    "module_type": "ESP32-S3",
                                    "driver": "esp32_uart_link",
                                    "confidence": "exact",
                                },
                                "capabilities": [
                                    {"id": "bridge.uart.mqtt", "unit": "-", "access": "readwrite", "status": "online"},
                                ],
                            },
                        ],
                    },
                }
            }
        )

        self.assertEqual("ports_status_payload", diagnostics["hardware_registry"]["source"])
        self.assertEqual("offline", diagnostics["aht20"]["status"])
        self.assertEqual("write addr nack", diagnostics["aht20"]["diag"])
        self.assertEqual(0, diagnostics["i2c"]["count"])
        self.assertEqual("no_device_ack", diagnostics["i2c"]["interpretation"])
        self.assertEqual("online", diagnostics["uart"])
        self.assertIn("motor.servo.angle", [item["id"] for item in diagnostics["platform_capabilities"]])

    def test_hardware_catalog_exposes_common_i2c_platform_capabilities(self) -> None:
        catalog = catalog_status()

        self.assertEqual("platform-hardware-catalog.v1", catalog["version"])
        self.assertIn("i2c", catalog["bus_types"])
        entries = {entry["type"]: entry for entry in catalog["entries"]}
        self.assertIn("AHT20", entries)
        self.assertIn("BME280", entries)
        self.assertIn("PCA9685", entries)
        self.assertIn("env.temperature", entries["AHT20"]["capabilities"])
        self.assertIn("motor.servo.angle", entries["PCA9685"]["capabilities"])

    def test_web_deploy_view_marks_matched_execution_event_as_executed(self) -> None:
        device_id = "exec_device_001"
        request_id = "exec_req_001"
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/status",
            {
                "type": "status",
                "payload": {
                    "device_id": device_id,
                    "uart": "waiting",
                    "script_state": "IDLE",
                    "last_request_id": request_id,
                    "last_execution": {"state": "IDLE", "reason": "RULE_CLEARED"},
                },
            },
        )
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/event",
            {
                "type": "execution_state",
                "request_id": request_id,
                "payload": {
                    "device_id": device_id,
                    "state": "IDLE",
                    "reason": "RULE_CLEARED",
                },
            },
        )
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/status",
            {
                "type": "status",
                "payload": {
                    "device_id": device_id,
                    "uart": "waiting",
                    "script_state": "IDLE",
                    "last_request_id": request_id,
                    "last_execution": {"state": "IDLE", "reason": "RULE_CLEARED"},
                },
            },
        )
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/event",
            {
                "type": "deploy_ack",
                "request_id": request_id,
                "payload": {
                    "device_id": device_id,
                    "state": "SCRIPT_ACCEPTED",
                },
            },
        )

        body = _build_web_deploy_view(
            {
                "request_id": request_id,
                "device_id": device_id,
                "published": True,
                "ack_received": True,
                "topic": f"cloudbridge/{device_id}/script",
            }
        )

        self.assertEqual("executed", body["delivery_stage"])
        self.assertEqual("success", body["status"])
        self.assertTrue(body["execution_layer"]["has_executed"])

    def test_web_deploy_view_marks_latest_screen_text_ack_as_executed(self) -> None:
        device_id = "screen_device_001"
        request_id = "screen_req_001"
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/status",
            {
                "type": "status",
                "payload": {
                    "device_id": device_id,
                    "uart": "waiting",
                    "script_state": "ACKED",
                    "last_request_id": request_id,
                    "last_intent_type": "screen_text",
                    "last_execution": {"state": "IDLE", "reason": "RULE_CLEARED"},
                },
            },
        )
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/event",
            {
                "type": "deploy_ack",
                "request_id": request_id,
                "payload": {
                    "device_id": device_id,
                    "state": "SCRIPT_ACCEPTED",
                },
            },
        )

        body = _build_web_deploy_view(
            {
                "request_id": request_id,
                "device_id": device_id,
                "published": True,
                "ack_received": True,
                "topic": f"cloudbridge/{device_id}/script",
                "message": {
                    "payload": {
                        "intent_type": "screen_text",
                    }
                },
            }
        )

        self.assertEqual("executed", body["delivery_stage"])
        self.assertEqual("success", body["status"])

    def test_rule_based_program_handles_temperature_servo_swing_twice(self) -> None:
        parsed = interpret_text_to_rule_program(
            "当温度到35度时，舵机来回旋转两次",
            Settings(llm_provider="template"),
        )

        program = parsed.program

        self.assertEqual("rule_program.v1", program.version)
        self.assertEqual("AHT20.temp", program.trigger.sensor)
        self.assertEqual("env.temperature", program.trigger.capability)
        self.assertEqual(">=", program.trigger.operator)
        self.assertEqual(35, program.trigger.value)
        self.assertEqual("motor.servo.angle", program.actions[0].capability)
        self.assertEqual([30, 150, 30, 150, 90], [action.params["angle"] for action in program.actions])
        self.assertEqual([350, 350, 350, 350, 350], [action.params["duration_ms"] for action in program.actions])

    def test_program_api_returns_rule_program(self) -> None:
        body = interpret_program(
            ProgramInterpretRequest(text="当温度到35度时，舵机来回旋转两次"),
            Settings(llm_provider="template", log_db_path=":memory:"),
            None,
        )

        self.assertTrue(body["ok"])
        self.assertEqual("rule_program.v1", body["program"]["version"])
        self.assertEqual([30, 150, 30, 150, 90], [item["params"]["angle"] for item in body["program"]["actions"]])

    def test_program_api_delegates_preview_to_hermes_when_provider_is_official(self) -> None:
        settings = Settings(
            llm_provider="hermes_official",
            hermes_official_enabled=True,
            hermes_official_uv_path="/tmp/uv",
            hermes_official_workdir="/tmp",
            hermes_official_model="deepseek-v4-pro",
            deepseek_api_key="test",
            log_db_path=":memory:",
        )
        parsed = interpret_text_to_rule_program(
            "当温度到35度时，舵机来回旋转两次",
            Settings(llm_provider="template"),
        )
        chat_result = HermesOfficialChatResult(
            assistant_message="我会把它规划为 rule_program 预览。",
            action_kind="rule_program",
            session_id="sess_preview_001",
            raw_text="{}",
            program=parsed.program,
        )

        with patch("cloud.app.api.routes.chat_with_hermes_official", return_value=chat_result):
            body = interpret_program(
                ProgramInterpretRequest(text="当温度到35度时，舵机来回旋转两次"),
                settings,
                None,
            )

        self.assertTrue(body["ok"])
        self.assertEqual("hermes_official:deepseek-v4-pro+chat", body["source"])
        self.assertEqual("rule_program_v1", body["route"])
        self.assertEqual("sess_preview_001", body["session_id"])
        self.assertEqual("rule_program", body["action_kind"])
        self.assertEqual("rule_program.v1", body["program"]["version"])

    def test_program_api_rejects_unsupported_text(self) -> None:
        with self.assertRaises(HTTPException) as context:
            interpret_program(
                ProgramInterpretRequest(text="舵机来回旋转两次"),
                Settings(llm_provider="template", log_db_path=":memory:"),
                None,
            )

        self.assertEqual(422, context.exception.status_code)
        self.assertIn("temperature threshold", str(context.exception.detail))

    def test_action_schema_rejects_unsafe_angle(self) -> None:
        with self.assertRaises(ValueError):
            RuleProgramAction(device="SG90", method="servo_set", params={"angle": 181, "duration_ms": 350})

    def test_rule_program_accepts_platform_temperature_capability_alias(self) -> None:
        program = RuleProgram(
            trigger=RuleProgramTrigger(sensor="env.temperature", operator=">=", value=30),
            actions=[RuleProgramAction(device="SG90", method="servo_set", params={"angle": 90})],
        )

        self.assertEqual("AHT20.temp", program.trigger.sensor)
        self.assertEqual("env.temperature", program.trigger.capability)
        self.assertEqual("motor.servo.angle", program.actions[0].capability)

    def test_deepseek_provider_can_generate_rule_program(self) -> None:
        content = (
            '{"version":"rule_program.v1",'
            '"trigger":{"sensor":"AHT20.temp","operator":">=","value":35},'
            '"actions":[{"device":"SG90","method":"servo_set","params":{"angle":30,"duration_ms":350}},'
            '{"device":"SG90","method":"servo_set","params":{"angle":150,"duration_ms":350}},'
            '{"device":"SG90","method":"servo_set","params":{"angle":90,"duration_ms":350}}],'
            '"loop_interval_ms":1000,"cooldown_ms":30000,"description":"test"}'
        )

        with patch("cloud.app.agent_service.deepseek._post_chat_completion", return_value=content):
            parsed = interpret_text_to_rule_program(
                "当温度到35度时，舵机来回旋转一次",
                Settings(llm_provider="deepseek", deepseek_api_key="test", deepseek_model="deepseek-v4-pro"),
            )

        self.assertEqual("rule_based_action_plan_v1+fastpath", parsed.source)
        self.assertEqual(35, parsed.program.trigger.value)
        self.assertEqual([30, 150, 90], [action.params["angle"] for action in parsed.program.actions])

    def test_interpret_and_deploy_returns_rule_program_payload(self) -> None:
        settings = Settings(llm_provider="template", mqtt_enabled=False, log_db_path=":memory:")
        body = interpret_program_and_deploy(
            ProgramInterpretDeployRequest(
                request_id="req_program_001",
                text="当温度到35度时，舵机来回旋转两次",
                wait_for_ack=False,
            ),
            settings,
            AgentOrchestrator(settings, MqttPublisher(settings)),
            None,
        )

        self.assertTrue(body["ok"])
        self.assertEqual("planned", body["status"])
        self.assertEqual("rule_program", body["mqtt_message"]["payload"]["intent_type"])
        self.assertIn("rule_program", body["mqtt_message"]["payload"])
        self.assertEqual(5, len(body["mqtt_message"]["payload"]["rule_program"]["actions"]))

    def test_hermes_official_provider_can_generate_rule_program(self) -> None:
        content = (
            '{"version":"rule_program.v1",'
            '"trigger":{"sensor":"AHT20.temp","operator":">=","value":26},'
            '"actions":[{"device":"SG90","method":"servo_set","params":{"angle":30,"duration_ms":350}},'
            '{"device":"SG90","method":"servo_set","params":{"angle":150,"duration_ms":350}},'
            '{"device":"SG90","method":"servo_set","params":{"angle":90,"duration_ms":350}}],'
            '"loop_interval_ms":1000,"cooldown_ms":30000,"description":"test"}'
        )

        with patch("cloud.app.agent_service.hermes_official._run_hermes_oneshot", return_value=content):
            parsed = interpret_text_to_rule_program(
                "当温度到26度时，舵机来回旋转一次",
                Settings(
                    llm_provider="hermes_official",
                    deepseek_api_key="test",
                    hermes_official_enabled=True,
                    hermes_official_uv_path="/tmp/uv",
                    hermes_official_workdir="/tmp",
                    hermes_official_model="deepseek-v4-pro",
                ),
            )

        self.assertEqual("hermes_official:deepseek-v4-pro+rule_program_v1", parsed.source)
        self.assertEqual(26, parsed.program.trigger.value)
        self.assertEqual([30, 150, 90], [action.params["angle"] for action in parsed.program.actions])

    def test_hermes_chat_preview_returns_answer_without_deploy(self) -> None:
        settings = Settings(
            llm_provider="hermes_official",
            hermes_official_enabled=True,
            hermes_official_uv_path="/tmp/uv",
            hermes_official_workdir="/tmp",
            deepseek_api_key="test",
            mqtt_enabled=False,
            log_db_path=":memory:",
        )
        orchestrator = AgentOrchestrator(settings, MqttPublisher(settings))
        chat_result = HermesOfficialChatResult(
            assistant_message="当前不会下发硬件动作，只回答问题。",
            action_kind="none",
            session_id="sess_demo_001",
            raw_text="{}",
        )

        with patch("cloud.app.api.routes.chat_with_hermes_official", return_value=chat_result):
            body = hermes_chat(
                HermesChatRequest(
                    request_id="chat_preview_001",
                    text="现在系统在做什么",
                    preview_only=True,
                ),
                settings,
                orchestrator,
            )

        self.assertTrue(body["ok"])
        self.assertEqual("answered", body["status"])
        self.assertEqual("answered", body["delivery_stage"])
        self.assertEqual("sess_demo_001", body["session_id"])
        self.assertEqual("none", body["action_kind"])
        self.assertEqual("当前不会下发硬件动作，只回答问题。", body["assistant_message"])

    def test_hermes_official_chat_accepts_plain_text_reply(self) -> None:
        settings = Settings(
            llm_provider="hermes_official",
            hermes_official_enabled=True,
            hermes_official_uv_path="/tmp/uv",
            hermes_official_workdir="/tmp",
            deepseek_api_key="test",
        )

        with patch("cloud.app.agent_service.hermes_official._latest_session_id", side_effect=["sess_before", "sess_after"]):
            with patch(
                "cloud.app.agent_service.hermes_official._run_hermes_prompt",
                return_value="当前可以回答问题，也可以在需要时继续下发控制。",
            ):
                result = chat_with_hermes_official("你现在能做什么", settings)

        self.assertEqual("none", result.action_kind)
        self.assertEqual("sess_after", result.session_id)
        self.assertIn("回答问题", result.assistant_message)

    def test_hermes_chat_can_deploy_rule_program(self) -> None:
        settings = Settings(
            llm_provider="hermes_official",
            hermes_official_enabled=True,
            hermes_official_uv_path="/tmp/uv",
            hermes_official_workdir="/tmp",
            deepseek_api_key="test",
            mqtt_enabled=False,
            log_db_path=":memory:",
        )
        orchestrator = AgentOrchestrator(settings, MqttPublisher(settings))
        parsed = interpret_text_to_rule_program(
            "当温度到25度时，舵机来回旋转两次",
            Settings(llm_provider="template"),
        )
        chat_result = HermesOfficialChatResult(
            assistant_message="我会按 25 度温度阈值下发舵机动作。",
            action_kind="rule_program",
            session_id="sess_demo_002",
            raw_text="{}",
            program=parsed.program,
        )

        with patch("cloud.app.api.routes.chat_with_hermes_official", return_value=chat_result):
            body = hermes_chat(
                HermesChatRequest(
                    request_id="chat_deploy_001",
                    text="当温度到25度时，舵机来回旋转两次",
                    wait_for_ack=False,
                ),
                settings,
                orchestrator,
            )

        self.assertTrue(body["ok"])
        self.assertEqual("sess_demo_002", body["session_id"])
        self.assertEqual("planned", body["delivery_stage"])
        self.assertEqual("rule_program", body["mqtt_message"]["payload"]["intent_type"])
        self.assertEqual("hermes_official:deepseek-v4-pro+chat", body["intent_source"])

    def test_hermes_chat_passes_device_diagnostics_to_official_hermes(self) -> None:
        settings = Settings(
            llm_provider="hermes_official",
            hermes_official_enabled=True,
            hermes_official_uv_path="/tmp/uv",
            hermes_official_workdir="/tmp",
            deepseek_api_key="test",
            mqtt_enabled=False,
            log_db_path=":memory:",
        )
        device_id = "diag_device_001"
        device_state_store.update_from_mqtt(
            f"cloudbridge/{device_id}/status",
            {
                "type": "status",
                "payload": {
                    "device_id": device_id,
                    "uart": "online",
                    "script_state": "ACKED",
                    "i2c": {
                        "bus": "s1",
                        "diag": "ok",
                        "count": 1,
                        "devices": [{"address": "0x38", "type": "AHT20"}],
                    },
                    "hardware_list": [{"address": "0x38", "type": "AHT20", "status": "present", "bus": "s1"}],
                    "aht20": {"status": "offline", "crc_ok": False, "diag": "write addr nack"},
                    "last_execution": {"state": "ARMED", "sample": False},
                },
            },
        )
        orchestrator = AgentOrchestrator(settings, MqttPublisher(settings))
        chat_result = HermesOfficialChatResult(
            assistant_message="AHT20 离线，温度规则只能保持 armed。",
            action_kind="none",
            session_id="sess_diag_001",
            raw_text="{}",
        )

        with patch("cloud.app.api.routes.chat_with_hermes_official", return_value=chat_result) as hermes_call:
            body = hermes_chat(
                HermesChatRequest(
                    request_id="chat_diag_001",
                    text="现在温度规则为什么没触发",
                    device_id=device_id,
                    preview_only=True,
                ),
                settings,
                orchestrator,
            )

        device_context = hermes_call.call_args.kwargs["device_context"]
        self.assertEqual("write addr nack", device_context["diagnostics"]["aht20"]["diag"])
        self.assertEqual(1, device_context["diagnostics"]["i2c"]["count"])
        self.assertEqual("0x38", device_context["diagnostics"]["i2c"]["devices"][0]["address"])
        self.assertEqual("write addr nack", body["device_diagnostics"]["aht20"]["diag"])
        self.assertEqual(1, body["device_diagnostics"]["i2c"]["count"])
        self.assertEqual("devices_present", body["device_diagnostics"]["i2c"]["interpretation"])
        self.assertEqual(2, len(device_context["diagnostics"]["blocking_conditions"]))

    def test_program_interpret_deploy_delegates_to_hermes_chat_when_provider_is_official(self) -> None:
        settings = Settings(
            llm_provider="hermes_official",
            hermes_official_enabled=True,
            hermes_official_uv_path="/tmp/uv",
            hermes_official_workdir="/tmp",
            deepseek_api_key="test",
            mqtt_enabled=False,
            log_db_path=":memory:",
        )
        orchestrator = AgentOrchestrator(settings, MqttPublisher(settings))
        delegated = {"ok": True, "status": "answered", "action_kind": "none", "session_id": "sess_from_delegate"}

        with patch("cloud.app.api.routes.hermes_chat", return_value=delegated) as hermes_route:
            body = interpret_program_and_deploy(
                ProgramInterpretDeployRequest(
                    request_id="delegate_program_001",
                    text="现在系统状态如何",
                    wait_for_ack=False,
                ),
                settings,
                orchestrator,
                None,
            )

        self.assertEqual(delegated, body)
        hermes_request = hermes_route.call_args.args[0]
        self.assertIsInstance(hermes_request, HermesChatRequest)
        self.assertEqual("delegate_program_001", hermes_request.request_id)
        self.assertEqual("现在系统状态如何", hermes_request.text)

    def test_interpret_deploy_delegates_to_hermes_chat_when_provider_is_official(self) -> None:
        settings = Settings(
            llm_provider="hermes_official",
            hermes_official_enabled=True,
            hermes_official_uv_path="/tmp/uv",
            hermes_official_workdir="/tmp",
            deepseek_api_key="test",
            mqtt_enabled=False,
            log_db_path=":memory:",
        )
        orchestrator = AgentOrchestrator(settings, MqttPublisher(settings))
        delegated = {"ok": True, "status": "answered", "action_kind": "none", "session_id": "sess_from_delegate"}

        with patch("cloud.app.api.routes.hermes_chat", return_value=delegated) as hermes_route:
            body = interpret_and_deploy(
                InterpretDeployRequest(
                    request_id="delegate_intent_001",
                    text="你现在能做什么",
                    wait_for_ack=False,
                ),
                settings,
                orchestrator,
                None,
            )

        self.assertEqual(delegated, body)
        hermes_request = hermes_route.call_args.args[0]
        self.assertIsInstance(hermes_request, HermesChatRequest)
        self.assertEqual("delegate_intent_001", hermes_request.request_id)
        self.assertEqual("你现在能做什么", hermes_request.text)


if __name__ == "__main__":
    unittest.main()
