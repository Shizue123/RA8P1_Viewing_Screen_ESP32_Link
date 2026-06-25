from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from cloud.app.hardware_catalog import (
    capability_for_sensor,
    catalog_status,
    known_trigger_capabilities,
    legacy_sensor_for_capability,
)
from cloud.app.models import Intent, MqttEnvelope, RuleProgram


ROOT = Path(__file__).resolve().parents[2]

JsonObject = dict[str, Any]


@dataclass(frozen=True)
class ProjectKnowledge:
    project_manifest: JsonObject
    protocol_manifest: JsonObject
    hardware_manifest: JsonObject
    gbrain_capabilities: JsonObject
    gbrain_entities: JsonObject
    gbrain_skills: JsonObject
    gbrain_templates: JsonObject

    def status(self) -> JsonObject:
        return {
            "ok": True,
            "llm_wiki": {
                "root": "docs",
                "available": (ROOT / "docs" / "知识管理方案.md").exists(),
                "primary_documents": self.project_manifest.get("primary_documents", []),
            },
            "gbrain": {
                "root": "mcp/resources/gbrain",
                "available": True,
                "resources": [
                    "entities.json",
                    "relations.json",
                    "capabilities.json",
                    "skills.json",
                    "templates.json",
                    "task_routing.json",
                    "maintenance_workflows.json",
                    "update_policy.json",
                    "decisions.json",
                    "risks.json",
                ],
            },
            "mcp_equivalent_checks": [
                "validate_lua_api",
                "validate_mqtt_payload",
                "compile_intent_to_lua",
            ],
            "platform_hardware_catalog": {
                "version": catalog_status()["version"],
                "bus_types": catalog_status()["bus_types"],
                "entry_count": len(catalog_status()["entries"]),
            },
            "sources": _source_paths(),
        }

    def skills(self) -> JsonObject:
        return {
            "ok": True,
            "skills": self.gbrain_skills.get("skills", []),
            "positioning": self.gbrain_skills.get("positioning", {}),
            "behavior_guidelines": self.gbrain_skills.get("behavior_guidelines", {}),
            "sources": ["mcp/resources/gbrain/skills.json"],
        }

    def validate_intent(self, intent: Intent) -> JsonObject:
        errors: list[str] = []
        warnings: list[str] = []

        supported_intents = set(self.protocol_manifest.get("intent", {}).get("v1_supported_intent_types", []))
        if intent.intent_type.value not in supported_intents:
            errors.append(f"intent_type is not supported by protocol_manifest: {intent.intent_type}")

        capability = self._capability_for_intent(intent.intent_type.value)
        if not capability:
            errors.append(f"intent_type has no matching GBrain capability: {intent.intent_type}")
        else:
            supported_sensor = capability.get("supported_sensor")
            if supported_sensor and (
                intent.conditions is None
                or legacy_sensor_for_capability(intent.conditions.sensor) != supported_sensor
            ):
                actual_sensor = None if intent.conditions is None else intent.conditions.sensor
                errors.append(f"sensor is not supported by GBrain capability: {actual_sensor}")

            supported_actions = set(capability.get("supported_actions", []))
            for action in intent.actions:
                if action.method not in supported_actions:
                    errors.append(f"action method is not supported by GBrain capability: {action.method}")

        supported_devices = self._supported_device_aliases()
        for device in intent.target_devices:
            if _normalize_device(device) not in supported_devices:
                warnings.append(f"target device is not listed as V1 supported hardware: {device}")
        for action in intent.actions:
            if _normalize_device(action.device) not in supported_devices:
                warnings.append(f"action device is not listed as V1 supported hardware: {action.device}")

        required_templates = [template["id"] for template in self._templates_for_intent(intent.intent_type.value)]
        if not required_templates:
            warnings.append(f"no GBrain template found for intent_type: {intent.intent_type}")
        matched_skills = [skill["id"] for skill in self._skills_for_intent(intent.intent_type.value)]
        if not matched_skills:
            warnings.append(f"no runtime skill found for intent_type: {intent.intent_type}")

        return {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
            "sources": _source_paths(),
            "matched_templates": required_templates,
            "matched_skills": matched_skills,
        }

    def validate_mqtt_envelope(self, message: MqttEnvelope) -> JsonObject:
        errors: list[str] = []
        payload = message.model_dump(mode="json")
        for field in self.protocol_manifest.get("mqtt", {}).get("required_fields", []):
            if field not in payload:
                errors.append(f"missing MQTT field: {field}")

        if payload.get("type") == "deploy_script":
            if payload.get("timestamp") is None:
                errors.append("deploy_script requires timestamp")
            body = payload.get("payload")
            if not isinstance(body, dict):
                errors.append("deploy_script payload must be an object")
            else:
                required = self.protocol_manifest.get("mqtt", {}).get("deploy_script_payload_required_fields", [])
                for field in required:
                    if field not in body:
                        errors.append(f"missing deploy_script payload field: {field}")
                for field in ("script_id", "intent_type", "lua_code", "checksum", "target_device_id", "auth_signature"):
                    if not body.get(field):
                        errors.append(f"deploy_script payload field is empty: {field}")
                if body.get("intent_type") == "rule_program" and not isinstance(body.get("rule_program"), dict):
                    errors.append("rule_program deploy_script payload requires rule_program object")

        return {"ok": not errors, "errors": errors, "sources": ["mcp/resources/protocol_manifest.json"]}

    def validate_rule_program(self, program: RuleProgram) -> JsonObject:
        errors: list[str] = []
        warnings: list[str] = []

        trigger_capability = capability_for_sensor(program.trigger.capability or program.trigger.sensor)
        wire_sensor = legacy_sensor_for_capability(program.trigger.sensor)
        if trigger_capability not in known_trigger_capabilities() or wire_sensor != "AHT20.temp":
            errors.append(
                f"rule_program trigger capability is not supported by current wire protocol: "
                f"{program.trigger.capability or program.trigger.sensor}"
            )

        supported_devices = self._supported_device_aliases()
        for action in program.actions:
            if action.method != "servo_set":
                errors.append(f"rule_program action method is not supported: {action.method}")
            if _normalize_device(action.device) not in supported_devices:
                warnings.append(f"rule_program action device is not listed as V1 supported hardware: {action.device}")

        matched_capability = next(
            (
                capability.get("id", "")
                for capability in self.gbrain_capabilities.get("capabilities", [])
                if capability.get("intent_type") == "threshold_control"
                and legacy_sensor_for_capability(str(capability.get("supported_sensor") or "")) == "AHT20.temp"
            ),
            "",
        )
        matched_skills = [
            skill.get("id", "")
            for skill in self.gbrain_skills.get("skills", [])
            if skill.get("intent_type") == "threshold_control" and skill.get("status") == "available"
        ]
        if not matched_capability:
            warnings.append("no GBrain capability matched rule_program threshold baseline")
        if not matched_skills:
            warnings.append("no runtime skill matched rule_program threshold baseline")

        return {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
            "sources": _source_paths(),
            "matched_capability": matched_capability,
            "matched_skills": matched_skills,
            "platform_capability": trigger_capability,
            "wire_sensor": wire_sensor,
        }

    def _capability_for_intent(self, intent_type: str) -> JsonObject | None:
        for capability in self.gbrain_capabilities.get("capabilities", []):
            if capability.get("intent_type") == intent_type:
                return capability
        return None

    def _templates_for_intent(self, intent_type: str) -> list[JsonObject]:
        return [
            template
            for template in self.gbrain_templates.get("templates", [])
            if template.get("intent_type") == intent_type
        ]

    def _skills_for_intent(self, intent_type: str) -> list[JsonObject]:
        return [
            skill
            for skill in self.gbrain_skills.get("skills", [])
            if skill.get("intent_type") == intent_type and skill.get("status") == "available"
        ]

    def _supported_device_aliases(self) -> set[str]:
        aliases: set[str] = set()
        for device in self.hardware_manifest.get("v1_devices", []):
            name = str(device.get("name", ""))
            aliases.add(_normalize_device(name))
        for entity in self.gbrain_entities.get("entities", []):
            if entity.get("type") in {"sensor", "actuator"}:
                aliases.add(_normalize_device(str(entity.get("name", ""))))

        aliases.update({"AHT20", "SG90", "RGBLED", "RGB_LED", "BUZZER", "ACTIVEBUZZER", "HCSR04P", "HC_SR04P", "SCREEN", "LCD"})
        return aliases


@lru_cache
def get_project_knowledge() -> ProjectKnowledge:
    return ProjectKnowledge(
        project_manifest=_load_json("mcp/resources/project_manifest.json"),
        protocol_manifest=_load_json("mcp/resources/protocol_manifest.json"),
        hardware_manifest=_load_json("mcp/resources/hardware_manifest.json"),
        gbrain_capabilities=_load_json("mcp/resources/gbrain/capabilities.json"),
        gbrain_entities=_load_json("mcp/resources/gbrain/entities.json"),
        gbrain_skills=_load_json("mcp/resources/gbrain/skills.json"),
        gbrain_templates=_load_json("mcp/resources/gbrain/templates.json"),
    )


def _load_json(path: str) -> JsonObject:
    full_path = ROOT / path
    with full_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _source_paths() -> list[str]:
    return [
        "docs/知识管理方案.md",
        "docs/Agent工作规范.md",
        "docs/专用Agent架构方案.md",
        "mcp/resources/project_manifest.json",
        "mcp/resources/protocol_manifest.json",
        "mcp/resources/hardware_manifest.json",
        "mcp/resources/gbrain/capabilities.json",
        "mcp/resources/gbrain/entities.json",
        "mcp/resources/gbrain/skills.json",
        "mcp/resources/gbrain/templates.json",
    ]


def _normalize_device(value: str) -> str:
    return value.upper().replace(" ", "").replace("-", "_")
