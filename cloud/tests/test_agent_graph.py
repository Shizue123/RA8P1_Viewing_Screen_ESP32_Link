from __future__ import annotations

import unittest

from cloud.app.agent_service.orchestrator import AgentOrchestrator
from cloud.app.config import Settings
from cloud.app.models import DeployRequest, Intent
from cloud.app.mqtt_service.client import MqttPublisher


class AgentGraphTest(unittest.TestCase):
    def test_compile_and_deploy_uses_explicit_graph_trace(self) -> None:
        settings = Settings(mqtt_enabled=False, log_db_path=":memory:")
        response = AgentOrchestrator(settings, MqttPublisher(settings)).compile_and_deploy(
            DeployRequest(request_id="req_graph", intent=_threshold_intent(), wait_for_ack=False)
        )

        self.assertTrue(response.knowledge_validation["ok"])
        self.assertTrue(response.mqtt_validation["ok"])
        self.assertFalse(response.ack_received)
        self.assertEqual(
            [
                "resolve_device",
                "load_runtime_knowledge",
                "validate_intent",
                "compile_lua",
                "build_mqtt_message",
                "validate_mqtt_message",
                "publish_mqtt",
                "record_deploy",
                "wait_for_ack",
                "record_ack",
            ],
            response.graph_trace,
        )


def _threshold_intent() -> Intent:
    return Intent.model_validate(
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


if __name__ == "__main__":
    unittest.main()
