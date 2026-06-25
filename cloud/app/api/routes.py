from __future__ import annotations

import base64
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from cloud.app.agent_service.action_plan import interpret_text_to_rule_program
from cloud.app.agent_service.asr import transcribe_audio
from cloud.app.agent_service.hermes_official import chat_with_hermes_official
from cloud.app.agent_service.language import interpret_text_to_intent
from cloud.app.agent_service.orchestrator import AgentOrchestrator
from cloud.app.agent_service.runtime_agent import HermesRA8P1Agent
from cloud.app.config import Settings, get_settings
from cloud.app.device_state.store import device_state_store
from cloud.app.hardware_catalog import build_platform_hardware_registry, catalog_status
from cloud.app.knowledge_base import get_project_knowledge
from cloud.app.log_service.store import PersistentLogStore
from cloud.app.models import (
    AgentDeployRequest,
    AgentPlanRequest,
    CompileRequest,
    DeployRequest,
    InterpretDeployRequest,
    InterpretRequest,
    HermesChatRequest,
    MqttEnvelope,
    ProgramDeployRequest,
    ProgramInterpretRequest,
    ProgramInterpretDeployRequest,
)
from cloud.app.mqtt_service.client import MqttPublisher
from cloud.app.security import build_script_signature
from cloud.app.server_context import latest_aht20_observation
from cloud.app.template_compiler.compiler import build_deploy_payload, compile_intent_to_lua


router = APIRouter()


def get_orchestrator(settings: Settings = Depends(get_settings)) -> AgentOrchestrator:
    return AgentOrchestrator(settings, MqttPublisher(settings))


def get_log_store(settings: Settings = Depends(get_settings)) -> PersistentLogStore:
    return PersistentLogStore(settings.log_db_path)


def get_runtime_agent(settings: Settings = Depends(get_settings)) -> HermesRA8P1Agent:
    return HermesRA8P1Agent(settings, PersistentLogStore(settings.log_db_path))


def require_api_token(
    settings: Settings = Depends(get_settings),
    x_api_token: str | None = Header(default=None, alias="X-API-Token"),
) -> None:
    if not settings.api_token:
        return
    if x_api_token == settings.api_token:
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="missing or invalid API token",
    )


def parse_interpret_request(request: InterpretRequest, settings: Settings | None = None):
    try:
        return interpret_text_to_intent(request.text, settings)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


def parse_program_request(request: ProgramInterpretRequest, settings: Settings | None = None):
    try:
        return interpret_text_to_rule_program(request.text, settings)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


def parse_audio_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


def parse_deploy_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


def _message_payload(message: object) -> dict[str, object]:
    if not isinstance(message, dict):
        return {}
    payload = message.get("payload")
    return payload if isinstance(payload, dict) else {}


def _payload_ports(payload: dict[str, object]) -> list[dict[str, object]]:
    ports = payload.get("ports")
    return [item for item in ports if isinstance(item, dict)] if isinstance(ports, list) else []


def _module_payload(port: dict[str, object]) -> dict[str, object]:
    module = port.get("module")
    return module if isinstance(module, dict) else {}


def _find_port(payload: dict[str, object], port_id: str) -> dict[str, object]:
    for port in _payload_ports(payload):
        if str(port.get("port_id") or "").strip() == port_id:
            return port
    return {}


def _port_device_count(port: dict[str, object]) -> int:
    module = _module_payload(port)
    module_type = str(module.get("module_type") or "").strip().lower()
    return 0 if module_type in {"", "none", "reserved"} else 1


def _port_as_device(port: dict[str, object]) -> dict[str, object]:
    module = _module_payload(port)
    capability_items = port.get("capabilities")
    capability_items = capability_items if isinstance(capability_items, list) else []
    return {
        "address": module.get("address") or None,
        "type": module.get("module_type") or module.get("module_id") or "unknown",
        "status": port.get("status") or "unknown",
        "capabilities": [
            item.get("id")
            for item in capability_items
            if isinstance(item, dict) and item.get("id")
        ],
        "driver": module.get("driver") or "",
        "confidence": module.get("confidence") or "unknown",
    }


def _delivery_stage_label(stage: str) -> str:
    return {
        "answered": "仅回答",
        "planned": "已规划",
        "published": "已下发",
        "acked": "已 ACK",
        "executed": "已执行",
        "blocked": "被硬件条件阻塞",
        "failed": "下发失败",
    }.get(stage, stage)


def _device_diagnostics(snapshot: dict[str, object]) -> dict[str, object]:
    last_status = snapshot.get("last_status")
    last_telemetry = snapshot.get("last_telemetry")
    status_payload = _message_payload(last_status)
    telemetry_payload = _message_payload(last_telemetry)
    observation = latest_aht20_observation(last_status, last_telemetry)
    observed_aht20 = observation.get("payload")
    observed_aht20 = observed_aht20 if isinstance(observed_aht20, dict) else {}
    status_aht20 = status_payload.get("aht20")
    telemetry_aht20 = telemetry_payload.get("aht20")
    status_i2c = status_payload.get("i2c")
    telemetry_i2c = telemetry_payload.get("i2c")
    status_ports = _payload_ports(status_payload)
    telemetry_ports = _payload_ports(telemetry_payload)
    i2c_port = _find_port(status_payload, "i2c.s1") or _find_port(telemetry_payload, "i2c.s1")
    uart_port = _find_port(status_payload, "uart.bridge") or _find_port(telemetry_payload, "uart.bridge")
    aht20 = observed_aht20 or (status_aht20 if isinstance(status_aht20, dict) else {})
    i2c = status_i2c if isinstance(status_i2c, dict) else {}
    if not aht20 and isinstance(telemetry_aht20, dict):
        aht20 = telemetry_aht20
    if not i2c and isinstance(telemetry_i2c, dict):
        i2c = telemetry_i2c
    if not i2c and i2c_port:
        i2c = {
            "bus": "s1",
            "diag": i2c_port.get("diag"),
            "count": _port_device_count(i2c_port),
            "devices": [_port_as_device(i2c_port)] if _port_device_count(i2c_port) else [],
        }
    last_execution = status_payload.get("last_execution")
    last_execution = last_execution if isinstance(last_execution, dict) else {}
    hardware_list = status_payload.get("hardware_list")
    hardware_list = hardware_list if isinstance(hardware_list, list) else []
    if not hardware_list:
        hardware_list = []
        for port in status_ports or telemetry_ports:
            if _port_device_count(port):
                hardware_list.append(_port_as_device(port))
    hardware_registry = build_platform_hardware_registry(snapshot)
    i2c_devices = i2c.get("devices")
    i2c_devices = i2c_devices if isinstance(i2c_devices, list) else []
    i2c_count = i2c.get("count") if i2c.get("count") is not None else len(i2c_devices)
    i2c_count = int(i2c_count) if isinstance(i2c_count, (int, float)) else len(i2c_devices)
    if i2c_port and str(i2c_port.get("diag") or "").strip() == "write addr nack":
        i2c_count = 0
        i2c_devices = []
    i2c_interpretation = "unknown"
    i2c_next_checks: list[str] = []

    blockers: list[dict[str, object]] = []
    aht20_status = aht20.get("status")
    aht20_diag = str(aht20.get("diag") or "").strip()
    i2c_diag = str(i2c.get("diag") or "").strip()
    if i2c_diag == "sda stuck":
        i2c_interpretation = "bus_blocked"
        i2c_next_checks = [
            "Check whether SDA is held low by wiring or a failed module on Bus S1.",
            "Power-cycle the external I2C module and re-run the scan.",
        ]
    elif i2c_count == 0 and aht20_diag == "write addr nack":
        i2c_interpretation = "no_device_ack"
        i2c_next_checks = [
            "Check AHT20 VCC and GND first.",
            "Check AHT20 SCL -> P306 and SDA -> P309 on Bus S1.",
            "Confirm the module is on the dedicated AHT20 bus, not the FT6336 touch bus.",
        ]
    elif i2c_count > 0:
        i2c_interpretation = "devices_present"
    if aht20_status == "offline":
        aht20_detail = f"AHT20 offline: {aht20_diag}" if aht20_diag else "AHT20 offline; exact RA8P1 diag is not yet present in cloud state"
        if i2c_interpretation == "no_device_ack":
            aht20_detail = "AHT20 offline: write addr nack; Bus S1 scan completed but no device ACKed, so check AHT20 power and wiring on P309/P306."
        blockers.append(
            {
                "component": "AHT20",
                "severity": "blocking",
                "detail": aht20_detail,
            }
        )
    if last_execution.get("state") == "ARMED" and last_execution.get("sample") is False:
        blockers.append(
            {
                "component": "rule_program",
                "severity": "blocking",
                "detail": "temperature rule is armed but cannot trigger without a valid AHT20 sample",
            }
        )
    if i2c_diag == "sda stuck":
        blockers.append(
            {
                "component": "I2C_BUS_S1",
                "severity": "blocking",
                "detail": "I2C bus S1 is stuck low; scan/identify cannot progress until hardware recovers",
            }
        )

    return {
        "aht20": {
            "status": aht20_status or "unknown",
            "crc_ok": aht20.get("crc_ok"),
            "diag": aht20_diag or None,
        },
        "i2c": {
            "bus": i2c.get("bus") or "s1",
            "diag": i2c_diag or None,
            "count": i2c_count,
            "devices": i2c_devices,
            "interpretation": i2c_interpretation,
            "next_checks": i2c_next_checks,
        },
        "hardware_capabilities": hardware_list,
        "hardware_registry": hardware_registry,
        "platform_capabilities": hardware_registry.get("capabilities", []),
        "uart": status_payload.get("uart") or (uart_port.get("status") if uart_port else "unknown") or "unknown",
        "script_state": status_payload.get("script_state") or "unknown",
        "last_execution": last_execution,
        "blocking_conditions": blockers,
    }


def _find_request_event(snapshot: dict[str, object], request_id: str, message_type: str) -> dict[str, object] | None:
    if not request_id:
        return None
    events = snapshot.get("events")
    if not isinstance(events, list):
        return None
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        message = event.get("message")
        if (
            isinstance(message, dict)
            and message.get("type") == message_type
            and message.get("request_id") == request_id
        ):
            return message
    return None


def _await_execution_window(response: dict[str, object], *, wait_for_ack: bool, timeout_sec: float = 1.2) -> None:
    if not wait_for_ack:
        return
    device_id = str(response.get("device_id") or "")
    request_id = str(response.get("request_id") or "")
    if not device_id or not request_id:
        return
    device_state_store.wait_for_request_event(
        device_id=device_id,
        request_id=request_id,
        message_type="execution_state",
        timeout_sec=timeout_sec,
    )


def _finalize_web_deploy_view(
    response: dict[str, object],
    *,
    wait_for_ack: bool,
    intent_source: str | None = None,
    intent_confidence: float | None = None,
) -> dict[str, object]:
    _await_execution_window(response, wait_for_ack=wait_for_ack)
    return _build_web_deploy_view(
        response,
        intent_source=intent_source,
        intent_confidence=intent_confidence,
    )


def _build_web_deploy_view(
    response: dict[str, object],
    *,
    intent_source: str | None = None,
    intent_confidence: float | None = None,
) -> dict[str, object]:
    request_id = str(response.get("request_id") or "")
    device_id = str(response.get("device_id") or "")
    snapshot = device_state_store.snapshot(device_id) if device_id else {}
    last_status = snapshot.get("last_status")
    last_event = snapshot.get("last_event")
    last_ack = snapshot.get("last_deploy_ack")
    status_payload = _message_payload(last_status)
    event_payload = _message_payload(last_event)
    last_execution = status_payload.get("last_execution")
    last_execution = last_execution if isinstance(last_execution, dict) else {}
    execution_event = _find_request_event(snapshot, request_id, "execution_state")
    execution_event_payload = _message_payload(execution_event)
    aht20 = status_payload.get("aht20")
    aht20 = aht20 if isinstance(aht20, dict) else {}
    diagnostics = _device_diagnostics(snapshot)
    aht20_diag = str(aht20.get("diag") or "").strip()
    raw_message = response.get("message")
    mqtt_message = raw_message if isinstance(raw_message, dict) else None
    message_payload = _message_payload(mqtt_message)
    message_rule_program = message_payload.get("rule_program")
    message_rule_program = message_rule_program if isinstance(message_rule_program, dict) else {}
    trigger = message_rule_program.get("trigger")
    trigger = trigger if isinstance(trigger, dict) else {}
    current_intent_type = message_payload.get("intent_type") or status_payload.get("last_intent_type")
    last_event_type = last_event.get("type") if isinstance(last_event, dict) else None
    last_event_request_id = last_event.get("request_id") if isinstance(last_event, dict) else None
    last_ack_request_id = last_ack.get("request_id") if isinstance(last_ack, dict) else None
    last_request_matches = request_id and status_payload.get("last_request_id") == request_id
    last_event_matches = request_id and last_event_request_id == request_id
    mqtt_enabled = response.get("mqtt_enabled")
    if "published" in response:
        published = bool(response.get("published"))
    else:
        published = bool(mqtt_enabled is not False and mqtt_message is not None)
    ack_received = bool(response.get("ack_received")) or (request_id != "" and last_ack_request_id == request_id)
    script_state = status_payload.get("script_state") if last_request_matches else None
    execution_state = None
    if execution_event_payload:
        execution_state = execution_event_payload.get("state")
    if last_request_matches:
        execution_state = last_execution.get("state") or script_state
    if execution_state is None and last_event_matches:
        execution_state = event_payload.get("state")
    execution_has_state = execution_state is not None
    aht20_offline = aht20.get("status") == "offline"
    requires_aht20_trigger = trigger.get("sensor") == "AHT20.temp" or status_payload.get("last_intent_type") == "rule_program"
    one_shot_screen_text_done = bool(
        ack_received
        and last_request_matches
        and current_intent_type == "screen_text"
        and execution_state in {"", None, "IDLE", "ACKED"}
    )

    publish_layer = {
        "ok": published,
        "topic": response.get("topic") or "",
        "request_id": request_id,
    }
    ack_layer = {
        "received": ack_received,
        "request_id": request_id,
        "detail": "ACK 已收到" if ack_received else "等待 ACK",
    }
    execution_layer = {
        "has_executed": last_request_matches or last_event_matches,
        "state": execution_state or "",
        "detail": "",
    }

    delivery_stage = "failed"
    if (
        execution_state in {"TRIGGERED", "DONE"}
        or execution_event_payload
        or (last_event_matches and last_event_type == "execution_state")
        or one_shot_screen_text_done
    ):
        delivery_stage = "executed"
        status = "success"
        execution_layer["has_executed"] = True
        execution_layer["detail"] = f"设备状态 {execution_state or execution_event_payload.get('state') or 'EXECUTED'}"
        message = "已下发并进入设备执行链路"
    elif aht20_offline and requires_aht20_trigger and (script_state in {"ACKED", "ARMED", "PENDING"} or execution_state == "ARMED"):
        delivery_stage = "blocked"
        status = "executing"
        execution_layer["has_executed"] = True
        execution_layer["state"] = execution_state or script_state or "ARMED"
        if aht20_diag:
            execution_layer["detail"] = f"AHT20 当前离线（诊断：{aht20_diag}），规则已 armed 但无法触发"
            message = f"已下发并收到设备回执，但 AHT20 离线（{aht20_diag}），规则暂未触发"
        else:
            execution_layer["detail"] = "AHT20 当前离线，规则已 armed 但无法触发"
            message = "已下发并收到设备回执，但 AHT20 离线，规则暂未触发"
    elif ack_received:
        delivery_stage = "acked"
        status = "executing"
        execution_layer["detail"] = f"设备状态 {execution_state or script_state or 'ACKED'}"
        message = "已下发并收到 ACK，等待设备进一步执行"
    elif mqtt_enabled is False and mqtt_message is not None:
        delivery_stage = "planned"
        status = "planned"
        execution_layer["detail"] = "MQTT 当前关闭，未发布到真实设备"
        message = "已生成设备下发消息，但 MQTT 当前关闭，未发布到真实设备"
    elif published:
        delivery_stage = "published"
        status = "partial"
        execution_layer["detail"] = f"设备状态 {execution_state or script_state or 'PENDING'}"
        message = "已发布到 MQTT，等待设备 ACK / 状态回流"
    else:
        delivery_stage = "failed"
        status = "failed"
        execution_layer["detail"] = "未检测到设备侧状态推进"
        message = "未能将请求发布到设备链路"

    response["intent_source"] = intent_source or response.get("intent_source") or response.get("program_source")
    response["intent_confidence"] = (
        intent_confidence
        if intent_confidence is not None
        else response.get("intent_confidence") or response.get("program_confidence")
    )
    response["status"] = status
    response["delivery_stage"] = delivery_stage
    response["delivery_stage_label"] = _delivery_stage_label(delivery_stage)
    response["publish_layer"] = publish_layer
    response["ack_layer"] = ack_layer
    response["execution_layer"] = execution_layer
    response["latest_device_state"] = snapshot
    response["device_diagnostics"] = diagnostics
    response["mqtt_message"] = mqtt_message
    response["message"] = message
    return response


def mock_transcript_from_headers(value: str | None, encoded: str | None) -> str:
    if encoded:
        try:
            return base64.b64decode(encoded).decode("utf-8")
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid X-Mock-Transcript-Base64 header",
            ) from exc
    return value or ""


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    return {
        "ok": True,
        "app_env": settings.app_env,
        "device_id": settings.device_id,
        "mqtt_enabled": settings.mqtt_enabled,
        "knowledge": {
            "llm_wiki": True,
            "gbrain": True,
            "runtime_validation": True,
        },
    }


@router.get("/agent/knowledge/status")
def knowledge_status(
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    return get_project_knowledge().status()


@router.get("/agent/skills")
def agent_skills(
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    return get_project_knowledge().skills()


@router.post("/agent/speech/transcribe")
async def transcribe_speech(
    request: Request,
    filename: str = Query(default="audio.wav"),
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(require_api_token),
    x_mock_transcript: str | None = Header(default=None, alias="X-Mock-Transcript"),
    x_mock_transcript_base64: str | None = Header(default=None, alias="X-Mock-Transcript-Base64"),
) -> dict[str, object]:
    try:
        transcription = transcribe_audio(
            settings=settings,
            audio=await request.body(),
            filename=filename,
            content_type=request.headers.get("content-type", ""),
            mock_transcript=mock_transcript_from_headers(x_mock_transcript, x_mock_transcript_base64),
        )
    except Exception as exc:
        raise parse_audio_error(exc) from exc
    return {
        "ok": True,
        "transcript": transcription.text,
        "asr_provider": transcription.provider,
        "asr_model": transcription.model,
    }


@router.post("/agent/speech/interpret")
async def interpret_speech(
    request: Request,
    filename: str = Query(default="audio.wav"),
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(require_api_token),
    x_mock_transcript: str | None = Header(default=None, alias="X-Mock-Transcript"),
    x_mock_transcript_base64: str | None = Header(default=None, alias="X-Mock-Transcript-Base64"),
) -> dict[str, object]:
    try:
        transcription = transcribe_audio(
            settings=settings,
            audio=await request.body(),
            filename=filename,
            content_type=request.headers.get("content-type", ""),
            mock_transcript=mock_transcript_from_headers(x_mock_transcript, x_mock_transcript_base64),
        )
        parsed = interpret_text_to_intent(transcription.text, settings)
    except Exception as exc:
        raise parse_audio_error(exc) from exc
    return {
        "ok": True,
        "transcript": transcription.text,
        "asr_provider": transcription.provider,
        "asr_model": transcription.model,
        "intent": parsed.intent.model_dump(mode="json"),
        "intent_source": parsed.source,
        "intent_confidence": parsed.confidence,
    }


@router.post("/agent/speech/deploy")
async def speech_deploy(
    request: Request,
    request_id: str = Query(),
    filename: str = Query(default="audio.wav"),
    device_id: str | None = Query(default=None),
    need_confirm: bool = Query(default=True),
    wait_for_ack: bool = Query(default=True),
    settings: Settings = Depends(get_settings),
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    _auth: None = Depends(require_api_token),
    x_mock_transcript: str | None = Header(default=None, alias="X-Mock-Transcript"),
    x_mock_transcript_base64: str | None = Header(default=None, alias="X-Mock-Transcript-Base64"),
) -> dict[str, object]:
    try:
        transcription = transcribe_audio(
            settings=settings,
            audio=await request.body(),
            filename=filename,
            content_type=request.headers.get("content-type", ""),
            mock_transcript=mock_transcript_from_headers(x_mock_transcript, x_mock_transcript_base64),
        )
        parsed = interpret_text_to_intent(transcription.text, settings)
    except Exception as exc:
        raise parse_audio_error(exc) from exc
    try:
        response = orchestrator.compile_and_deploy(
            DeployRequest(
                request_id=request_id,
                device_id=device_id,
                intent=parsed.intent,
                need_confirm=need_confirm,
                wait_for_ack=wait_for_ack,
            )
        )
    except Exception as exc:
        raise parse_deploy_error(exc) from exc
    return {
        "ok": True,
        "transcript": transcription.text,
        "asr_provider": transcription.provider,
        "asr_model": transcription.model,
        "intent_source": parsed.source,
        "intent_confidence": parsed.confidence,
        **_finalize_web_deploy_view(
            response.model_dump(mode="json"),
            wait_for_ack=wait_for_ack,
            intent_source=parsed.source,
            intent_confidence=parsed.confidence,
        ),
    }


@router.post("/agent/compile")
def compile_intent(
    request: CompileRequest,
    settings: Settings | None = Depends(get_settings),
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    resolved_settings = settings or get_settings()
    knowledge = get_project_knowledge()
    knowledge_validation = knowledge.validate_intent(request.intent)
    if not knowledge_validation["ok"]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=knowledge_validation["errors"])
    lua_code, validation = compile_intent_to_lua(request.intent)
    timestamp = int(time.time())
    payload = build_deploy_payload(request.intent, lua_code, need_confirm=True)
    payload.target_device_id = resolved_settings.device_id
    payload.auth_signature = build_script_signature(
        resolved_settings.mqtt_script_secret or "preview-secret",
        "compile_preview",
        payload.script_id,
        payload.intent_type.value,
        payload.checksum,
        timestamp,
        resolved_settings.device_id,
    )
    message = {
        "request_id": "compile_preview",
        "type": "deploy_script",
        "timestamp": timestamp,
        "payload": payload.model_dump(mode="json"),
    }
    return {
        "ok": True,
        "lua_code": lua_code,
        "payload": payload.model_dump(mode="json"),
        "lua_validation": validation,
        "knowledge_validation": knowledge_validation,
        "mqtt_validation": knowledge.validate_mqtt_envelope(
            MqttEnvelope.model_validate(message)
        ),
    }


@router.post("/agent/interpret")
def interpret_text(
    request: InterpretRequest,
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    parsed = parse_interpret_request(request, settings)
    return {
        "ok": True,
        "intent": parsed.intent.model_dump(mode="json"),
        "source": parsed.source,
        "confidence": parsed.confidence,
        "notes": parsed.notes,
    }


@router.post("/agent/program/interpret")
def interpret_program(
    request: ProgramInterpretRequest,
    settings: Settings | None = Depends(get_settings),
    runtime_agent: HermesRA8P1Agent | None = Depends(get_runtime_agent),
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    resolved_settings = settings or get_settings()
    if resolved_settings.llm_provider == "hermes_official":
        device_id = resolved_settings.device_id
        device_snapshot = device_state_store.snapshot(device_id)
        diagnostics = _device_diagnostics(device_snapshot)
        chat_source = f"hermes_official:{resolved_settings.hermes_official_model}+chat"
        try:
            result = chat_with_hermes_official(
                request.text,
                resolved_settings,
                session_id=None,
                device_context={
                    "device_id": device_id,
                    "latest_state": device_snapshot,
                    "diagnostics": diagnostics,
                },
            )
        except Exception as exc:
            raise parse_deploy_error(exc) from exc

        response: dict[str, object] = {
            "ok": True,
            "request_id": f"hermes_preview_{int(time.time() * 1000)}",
            "source": chat_source,
            "confidence": 0.9,
            "notes": ["compat_preview_via_hermes_chat"],
            "assistant_message": result.assistant_message,
            "session_id": result.session_id,
            "action_kind": result.action_kind,
            "latest_device_state": device_snapshot,
            "device_diagnostics": diagnostics,
        }
        if result.program is not None:
            response["route"] = "rule_program_v1"
            response["program"] = result.program.model_dump(mode="json")
        if result.intent is not None:
            response["intent"] = result.intent.model_dump(mode="json")
        return response

    resolved_runtime_agent = runtime_agent or HermesRA8P1Agent(
        resolved_settings,
        PersistentLogStore(resolved_settings.log_db_path),
    )
    try:
        planned = resolved_runtime_agent.plan(
            AgentPlanRequest(
                text=request.text,
                device_id=resolved_settings.device_id,
            )
        )
    except Exception as exc:
        raise parse_deploy_error(exc) from exc
    return {
        "ok": True,
        "request_id": planned.request_id,
        "route": planned.route.value,
        "program": planned.program.model_dump(mode="json"),
        "source": planned.source,
        "confidence": planned.confidence,
        "notes": planned.notes,
        "knowledge_snapshot": planned.knowledge_snapshot.model_dump(mode="json"),
        "graph_trace": planned.graph_trace,
    }


@router.post("/agent/program/interpret/deploy")
def interpret_program_and_deploy(
    request: ProgramInterpretDeployRequest,
    settings: Settings = Depends(get_settings),
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    runtime_agent: HermesRA8P1Agent | None = Depends(get_runtime_agent),
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    if settings.llm_provider == "hermes_official":
        return hermes_chat(
            HermesChatRequest(
                request_id=request.request_id,
                text=request.text,
                session_id=None,
                device_id=request.device_id,
                need_confirm=request.need_confirm,
                wait_for_ack=request.wait_for_ack,
                preview_only=False,
            ),
            settings,
            orchestrator,
        )

    resolved_runtime_agent = runtime_agent or HermesRA8P1Agent(
        settings,
        PersistentLogStore(settings.log_db_path),
    )
    parsed = None
    try:
        parsed = parse_interpret_request(InterpretRequest(text=request.text), settings)
    except HTTPException:
        parsed = None
    parsed_intent_type = None
    if parsed is not None:
        parsed_intent_type = getattr(parsed.intent.intent_type, "value", parsed.intent.intent_type)
    if parsed_intent_type == "screen_text":
        try:
            response = orchestrator.compile_and_deploy(
                DeployRequest(
                    request_id=request.request_id,
                    device_id=request.device_id,
                    intent=parsed.intent,
                    need_confirm=request.need_confirm,
                    wait_for_ack=request.wait_for_ack,
                )
            )
        except Exception as exc:
            raise parse_deploy_error(exc) from exc
        return {
            "ok": True,
            "intent_source": parsed.source,
            "intent_confidence": parsed.confidence,
            **_finalize_web_deploy_view(
                response.model_dump(mode="json"),
                wait_for_ack=request.wait_for_ack,
                intent_source=parsed.source,
                intent_confidence=parsed.confidence,
            ),
        }
    try:
        response = resolved_runtime_agent.deploy(
            AgentDeployRequest(
                request_id=request.request_id,
                text=request.text,
                device_id=request.device_id,
                need_confirm=request.need_confirm,
                wait_for_ack=request.wait_for_ack,
            ),
            orchestrator,
        )
    except Exception as exc:
        raise parse_deploy_error(exc) from exc
    payload = {
        "ok": True,
        "program_source": response.source,
        "program_confidence": response.confidence,
        "agent_route": response.route.value,
        "agent_notes": response.notes,
        "knowledge_snapshot": response.knowledge_snapshot.model_dump(mode="json"),
        **response.model_dump(mode="json"),
    }
    return _finalize_web_deploy_view(
        payload,
        wait_for_ack=request.wait_for_ack,
        intent_source=response.source,
        intent_confidence=response.confidence,
    )


@router.post("/agent/program/deploy")
def deploy_program(
    request: ProgramDeployRequest,
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    try:
        response = orchestrator.deploy_rule_program(request)
    except Exception as exc:
        raise parse_deploy_error(exc) from exc
    return _finalize_web_deploy_view(
        {"ok": True, **response.model_dump(mode="json")},
        wait_for_ack=request.wait_for_ack,
    )


@router.get("/agent/runtime/status")
def agent_runtime_status(
    runtime_agent: HermesRA8P1Agent = Depends(get_runtime_agent),
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    return runtime_agent.runtime_status()


@router.post("/agent/runtime/plan")
def agent_runtime_plan(
    request: AgentPlanRequest,
    runtime_agent: HermesRA8P1Agent = Depends(get_runtime_agent),
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    try:
        planned = runtime_agent.plan(request)
    except Exception as exc:
        raise parse_deploy_error(exc) from exc
    return {"ok": True, **planned.model_dump(mode="json")}


@router.post("/agent/runtime/deploy")
def agent_runtime_deploy(
    request: AgentDeployRequest,
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    runtime_agent: HermesRA8P1Agent = Depends(get_runtime_agent),
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    try:
        response = runtime_agent.deploy(request, orchestrator)
    except Exception as exc:
        raise parse_deploy_error(exc) from exc
    return _finalize_web_deploy_view(
        {"ok": True, **response.model_dump(mode="json")},
        wait_for_ack=request.wait_for_ack,
        intent_source=response.source,
        intent_confidence=response.confidence,
    )


@router.post("/agent/interpret/deploy")
def interpret_and_deploy(
    request: InterpretDeployRequest,
    settings: Settings = Depends(get_settings),
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    runtime_agent: HermesRA8P1Agent | None = Depends(get_runtime_agent),
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    if settings.llm_provider == "hermes_official":
        return hermes_chat(
            HermesChatRequest(
                request_id=request.request_id,
                text=request.text,
                session_id=None,
                device_id=request.device_id,
                need_confirm=request.need_confirm,
                wait_for_ack=request.wait_for_ack,
                preview_only=False,
            ),
            settings,
            orchestrator,
        )

    resolved_runtime_agent = runtime_agent or HermesRA8P1Agent(
        settings,
        PersistentLogStore(settings.log_db_path),
    )

    parsed = parse_interpret_request(InterpretRequest(text=request.text), settings)
    parsed_intent_type = getattr(parsed.intent.intent_type, "value", parsed.intent.intent_type)
    if parsed_intent_type == "screen_text":
        try:
            response = orchestrator.compile_and_deploy(
                DeployRequest(
                    request_id=request.request_id,
                    device_id=request.device_id,
                    intent=parsed.intent,
                    need_confirm=request.need_confirm,
                    wait_for_ack=request.wait_for_ack,
                )
            )
        except Exception as exc:
            raise parse_deploy_error(exc) from exc
        return {
            "ok": True,
            "intent_source": parsed.source,
            "intent_confidence": parsed.confidence,
            **_finalize_web_deploy_view(
                response.model_dump(mode="json"),
                wait_for_ack=request.wait_for_ack,
                intent_source=parsed.source,
                intent_confidence=parsed.confidence,
            ),
        }

    # Compatibility path for older web bundles still posting to /agent/interpret/deploy.
    # Prefer the newer specialized runtime-agent -> rule_program chain first.
    try:
        response = resolved_runtime_agent.deploy(
            AgentDeployRequest(
                request_id=request.request_id,
                text=request.text,
                device_id=request.device_id,
                need_confirm=request.need_confirm,
                wait_for_ack=request.wait_for_ack,
            ),
            orchestrator,
        )
        return {
            "ok": True,
            "program_source": response.source,
            "program_confidence": response.confidence,
            "agent_route": response.route.value,
            "agent_notes": response.notes,
            "knowledge_snapshot": response.knowledge_snapshot.model_dump(mode="json"),
            **_finalize_web_deploy_view(
                response.model_dump(mode="json"),
                wait_for_ack=request.wait_for_ack,
                intent_source=response.source,
                intent_confidence=response.confidence,
            ),
        }
    except HTTPException:
        raise
    except Exception:
        # Fall back to the older intent-based path for non-rule-program requests.
        pass

    try:
        response = orchestrator.compile_and_deploy(
            DeployRequest(
                request_id=request.request_id,
                device_id=request.device_id,
                intent=parsed.intent,
                need_confirm=request.need_confirm,
                wait_for_ack=request.wait_for_ack,
            )
        )
    except Exception as exc:
        raise parse_deploy_error(exc) from exc
    return {
        "ok": True,
        "intent_source": parsed.source,
        "intent_confidence": parsed.confidence,
        **_finalize_web_deploy_view(
            response.model_dump(mode="json"),
            wait_for_ack=request.wait_for_ack,
            intent_source=parsed.source,
            intent_confidence=parsed.confidence,
        ),
    }


@router.post("/agent/hermes/chat")
def hermes_chat(
    request: HermesChatRequest,
    settings: Settings = Depends(get_settings),
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    device_id = request.device_id or settings.device_id
    device_snapshot = device_state_store.snapshot(device_id)
    diagnostics = _device_diagnostics(device_snapshot)
    chat_source = f"hermes_official:{settings.hermes_official_model}+chat"
    try:
        result = chat_with_hermes_official(
            request.text,
            settings,
            session_id=request.session_id,
            device_context={
                "device_id": device_id,
                "latest_state": device_snapshot,
                "diagnostics": diagnostics,
            },
        )
    except Exception as exc:
        raise parse_deploy_error(exc) from exc

    preview: dict[str, object] = {}
    if result.intent is not None:
        preview["intent"] = result.intent.model_dump(mode="json")
    if result.program is not None:
        preview["program"] = result.program.model_dump(mode="json")

    if request.preview_only or result.action_kind == "none":
        delivery_stage = "answered" if result.action_kind == "none" else "planned"
        return {
            "ok": True,
            "status": delivery_stage,
            "delivery_stage": delivery_stage,
            "delivery_stage_label": _delivery_stage_label(delivery_stage),
            "assistant_message": result.assistant_message,
            "session_id": result.session_id,
            "action_kind": result.action_kind,
            "intent_source": chat_source,
            "intent_confidence": 0.9,
            "preview": preview,
            "latest_device_state": device_snapshot,
            "device_diagnostics": diagnostics,
            "message": result.assistant_message,
        }

    try:
        if result.program is not None:
            deploy_response = orchestrator.deploy_rule_program(
                ProgramDeployRequest(
                    request_id=request.request_id,
                    device_id=device_id,
                    program=result.program,
                    need_confirm=request.need_confirm,
                    wait_for_ack=request.wait_for_ack,
                )
            )
        elif result.intent is not None:
            deploy_response = orchestrator.compile_and_deploy(
                DeployRequest(
                    request_id=request.request_id,
                    device_id=device_id,
                    intent=result.intent,
                    need_confirm=request.need_confirm,
                    wait_for_ack=request.wait_for_ack,
                )
            )
        else:
            raise ValueError("Hermes returned no deployable action")
    except Exception as exc:
        raise parse_deploy_error(exc) from exc

    response_payload = {
        "ok": True,
        "assistant_message": result.assistant_message,
        "session_id": result.session_id,
        "action_kind": result.action_kind,
        "preview": preview,
        **deploy_response.model_dump(mode="json"),
    }
    return _finalize_web_deploy_view(
        response_payload,
        wait_for_ack=request.wait_for_ack,
        intent_source=chat_source,
        intent_confidence=0.9,
    )


@router.post("/agent/deploy")
def deploy_intent(
    request: DeployRequest,
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    try:
        response = orchestrator.compile_and_deploy(request)
    except Exception as exc:
        raise parse_deploy_error(exc) from exc
    return _finalize_web_deploy_view(
        {"ok": True, **response.model_dump(mode="json")},
        wait_for_ack=request.wait_for_ack,
    )


@router.get("/hardware/catalog")
def hardware_catalog(
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    return {"ok": True, "catalog": catalog_status()}


@router.get("/devices/{device_id}/state")
def device_state(
    device_id: str,
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    snapshot = device_state_store.snapshot(device_id)
    return {"ok": True, "state": snapshot, "diagnostics": _device_diagnostics(snapshot)}


@router.get("/devices/{device_id}/diagnostics")
def device_diagnostics(
    device_id: str,
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    snapshot = device_state_store.snapshot(device_id)
    return {"ok": True, "device_id": device_id, "diagnostics": _device_diagnostics(snapshot)}



@router.get("/devices/{device_id}/events")
def device_events(
    device_id: str,
    limit: int = 20,
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    bounded_limit = max(1, min(limit, 100))
    return {"ok": True, "events": device_state_store.events(device_id, bounded_limit)}


@router.get("/deployments")
def deployment_history(
    limit: int = 20,
    log_store: PersistentLogStore = Depends(get_log_store),
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    bounded_limit = max(1, min(limit, 100))
    deployments = []
    for item in log_store.list_deployments(bounded_limit):
        if isinstance(item, dict):
            deployments.append(_build_web_deploy_view({"ok": True, **item}))
    return {"ok": True, "deployments": deployments}


@router.get("/deployments/{request_id}")
def deployment_detail(
    request_id: str,
    log_store: PersistentLogStore = Depends(get_log_store),
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    deployment = log_store.get_deployment(request_id)
    if not isinstance(deployment, dict):
        return {"ok": False, "deployment": None}
    return {"ok": True, "deployment": _build_web_deploy_view({"ok": True, **deployment})}


@router.get("/devices/{device_id}/messages")
def device_message_history(
    device_id: str,
    limit: int = 50,
    channel: str | None = None,
    log_store: PersistentLogStore = Depends(get_log_store),
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    bounded_limit = max(1, min(limit, 200))
    return {"ok": True, "messages": log_store.list_device_messages(device_id, bounded_limit, channel)}


@router.get("/agent/runtime/runs")
def agent_runtime_runs(
    limit: int = 20,
    runtime_agent: HermesRA8P1Agent = Depends(get_runtime_agent),
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    bounded_limit = max(1, min(limit, 100))
    return {"ok": True, "runs": runtime_agent.list_runs(bounded_limit)}


@router.get("/agent/runtime/runs/{request_id}")
def agent_runtime_run_detail(
    request_id: str,
    runtime_agent: HermesRA8P1Agent = Depends(get_runtime_agent),
    _auth: None = Depends(require_api_token),
) -> dict[str, object]:
    run = runtime_agent.get_run(request_id)
    return {"ok": run is not None, "run": run}
