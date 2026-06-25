from __future__ import annotations

import unittest

from cloud.app.agent_service.orchestrator import AgentOrchestrator
from cloud.app.config import Settings
from cloud.app.models import ProgramDeployRequest, RuleProgram
from cloud.app.mqtt_service.client import MqttPublisher


class ProgramGraphTest(unittest.TestCase):
    def test_program_deploy_uses_explicit_graph_trace(self) -> None:
        settings = Settings(mqtt_enabled=False, log_db_path=":memory:")
        response = AgentOrchestrator(settings, MqttPublisher(settings)).deploy_rule_program(
            ProgramDeployRequest(request_id="req_program_graph", program=_program(), wait_for_ack=False)
        )

        self.assertTrue(response.knowledge_validation["ok"])
        self.assertTrue(response.mqtt_validation["ok"])
        self.assertFalse(response.ack_received)
        self.assertEqual("rule_program", response.message.payload["intent_type"])
        self.assertIsNotNone(response.message.payload["rule_program"])
        self.assertEqual(
            [
                "resolve_device",
                "load_runtime_knowledge",
                "validate_program",
                "compile_rule_program_lua",
                "build_mqtt_message",
                "validate_mqtt_message",
                "publish_mqtt",
                "record_deploy",
                "wait_for_ack",
                "record_ack",
            ],
            response.graph_trace,
        )


def _program() -> RuleProgram:
    return RuleProgram.model_validate(
        {
            "program_id": "rp_test",
            "version": "rule_program.v1",
            "trigger": {"sensor": "AHT20.temp", "operator": ">=", "value": 35},
            "actions": [
                {"device": "SG90", "method": "servo_set", "params": {"angle": 30, "duration_ms": 350}},
                {"device": "SG90", "method": "servo_set", "params": {"angle": 150, "duration_ms": 350}},
                {"device": "SG90", "method": "servo_set", "params": {"angle": 90, "duration_ms": 350}},
            ],
            "loop_interval_ms": 1000,
            "cooldown_ms": 30000,
            "description": "test",
        }
    )


if __name__ == "__main__":
    unittest.main()
