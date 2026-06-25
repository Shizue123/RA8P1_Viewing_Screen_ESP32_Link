from __future__ import annotations

import unittest
from unittest.mock import patch

from cloud.app.agent_service.orchestrator import AgentOrchestrator
from cloud.app.agent_service.runtime_agent import HermesRA8P1Agent, SpecializedHardwareAgent
from cloud.app.config import Settings
from cloud.app.models import AgentDeployRequest, AgentPlanRequest
from cloud.app.mqtt_service.client import MqttPublisher


class RuntimeAgentTest(unittest.TestCase):
    def test_runtime_status_reports_rule_based_default_and_deepseek_readiness(self) -> None:
        agent = HermesRA8P1Agent(Settings(llm_provider="template", deepseek_api_key="", log_db_path=":memory:"))

        status = agent.runtime_status()

        self.assertEqual("hermes_ra8p1_v1", status["agent_id"])
        self.assertEqual("specialized_agent_v1", status["compatibility_agent_id"])
        self.assertEqual("hermes_specialized_for_ra8p1", status["agent_shell"])
        self.assertEqual("template", status["llm_provider"])
        self.assertEqual("rule_based_primary", status["planner_mode"])
        self.assertEqual("rule_program.v1", status["hermes"]["control_core"])
        self.assertIn("episodic_agent_runs", status["hermes"]["memory_layers"])
        self.assertEqual("deepseek-v4-pro", status["deepseek"]["model"])
        self.assertFalse(status["deepseek"]["configured"])
        self.assertTrue(status["deepseek"]["fallback_rule_based_available"])

    def test_runtime_status_reports_deepseek_primary_when_configured(self) -> None:
        agent = HermesRA8P1Agent(
            Settings(
                llm_provider="deepseek",
                deepseek_api_key="test",
                deepseek_model="deepseek-v4-pro",
                log_db_path=":memory:",
            )
        )

        status = agent.runtime_status()

        self.assertEqual("deepseek_primary", status["planner_mode"])
        self.assertTrue(status["deepseek"]["configured"])

    def test_runtime_status_reports_hermes_official_primary_when_configured(self) -> None:
        agent = HermesRA8P1Agent(
            Settings(
                llm_provider="hermes_official",
                deepseek_api_key="test",
                hermes_official_enabled=True,
                hermes_official_uv_path="/home/admin/.hermes/bin/uv",
                hermes_official_workdir="/home/admin/.hermes/hermes-agent",
                hermes_official_model="deepseek-v4-pro",
                log_db_path=":memory:",
            )
        )

        status = agent.runtime_status()

        self.assertEqual("hermes_official_primary", status["planner_mode"])
        self.assertTrue(status["hermes_official"]["enabled"])
        self.assertEqual("deepseek-v4-pro", status["hermes_official"]["model"])

    def test_plan_builds_rule_program_and_knowledge_snapshot(self) -> None:
        settings = Settings(llm_provider="template", mqtt_enabled=False, log_db_path=":memory:")
        agent = HermesRA8P1Agent(settings)

        response = agent.plan(AgentPlanRequest(text="当温度达到35度时，舵机来回旋转两次"))

        self.assertEqual("rule_program_v1", response.route.value)
        self.assertTrue(response.source.startswith("hermes_ra8p1_v1:"))
        self.assertIn("load_hermes_identity", response.graph_trace)
        self.assertIn("hermes_cycle_journal", response.graph_trace)
        self.assertIn("AHT20", response.knowledge_snapshot.supported_sensors)
        self.assertIn("SG90", response.knowledge_snapshot.supported_actuators)
        self.assertEqual([30, 150, 30, 150, 90], [item.params["angle"] for item in response.program.actions])

    def test_deploy_hands_off_to_existing_program_graph_and_records_ack(self) -> None:
        settings = Settings(llm_provider="template", mqtt_enabled=False, log_db_path=":memory:")
        agent = HermesRA8P1Agent(settings)
        orchestrator = AgentOrchestrator(settings, MqttPublisher(settings))

        response = agent.deploy(
            AgentDeployRequest(
                request_id="agent_runtime_001",
                text="当温度达到35度时，舵机来回旋转两次",
                wait_for_ack=False,
            ),
            orchestrator,
        )

        self.assertEqual("rule_program_v1", response.route.value)
        self.assertTrue(response.source.startswith("hermes_ra8p1_v1:"))
        self.assertEqual("rule_program", response.message.payload["intent_type"])
        self.assertIn("load_hermes_continuity", response.graph_trace)
        self.assertIn("handoff_program_graph", response.graph_trace)
        self.assertIn("hermes_cycle_journal", response.graph_trace)

        run = agent.get_run("agent_runtime_001")

        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual("rule_program_v1", run["route"])
        self.assertEqual("当温度达到35度时，舵机来回旋转两次", run["user_text"])
        self.assertIn("program", run["plan"])
        self.assertIn("deployment", run)

    def test_plan_uses_deepseek_source_when_provider_enabled(self) -> None:
        content = (
            '{"version":"rule_program.v1",'
            '"trigger":{"sensor":"AHT20.temp","operator":">=","value":35},'
            '"actions":[{"device":"SG90","method":"servo_set","params":{"angle":30,"duration_ms":350}},'
            '{"device":"SG90","method":"servo_set","params":{"angle":150,"duration_ms":350}},'
            '{"device":"SG90","method":"servo_set","params":{"angle":90,"duration_ms":350}}],'
            '"loop_interval_ms":1000,"cooldown_ms":30000,"description":"test"}'
        )

        with patch("cloud.app.agent_service.deepseek._post_chat_completion", return_value=content):
            agent = HermesRA8P1Agent(
                Settings(llm_provider="deepseek", deepseek_api_key="test", deepseek_model="deepseek-v4-pro", log_db_path=":memory:")
            )
            response = agent.plan(AgentPlanRequest(text="当温度达到35度时，舵机来回旋转一次"))

        self.assertIn("rule_based_action_plan_v1+fastpath", response.source)

    def test_plan_uses_hermes_official_source_when_provider_enabled(self) -> None:
        content = (
            '{"version":"rule_program.v1",'
            '"trigger":{"sensor":"AHT20.temp","operator":">=","value":27},'
            '"actions":[{"device":"SG90","method":"servo_set","params":{"angle":30,"duration_ms":350}},'
            '{"device":"SG90","method":"servo_set","params":{"angle":150,"duration_ms":350}},'
            '{"device":"SG90","method":"servo_set","params":{"angle":90,"duration_ms":350}}],'
            '"loop_interval_ms":1000,"cooldown_ms":30000,"description":"test"}'
        )

        with patch("cloud.app.agent_service.hermes_official._run_hermes_oneshot", return_value=content):
            agent = HermesRA8P1Agent(
                Settings(
                    llm_provider="hermes_official",
                    deepseek_api_key="test",
                    hermes_official_enabled=True,
                    hermes_official_uv_path="/tmp/uv",
                    hermes_official_workdir="/tmp",
                    hermes_official_model="deepseek-v4-pro",
                    log_db_path=":memory:",
                )
            )
            response = agent.plan(AgentPlanRequest(text="当温度达到27度时，舵机来回旋转一次"))

        self.assertIn("hermes_official:deepseek-v4-pro+rule_program_v1", response.source)

    def test_legacy_agent_name_still_maps_to_hermes_shell(self) -> None:
        agent = SpecializedHardwareAgent(Settings(llm_provider="template", log_db_path=":memory:"))

        status = agent.runtime_status()

        self.assertEqual("hermes_ra8p1_v1", status["agent_id"])


if __name__ == "__main__":
    unittest.main()
