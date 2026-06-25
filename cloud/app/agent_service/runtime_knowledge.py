from __future__ import annotations

from dataclasses import dataclass

from cloud.app.device_state.store import device_state_store
from cloud.app.knowledge_base import ProjectKnowledge, get_project_knowledge
from cloud.app.log_service.store import PersistentLogStore
from cloud.app.models import AgentKnowledgeSnapshot


@dataclass(frozen=True)
class RuntimeKnowledgeBundle:
    knowledge: ProjectKnowledge
    snapshot: AgentKnowledgeSnapshot
    prompt_context: dict[str, object]


def build_runtime_knowledge_bundle(device_id: str, log_store: PersistentLogStore) -> RuntimeKnowledgeBundle:
    knowledge = get_project_knowledge()
    latest_state = device_state_store.snapshot(device_id)
    recent_deployments = log_store.list_deployments(8)

    sensors = sorted(
        str(device.get("name", ""))
        for device in knowledge.hardware_manifest.get("v1_devices", [])
        if device.get("type") == "sensor"
    )
    actuators = sorted(
        str(device.get("name", ""))
        for device in knowledge.hardware_manifest.get("v1_devices", [])
        if device.get("type") == "actuator"
    )
    matched_capabilities = sorted(
        str(capability.get("id", ""))
        for capability in knowledge.gbrain_capabilities.get("capabilities", [])
        if capability.get("intent_type") in {"threshold_control", "screen_text"}
    )
    recent_request_ids = [
        str(item.get("request_id", ""))
        for item in recent_deployments
        if item.get("device_id") == device_id and item.get("request_id")
    ][:5]

    snapshot = AgentKnowledgeSnapshot(
        device_id=device_id,
        primary_sources=knowledge.status()["sources"],
        supported_sensors=sensors,
        supported_actuators=actuators,
        matched_capabilities=matched_capabilities,
        recent_request_ids=recent_request_ids,
        latest_device_state=latest_state,
    )

    prompt_context = {
        "device_id": device_id,
        "supported_sensors": sensors,
        "supported_actuators": actuators,
        "matched_capabilities": matched_capabilities,
        "recent_deployments": [
            {
                "request_id": item.get("request_id"),
                "script_id": item.get("script_id"),
                "ack_received": item.get("ack_received"),
                "intent": item.get("intent"),
            }
            for item in recent_deployments[:3]
        ],
        "latest_device_state": latest_state,
        "source_paths": snapshot.primary_sources,
    }
    return RuntimeKnowledgeBundle(
        knowledge=knowledge,
        snapshot=snapshot,
        prompt_context=prompt_context,
    )
