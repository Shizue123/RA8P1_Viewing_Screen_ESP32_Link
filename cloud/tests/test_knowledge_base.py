from __future__ import annotations

import unittest

from cloud.app.api.routes import agent_skills, compile_intent, knowledge_status
from cloud.app.knowledge_base import get_project_knowledge
from cloud.app.models import CompileRequest, Intent


class KnowledgeBaseTest(unittest.TestCase):
    def test_cloud_runtime_exposes_llm_wiki_and_gbrain_status(self) -> None:
        status = knowledge_status(None)

        self.assertTrue(status["ok"])
        self.assertTrue(status["llm_wiki"]["available"])
        self.assertTrue(status["gbrain"]["available"])
        self.assertIn("mcp/resources/gbrain/capabilities.json", status["sources"])
        self.assertIn("skills.json", status["gbrain"]["resources"])

    def test_validates_intent_against_gbrain_and_manifests(self) -> None:
        intent = _threshold_intent()

        validation = get_project_knowledge().validate_intent(intent)

        self.assertTrue(validation["ok"])
        self.assertIn("template.intent.threshold_temperature_servo_buzzer", validation["matched_templates"])
        self.assertIn("skill.threshold_temperature_control", validation["matched_skills"])

    def test_compile_endpoint_returns_knowledge_and_mqtt_validation(self) -> None:
        body = compile_intent(CompileRequest(intent=_threshold_intent()), None)

        self.assertTrue(body["ok"])
        self.assertTrue(body["knowledge_validation"]["ok"])
        self.assertTrue(body["mqtt_validation"]["ok"])

    def test_skills_endpoint_returns_runtime_skills(self) -> None:
        body = agent_skills(None)

        self.assertTrue(body["ok"])
        skill_ids = {item["id"] for item in body["skills"]}
        self.assertIn("skill.threshold_temperature_control", skill_ids)
        self.assertIn("mcp/resources/gbrain/skills.json", body["sources"])


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
