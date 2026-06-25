from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from cloud.app.hardware_catalog import capability_for_action, capability_for_sensor, legacy_sensor_for_capability


def _normalize_loop_interval_ms(value: Any) -> int:
    if value is None or value == "" or isinstance(value, bool):
        return 1000
    try:
        interval = int(float(value))
    except (TypeError, ValueError):
        return 1000
    if interval <= 0:
        return 1000
    return max(100, min(interval, 60000))


def _normalize_device_name(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    normalized = value.strip().upper().replace("-", "").replace("_", "")
    aliases = {
        "AG90": "SG90",
        "SG90SERVO": "SG90",
        "SERVO": "SG90",
    }
    return aliases.get(normalized, value)


class IntentType(str, Enum):
    threshold_control = "threshold_control"
    screen_text = "screen_text"
    rule_program = "rule_program"


class Condition(BaseModel):
    sensor: str
    capability: str = "env.temperature"
    operator: Literal[">", ">=", "<", "<=", "=="]
    value: float

    @model_validator(mode="after")
    def normalize_sensor_capability(self) -> "Condition":
        self.capability = capability_for_sensor(self.capability or self.sensor)
        self.sensor = legacy_sensor_for_capability(self.capability)
        return self


class Action(BaseModel):
    device: str
    method: Literal["servo_set", "buzzer", "led_rgb", "screen_text"]
    params: dict[str, Any] = Field(default_factory=dict)


class Intent(BaseModel):
    intent_type: IntentType
    target_devices: list[str] = Field(default_factory=list)
    conditions: Condition | None = None
    actions: list[Action]
    loop_interval_ms: int = Field(default=1000, ge=100, le=60000)

    @field_validator("loop_interval_ms", mode="before")
    @classmethod
    def normalize_loop_interval_ms(cls, value: Any) -> int:
        return _normalize_loop_interval_ms(value)


class RuleProgramTrigger(BaseModel):
    sensor: str
    capability: str = "env.temperature"
    operator: Literal[">", ">=", "<", "<=", "=="]
    value: float

    @model_validator(mode="after")
    def normalize_sensor_capability(self) -> "RuleProgramTrigger":
        self.capability = capability_for_sensor(self.capability or self.sensor)
        self.sensor = legacy_sensor_for_capability(self.capability)
        return self


class RuleProgramAction(BaseModel):
    device: Literal["SG90"]
    method: Literal["servo_set"]
    capability: str = "motor.servo.angle"
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("device", mode="before")
    @classmethod
    def normalize_device(cls, value: Any) -> Any:
        return _normalize_device_name(value)

    @model_validator(mode="after")
    def validate_servo_params(self) -> "RuleProgramAction":
        self.capability = capability_for_action(self.device, self.method)
        angle = self.params.get("angle")
        duration_ms = self.params.get("duration_ms", 350)
        if isinstance(angle, bool) or not isinstance(angle, int | float) or int(angle) != angle:
            raise ValueError("SG90.servo_set requires integer params.angle")
        angle = int(angle)
        if not 0 <= angle <= 180:
            raise ValueError("SG90 angle must be between 0 and 180")
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int | float) or int(duration_ms) != duration_ms:
            raise ValueError("SG90.servo_set params.duration_ms must be an integer")
        duration_ms = int(duration_ms)
        if not 50 <= duration_ms <= 5000:
            raise ValueError("SG90.servo_set params.duration_ms must be between 50 and 5000")
        self.params = {**self.params, "angle": angle, "duration_ms": duration_ms}
        return self


class RuleProgram(BaseModel):
    program_id: str = Field(default="", max_length=48)
    version: Literal["rule_program.v1"] = "rule_program.v1"
    trigger: RuleProgramTrigger
    actions: list[RuleProgramAction] = Field(min_length=1, max_length=16)
    loop_interval_ms: int = Field(default=1000, ge=100, le=60000)
    cooldown_ms: int = Field(default=30000, ge=0, le=600000)
    description: str = Field(default="", max_length=160)

    @field_validator("loop_interval_ms", mode="before")
    @classmethod
    def normalize_loop_interval_ms(cls, value: Any) -> int:
        return _normalize_loop_interval_ms(value)


class ProgramInterpretRequest(BaseModel):
    text: str = Field(min_length=1)


class ProgramInterpretDeployRequest(BaseModel):
    request_id: str
    text: str = Field(min_length=1)
    device_id: str | None = None
    need_confirm: bool = True
    wait_for_ack: bool = True


class ProgramDeployRequest(BaseModel):
    request_id: str
    device_id: str | None = None
    program: RuleProgram
    need_confirm: bool = True
    wait_for_ack: bool = True


class AgentRoute(str, Enum):
    rule_program_v1 = "rule_program_v1"


class AgentKnowledgeSnapshot(BaseModel):
    device_id: str
    primary_sources: list[str] = Field(default_factory=list)
    supported_sensors: list[str] = Field(default_factory=list)
    supported_actuators: list[str] = Field(default_factory=list)
    matched_capabilities: list[str] = Field(default_factory=list)
    recent_request_ids: list[str] = Field(default_factory=list)
    latest_device_state: dict[str, Any] = Field(default_factory=dict)


class AgentPlanRequest(BaseModel):
    text: str = Field(min_length=1)
    device_id: str | None = None


class AgentDeployRequest(BaseModel):
    request_id: str
    text: str = Field(min_length=1)
    device_id: str | None = None
    need_confirm: bool = True
    wait_for_ack: bool = True


class HermesChatRequest(BaseModel):
    request_id: str
    text: str = Field(min_length=1)
    session_id: str | None = None
    device_id: str | None = None
    need_confirm: bool = True
    wait_for_ack: bool = True
    preview_only: bool = False


class AgentPlanResponse(BaseModel):
    request_id: str
    device_id: str
    route: AgentRoute
    source: str
    confidence: float
    notes: list[str] = Field(default_factory=list)
    knowledge_snapshot: AgentKnowledgeSnapshot
    program: RuleProgram
    graph_trace: list[str] = Field(default_factory=list)


class DeployScriptPayload(BaseModel):
    script_id: str
    intent_type: IntentType
    version: str = "v1"
    lua_code: str
    need_confirm: bool = True
    checksum: str
    target_device_id: str = ""
    auth_signature: str = ""
    rule_program: RuleProgram | None = None


class MqttEnvelope(BaseModel):
    request_id: str
    type: str
    payload: dict[str, Any]
    timestamp: int | None = None


class CompileRequest(BaseModel):
    intent: Intent


class InterpretRequest(BaseModel):
    text: str = Field(min_length=1)


class InterpretDeployRequest(BaseModel):
    request_id: str
    text: str = Field(min_length=1)
    device_id: str | None = None
    need_confirm: bool = True
    wait_for_ack: bool = True


class DeployRequest(BaseModel):
    request_id: str
    device_id: str | None = None
    intent: Intent
    need_confirm: bool = True
    wait_for_ack: bool = True


class DeployResponse(BaseModel):
    request_id: str
    device_id: str
    topic: str
    mqtt_enabled: bool
    message: MqttEnvelope
    lua_validation: dict[str, object]
    knowledge_validation: dict[str, object]
    mqtt_validation: dict[str, object]
    graph_trace: list[str] = Field(default_factory=list)
    ack_received: bool = False
    ack: dict[str, Any] | None = None


class AgentDeployResponse(DeployResponse):
    route: AgentRoute
    source: str
    confidence: float
    notes: list[str] = Field(default_factory=list)
    knowledge_snapshot: AgentKnowledgeSnapshot
