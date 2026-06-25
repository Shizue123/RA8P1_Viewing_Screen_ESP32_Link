from __future__ import annotations

import time
from dataclasses import dataclass, field

from cloud.app.config import Settings
from cloud.app.device_state.store import device_state_store
from cloud.app.knowledge_base import ProjectKnowledge, get_project_knowledge
from cloud.app.log_service.store import PersistentLogStore
from cloud.app.models import DeployResponse, MqttEnvelope, ProgramDeployRequest
from cloud.app.mqtt_service.client import MqttPublisher, PublishResult
from cloud.app.security import build_script_signature
from cloud.app.template_compiler.compiler import build_program_deploy_payload, compile_rule_program_to_lua


@dataclass
class ProgramGraphState:
    request: ProgramDeployRequest
    settings: Settings
    mqtt_publisher: MqttPublisher
    log_store: PersistentLogStore
    device_id: str = ""
    knowledge: ProjectKnowledge | None = None
    knowledge_validation: dict[str, object] = field(default_factory=dict)
    lua_code: str = ""
    lua_validation: dict[str, object] = field(default_factory=dict)
    message: MqttEnvelope | None = None
    mqtt_validation: dict[str, object] = field(default_factory=dict)
    publish_result: PublishResult | None = None
    ack: dict[str, object] | None = None
    trace: list[str] = field(default_factory=list)


class ProgramGraph:
    def run(self, request: ProgramDeployRequest, settings: Settings, mqtt_publisher: MqttPublisher) -> DeployResponse:
        state = ProgramGraphState(
            request=request,
            settings=settings,
            mqtt_publisher=mqtt_publisher,
            log_store=PersistentLogStore(settings.log_db_path),
        )
        for node in (
            self.resolve_device,
            self.load_runtime_knowledge,
            self.validate_program,
            self.compile_lua,
            self.build_mqtt_message,
            self.validate_mqtt_message,
            self.publish_mqtt,
            self.record_deploy,
            self.wait_for_ack,
            self.record_ack,
            self.build_response,
        ):
            node(state)
        response = state.response
        return response

    def resolve_device(self, state: ProgramGraphState) -> None:
        state.device_id = state.request.device_id or state.settings.device_id
        state.trace.append("resolve_device")

    def load_runtime_knowledge(self, state: ProgramGraphState) -> None:
        state.knowledge = get_project_knowledge()
        state.trace.append("load_runtime_knowledge")

    def validate_program(self, state: ProgramGraphState) -> None:
        assert state.knowledge is not None
        state.knowledge_validation = state.knowledge.validate_rule_program(state.request.program)
        if not state.knowledge_validation["ok"]:
            raise ValueError("; ".join(str(error) for error in state.knowledge_validation["errors"]))
        state.trace.append("validate_program")

    def compile_lua(self, state: ProgramGraphState) -> None:
        state.lua_code, state.lua_validation = compile_rule_program_to_lua(state.request.program)
        state.trace.append("compile_rule_program_lua")

    def build_mqtt_message(self, state: ProgramGraphState) -> None:
        timestamp = int(time.time())
        deploy_payload = build_program_deploy_payload(state.request.program, state.lua_code, state.request.need_confirm)
        if state.settings.mqtt_enabled and not state.settings.mqtt_script_secret:
            raise ValueError("mqtt_script_secret is required when MQTT publishing is enabled")
        deploy_payload.target_device_id = state.device_id
        deploy_payload.auth_signature = build_script_signature(
            state.settings.mqtt_script_secret or "preview-secret",
            state.request.request_id,
            deploy_payload.script_id,
            deploy_payload.intent_type.value,
            deploy_payload.checksum,
            timestamp,
            state.device_id,
        )
        state.message = MqttEnvelope(
            request_id=state.request.request_id,
            type="deploy_script",
            timestamp=timestamp,
            payload=deploy_payload.model_dump(mode="json"),
        )
        state.trace.append("build_mqtt_message")

    def validate_mqtt_message(self, state: ProgramGraphState) -> None:
        assert state.knowledge is not None
        assert state.message is not None
        state.mqtt_validation = state.knowledge.validate_mqtt_envelope(state.message)
        if not state.mqtt_validation["ok"]:
            raise ValueError("; ".join(str(error) for error in state.mqtt_validation["errors"]))
        state.trace.append("validate_mqtt_message")

    def publish_mqtt(self, state: ProgramGraphState) -> None:
        assert state.message is not None
        state.publish_result = state.mqtt_publisher.publish_script(state.device_id, state.message)
        state.trace.append("publish_mqtt")

    def record_deploy(self, state: ProgramGraphState) -> None:
        assert state.message is not None
        assert state.publish_result is not None
        state.log_store.record_deploy(
            request_id=state.request.request_id,
            device_id=state.device_id,
            topic=state.publish_result.topic,
            intent={"rule_program": state.request.program.model_dump(mode="json")},
            message=state.message.model_dump(mode="json"),
            lua_validation=state.lua_validation,
            mqtt_enabled=state.settings.mqtt_enabled,
            published=state.publish_result.published,
        )
        state.trace.append("record_deploy")

    def wait_for_ack(self, state: ProgramGraphState) -> None:
        assert state.publish_result is not None
        if state.publish_result.published and state.request.wait_for_ack:
            state.ack = device_state_store.wait_for_deploy_ack(
                device_id=state.device_id,
                request_id=state.request.request_id,
                timeout_sec=state.settings.deploy_ack_timeout_sec,
            )
        state.trace.append("wait_for_ack")

    def record_ack(self, state: ProgramGraphState) -> None:
        if state.ack is not None:
            state.log_store.record_ack(state.device_id, state.ack)
        state.trace.append("record_ack")

    def build_response(self, state: ProgramGraphState) -> None:
        assert state.message is not None
        assert state.publish_result is not None
        state.response = DeployResponse(
            request_id=state.request.request_id,
            device_id=state.device_id,
            topic=state.publish_result.topic,
            mqtt_enabled=state.settings.mqtt_enabled,
            message=state.message,
            lua_validation=state.lua_validation,
            knowledge_validation=state.knowledge_validation,
            mqtt_validation=state.mqtt_validation,
            graph_trace=state.trace,
            ack_received=state.ack is not None,
            ack=state.ack,
        )
        state.trace.append("build_response")
