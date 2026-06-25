from __future__ import annotations

from cloud.app.config import Settings
from cloud.app.agent_service.graph import AgentGraph
from cloud.app.agent_service.program_graph import ProgramGraph
from cloud.app.models import DeployRequest, DeployResponse, ProgramDeployRequest
from cloud.app.mqtt_service.client import MqttPublisher


class AgentOrchestrator:
    def __init__(self, settings: Settings, mqtt_publisher: MqttPublisher) -> None:
        self._settings = settings
        self._mqtt_publisher = mqtt_publisher
        self._graph = AgentGraph()
        self._program_graph = ProgramGraph()

    def compile_and_deploy(self, request: DeployRequest) -> DeployResponse:
        return self._graph.run(request, self._settings, self._mqtt_publisher)

    def deploy_rule_program(self, request: ProgramDeployRequest) -> DeployResponse:
        return self._program_graph.run(request, self._settings, self._mqtt_publisher)
