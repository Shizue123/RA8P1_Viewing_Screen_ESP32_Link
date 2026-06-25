from __future__ import annotations

from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_KNOWLEDGE_ROOTS = (
    ("Project documents", PROJECT_ROOT / "docs"),
    ("Structured knowledge", PROJECT_ROOT / "mcp" / "resources"),
    ("Hardware sources", PROJECT_ROOT / "Hardware-code"),
)
ALLOWED_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".pdf"}
JsonObject = dict[str, Any]


def knowledge_catalog(limit: int = 80) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    available_roots: list[str] = []
    for label, root in ALLOWED_KNOWLEDGE_ROOTS:
        if not root.exists():
            continue
        available_roots.append(label)
        for path in sorted(root.rglob("*")):
            if len(entries) >= limit:
                break
            if not path.is_file() or path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            entries.append(
                {
                    "name": path.name,
                    "category": label,
                    "path": path.relative_to(PROJECT_ROOT).as_posix(),
                    "type": path.suffix.lower().lstrip("."),
                }
            )
    return {
        "available": bool(entries),
        "roots": available_roots,
        "documents": entries,
        "truncated": len(entries) >= limit,
    }


def _message_payload(message: object) -> JsonObject:
    if not isinstance(message, dict):
        return {}
    payload = message.get("payload")
    return payload if isinstance(payload, dict) else {}


def _dict_value(source: JsonObject, key: str) -> JsonObject:
    value = source.get(key)
    return value if isinstance(value, dict) else {}


def _list_value(source: JsonObject, key: str) -> list[object]:
    value = source.get(key)
    return value if isinstance(value, list) else []


def _status_text(value: object, fallback: str = "unknown") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _number_or_none(value: object) -> object:
    return value if isinstance(value, (int, float)) else None


def _message_timestamp(message: object) -> float | None:
    if not isinstance(message, dict):
        return None
    timestamp = message.get("timestamp")
    if isinstance(timestamp, (int, float)):
        return float(timestamp)
    if isinstance(timestamp, str):
        try:
            return float(timestamp)
        except ValueError:
            return None
    return None


def _port_entries(payload: JsonObject) -> list[JsonObject]:
    return [item for item in _list_value(payload, "ports") if isinstance(item, dict)]


def _sample_entries(payload: JsonObject) -> list[JsonObject]:
    return [item for item in _list_value(payload, "samples") if isinstance(item, dict)]


def _module_value(port: JsonObject) -> JsonObject:
    module = port.get("module")
    return module if isinstance(module, dict) else {}


def _capability_entries(port: JsonObject) -> list[JsonObject]:
    return [item for item in _list_value(port, "capabilities") if isinstance(item, dict)]


def _find_port(payload: JsonObject, port_id: str) -> JsonObject:
    for port in _port_entries(payload):
        if str(port.get("port_id") or "").strip() == port_id:
            return port
    return {}


def _capability_status(port: JsonObject, capability_id: str) -> str:
    for capability in _capability_entries(port):
        if str(capability.get("id") or "").strip() == capability_id:
            return _status_text(capability.get("status"), "")
    return ""


def _find_sample(payload: JsonObject, capability_id: str, *, port_id: str = "", module_type: str = "") -> JsonObject:
    for sample in _sample_entries(payload):
        if str(sample.get("capability") or "").strip() != capability_id:
            continue
        if port_id and str(sample.get("port_id") or "").strip() != port_id:
            continue
        if module_type and str(sample.get("module_type") or "").strip().upper() != module_type.upper():
            continue
        return sample
    return {}


def _format_reading_label(capability_id: str) -> str:
    return {
        "env.temperature": "温度",
        "env.humidity": "湿度",
        "env.light.lux": "光照",
        "motor.servo.angle": "角度",
        "bridge.uart.mqtt": "桥接状态",
    }.get(capability_id, capability_id)


def _module_class_from_hardware_type(value: object) -> str:
    hardware_type = _status_text(value, "").upper()
    return {
        "AHT20": "env.th",
        "AHT21": "env.th",
        "BH1750": "env.light",
        "9548A-MUX": "i2c.mux",
        "ENV-CLASS": "env.multi",
        "OLED-CLASS": "display.i2c",
        "EEPROM-CLASS": "storage.eeprom",
        "IMU-RTC-CLASS": "motion_time",
    }.get(hardware_type, "")


def _readings_from_port(port: JsonObject, status_payload: JsonObject, telemetry_payload: JsonObject) -> list[JsonObject]:
    readings: list[JsonObject] = []
    port_id = str(port.get("port_id") or "").strip()
    module = _module_value(port)
    module_type = _status_text(module.get("module_type"), "")
    for capability in _capability_entries(port):
        capability_id = str(capability.get("id") or "").strip()
        if not capability_id:
            continue
        sample = _find_sample(telemetry_payload, capability_id, port_id=port_id, module_type=module_type)
        if not sample:
            sample = _find_sample(status_payload, capability_id, port_id=port_id, module_type=module_type)
        if not sample:
            continue
        value = _number_or_none(sample.get("value"))
        if value is None:
            continue
        readings.append(
            {
                "label": _format_reading_label(capability_id),
                "capability": capability_id,
                "value": value,
                "unit": sample.get("unit") or capability.get("unit") or "",
            }
        )
    return readings


def _sample_readings_for_module(
    status_payload: JsonObject,
    telemetry_payload: JsonObject,
    *,
    port_id: str,
    module_type: str,
) -> tuple[list[JsonObject], list[str]]:
    readings: list[JsonObject] = []
    capabilities: list[str] = []
    seen_capabilities: set[str] = set()
    for payload in (telemetry_payload, status_payload):
        for sample in _sample_entries(payload):
            if str(sample.get("port_id") or "").strip() != port_id:
                continue
            if str(sample.get("module_type") or "").strip().upper() != module_type.upper():
                continue
            capability_id = str(sample.get("capability") or "").strip()
            value = _number_or_none(sample.get("value"))
            if not capability_id or value is None or capability_id in seen_capabilities:
                continue
            seen_capabilities.add(capability_id)
            capabilities.append(capability_id)
            readings.append(
                {
                    "label": _format_reading_label(capability_id),
                    "capability": capability_id,
                    "value": value,
                    "unit": sample.get("unit") or "",
                }
            )
    return readings, capabilities


def _module_present(module: JsonObject) -> bool:
    module_type = _status_text(module.get("module_type"), "")
    return module_type.lower() not in {"", "none", "reserved"}


def _port_signals(port_id: str, port_type: str, channel_name: str) -> list[JsonObject]:
    if port_id == "i2c.s1":
        return [
            {"name": "SDA", "direction": "bidirectional", "pin": "P309"},
            {"name": "SCL", "direction": "clock", "pin": "P306"},
        ]
    if port_id == "pwm.0":
        return [
            {"name": "PWM", "direction": "output", "pin": channel_name or "P105"},
            {"name": "VCC", "direction": "power", "pin": "external-5V"},
            {"name": "GND", "direction": "ground", "pin": "common-GND"},
        ]
    if port_id == "uart.bridge":
        return [{"name": "UART", "direction": "bridge", "pin": channel_name or "UART0"}]
    return []


def _channel_sort_key(channel: JsonObject) -> tuple[int, str]:
    order = {
        "i2c.s1": 0,
        "i2c.s2": 1,
        "pwm.0": 2,
        "uart.bridge": 3,
    }
    channel_id = str(channel.get("id") or "")
    return order.get(channel_id, 99), channel_id


def _channels_from_ports(
    status_payload: JsonObject,
    telemetry_payload: JsonObject,
    i2c: JsonObject,
    aht20_observation: JsonObject,
    *,
    device_online: bool,
    last_seen: object,
) -> list[JsonObject]:
    raw_ports = _port_entries(status_payload) or _port_entries(telemetry_payload)
    channels: list[JsonObject] = []
    for port in raw_ports:
        module = _module_value(port)
        module_type = _status_text(module.get("module_type"), "none")
        module_id = _status_text(module.get("module_id"), "")
        port_id = _status_text(port.get("port_id"), "")
        port_status = _status_text(port.get("status"), "unknown")
        endpoint_status = port_status
        capabilities = _capability_entries(port)
        for capability in capabilities:
            capability_status = _status_text(capability.get("status"), "")
            if capability_status in {"execution_feedback", "configured", "channel_ready", "online", "degraded"}:
                endpoint_status = capability_status
                break
        readings = _readings_from_port(port, status_payload, telemetry_payload)
        if not device_online:
            port_status = "offline"
            endpoint_status = "offline"

        endpoint: JsonObject = {
            "address": module.get("address") or None,
            "hardware_type": module_type,
            "status": endpoint_status,
            "capabilities": [item.get("id") for item in capabilities if item.get("id")],
            "readings": readings,
            "metadata": {
                "activation": port.get("activation") or "",
                "diag": port.get("diag"),
                "driver": module.get("driver") or "",
                "confidence": module.get("confidence") or "",
                "module_class": module.get("module_class") or "",
                "module_id": module_id or None,
                "model_state": module.get("model_state") or "",
                "port_id": port_id,
                "physical_port": port.get("physical_port") or "",
                "channel": port.get("channel") or "",
                "binding_source": module.get("binding_source") or "",
                "device_key": module.get("device_key") or "",
                "last_sample_ms": port.get("last_sample_ms"),
                "source": "ports_samples_v1",
            },
        }
        if port_id == "pwm.0":
            endpoint["control_methods"] = ["servo_set", "servo.sweep"]
            endpoint["metadata"]["physical_detection"] = "not_supported_pwm_no_feedback"

        if not _module_present(module):
            endpoint["hardware_type"] = module_type or "none"

        channel: JsonObject = {
            "id": port_id,
            "name": f"{_status_text(port.get('physical_port'), port_id)} · {port_id}",
            "protocol": _status_text(port.get("type"), "unknown").upper(),
            "source": "device_state" if (status_payload or telemetry_payload) else "configured_baseline",
            "signals": _port_signals(port_id, _status_text(port.get("type"), ""), _status_text(port.get("channel"), "")),
            "state": {
                "activation": port.get("activation") or "",
                "diagnostic": port.get("diag") or "unknown",
                "interpretation": module.get("module_class") or module_type,
                "module_type": module_type,
                "detected_count": 1 if _module_present(module) else 0,
                "status": port_status,
                "last_seen": last_seen,
                "last_sample_ms": port.get("last_sample_ms"),
            },
            "hardware": [endpoint],
        }
        if port_id == "i2c.s1":
            channel = _reconcile_i2c_channel(
                channel,
                port,
                status_payload,
                telemetry_payload,
                i2c,
                aht20_observation,
                device_online=device_online,
            )
        channels.append(channel)
    channels.sort(key=_channel_sort_key)
    return channels


def latest_aht20_observation(status_message: object, telemetry_message: object) -> JsonObject:
    candidates: list[tuple[str, int, float | None, JsonObject]] = []
    for source, priority, message in (
        ("telemetry", 0, telemetry_message),
        ("status", 1, status_message),
    ):
        payload = _message_payload(message)
        legacy_aht20 = _dict_value(payload, "aht20")
        port = _find_port(payload, "i2c.s1")
        sample_temp = _find_sample(payload, "env.temperature", port_id="i2c.s1", module_type="AHT20")
        sample_humidity = _find_sample(payload, "env.humidity", port_id="i2c.s1", module_type="AHT20")
        aht20 = dict(legacy_aht20)
        has_temperature = _number_or_none(aht20.get("temp")) is not None or _number_or_none(
            aht20.get("temperature")
        ) is not None
        has_humidity = _number_or_none(aht20.get("humidity")) is not None
        if sample_temp or sample_humidity or port:
            if sample_temp:
                temperature = _number_or_none(sample_temp.get("value"))
                if temperature is not None:
                    aht20["temp"] = temperature
                    aht20["temperature"] = temperature
                    has_temperature = True
            if sample_humidity:
                humidity = _number_or_none(sample_humidity.get("value"))
                if humidity is not None:
                    aht20["humidity"] = humidity
                    has_humidity = True
            if port:
                if has_temperature and has_humidity:
                    aht20["status"] = "online"
                    aht20["diag"] = "ok"
                else:
                    aht20["status"] = port.get("status") or aht20.get("status")
                    aht20["diag"] = port.get("diag") or aht20.get("diag")
                module = _module_value(port)
                if module.get("address"):
                    aht20["address"] = module.get("address")
        if aht20:
            candidates.append((source, priority, _message_timestamp(message), aht20))

    if not candidates:
        return {"payload": {}, "source": None, "timestamp": None}

    source, _priority, timestamp, aht20 = max(
        candidates,
        key=lambda item: (
            item[2] is not None,
            item[2] if item[2] is not None else float("-inf"),
            item[1],
        ),
    )
    return {"payload": aht20, "source": source, "timestamp": timestamp}


def _normalize_i2c_payload(source: JsonObject) -> tuple[JsonObject, JsonObject, JsonObject]:
    status_payload = _message_payload(source.get("last_status"))
    telemetry_payload = _message_payload(source.get("last_telemetry"))
    direct_i2c = _dict_value(source, "i2c")
    status_i2c = _dict_value(status_payload, "i2c")
    telemetry_i2c = _dict_value(telemetry_payload, "i2c")
    i2c = {**telemetry_i2c, **status_i2c, **direct_i2c}
    return status_payload, telemetry_payload, i2c


def _i2c_endpoints(
    status_payload: JsonObject,
    telemetry_payload: JsonObject,
    i2c: JsonObject,
    aht20_observation: JsonObject,
    *,
    device_online: bool,
) -> list[JsonObject]:
    raw_devices = _list_value(i2c, "devices")
    if not raw_devices:
        raw_devices = [
            item
            for item in _list_value(status_payload, "hardware_list")
            if isinstance(item, dict)
            and (
                item.get("address")
                or str(item.get("bus") or "").lower().startswith("i2c")
                or _status_text(item.get("type") or item.get("hardware_type"), "").upper() == "AHT20"
            )
        ]

    aht20 = _dict_value(aht20_observation, "payload")
    has_aht20 = False
    endpoints: list[JsonObject] = []
    for device in raw_devices:
        if not isinstance(device, dict):
            continue
        hardware_type = _status_text(device.get("type") or device.get("hardware_type"), "unidentified")
        if hardware_type.upper() == "SG90":
            continue
        if hardware_type.upper() == "AHT20":
            has_aht20 = True
        endpoint: JsonObject = {
            "address": device.get("address") or ("0x38" if hardware_type.upper() == "AHT20" else None),
            "hardware_type": hardware_type,
            "status": device.get("status") or ("online" if hardware_type.upper() == "AHT20" and aht20.get("status") == "online" else "detected"),
            "capabilities": device.get("capabilities") if isinstance(device.get("capabilities"), list) else [],
            "readings": [],
            "metadata": {
                key: value
                for key, value in device.items()
                if key not in {"address", "type", "hardware_type", "status", "capabilities"}
            },
        }
        endpoint["metadata"]["module_class"] = endpoint["metadata"].get("module_class") or _module_class_from_hardware_type(hardware_type)
        sample_readings, sample_capabilities = _sample_readings_for_module(
            status_payload,
            telemetry_payload,
            port_id="i2c.s1",
            module_type=hardware_type,
        )
        if hardware_type.upper() == "AHT20":
            endpoint["capabilities"] = endpoint["capabilities"] or ["env.temperature", "env.humidity"]
            endpoint["status"] = aht20.get("status") or endpoint["status"]
            endpoint["readings"] = _aht20_readings(aht20)
            endpoint["metadata"] = {
                **endpoint["metadata"],
                "diag": aht20.get("diag"),
                "crc_ok": aht20.get("crc_ok"),
                "source": aht20_observation.get("source"),
                "timestamp": aht20_observation.get("timestamp"),
            }
        elif sample_readings:
            endpoint["readings"] = sample_readings
            endpoint["capabilities"] = endpoint["capabilities"] or sample_capabilities
            if _status_text(endpoint.get("status"), "unknown").lower() in {"unknown", "detected", "present"}:
                endpoint["status"] = "online"
        if not device_online:
            endpoint["status"] = "offline"
        endpoints.append(endpoint)

    if aht20 and not has_aht20:
        endpoints.append(
            {
                "address": "0x38",
                "hardware_type": "AHT20",
                "status": (aht20.get("status") or "unknown") if device_online else "offline",
                "capabilities": ["env.temperature", "env.humidity"],
                "readings": _aht20_readings(aht20),
                "metadata": {
                    "diag": aht20.get("diag"),
                    "crc_ok": aht20.get("crc_ok"),
                    "source": aht20_observation.get("source"),
                    "timestamp": aht20_observation.get("timestamp"),
                },
            }
        )
    return endpoints


def _aht20_readings(aht20: JsonObject) -> list[JsonObject]:
    readings: list[JsonObject] = []
    temperature = _number_or_none(aht20.get("temp") if aht20.get("temp") is not None else aht20.get("temperature"))
    humidity = _number_or_none(aht20.get("humidity"))
    if temperature is not None:
        readings.append({"label": "温度", "capability": "env.temperature", "value": temperature, "unit": "C"})
    if humidity is not None:
        readings.append({"label": "湿度", "capability": "env.humidity", "value": humidity, "unit": "%"})
    return readings


def _endpoint_has_presence(endpoint: JsonObject) -> bool:
    hardware_type = _status_text(endpoint.get("hardware_type"), "").lower()
    if hardware_type in {"", "none", "reserved", "unidentified"}:
        return False
    status = _status_text(endpoint.get("status"), "unknown").lower()
    if status in {"offline", "unknown", "not_inserted", "empty"} and not endpoint.get("readings") and not endpoint.get("capabilities"):
        return False
    return True


def _channel_should_use_i2c_legacy(current_hardware: list[JsonObject], legacy_endpoints: list[JsonObject]) -> bool:
    if not legacy_endpoints:
        return False
    current_present = [endpoint for endpoint in current_hardware if _endpoint_has_presence(endpoint)]
    legacy_present = [endpoint for endpoint in legacy_endpoints if _endpoint_has_presence(endpoint)]
    if not legacy_present:
        return False
    if not current_present:
        return True
    if len(legacy_present) > len(current_present):
        return True
    if not any(endpoint.get("readings") for endpoint in current_hardware) and any(endpoint.get("readings") for endpoint in legacy_endpoints):
        return True
    return False


def _channel_status_from_endpoints(endpoints: list[JsonObject], *, device_online: bool) -> str:
    if not device_online:
        return "offline"
    active_statuses = {
        "online",
        "present",
        "available",
        "detected",
        "configured",
        "channel_ready",
        "execution_feedback",
        "degraded",
    }
    if any(_status_text(endpoint.get("status"), "unknown").lower() in active_statuses for endpoint in endpoints):
        return "online"
    return "waiting" if endpoints else "unknown"


def _inferred_i2c_interpretation(i2c: JsonObject, endpoints: list[JsonObject]) -> str:
    interpretation = _status_text(i2c.get("interpretation"), "")
    if interpretation and interpretation.lower() != "unknown":
        return interpretation
    classes: list[str] = []
    for endpoint in endpoints:
        metadata = endpoint.get("metadata")
        module_class = ""
        if isinstance(metadata, dict):
            module_class = _status_text(metadata.get("module_class"), "")
        module_class = module_class or _module_class_from_hardware_type(endpoint.get("hardware_type"))
        if module_class and module_class.lower() != "unknown":
            classes.append(module_class)
    signal_classes = sorted({item for item in classes if item != "i2c.mux"})
    if len(signal_classes) > 1:
        return "env.multi"
    if signal_classes:
        return signal_classes[0]
    return classes[0] if classes else "unknown"


def _reconcile_i2c_channel(
    channel: JsonObject,
    port: JsonObject,
    status_payload: JsonObject,
    telemetry_payload: JsonObject,
    i2c: JsonObject,
    aht20_observation: JsonObject,
    *,
    device_online: bool,
) -> JsonObject:
    current_hardware = [item for item in channel.get("hardware", []) if isinstance(item, dict)]
    legacy_endpoints = _i2c_endpoints(
        status_payload,
        telemetry_payload,
        i2c,
        aht20_observation,
        device_online=device_online,
    )
    if not _channel_should_use_i2c_legacy(current_hardware, legacy_endpoints):
        return channel

    merged_hardware: list[JsonObject] = []
    port_id = _status_text(port.get("port_id"), "")
    for endpoint in legacy_endpoints:
        metadata = endpoint.get("metadata")
        endpoint_metadata = dict(metadata) if isinstance(metadata, dict) else {}
        endpoint_activation = _status_text(endpoint_metadata.get("activation"), "")
        if endpoint_activation.lower() in {"", "inactive", "unknown"} and device_online and _endpoint_has_presence(endpoint):
            endpoint_metadata["activation"] = "channel_active"
        else:
            endpoint_metadata["activation"] = endpoint_metadata.get("activation") or port.get("activation") or ("channel_active" if device_online else "")
        endpoint_metadata["channel"] = endpoint_metadata.get("channel") or port.get("channel") or ""
        endpoint_metadata["diag"] = endpoint_metadata.get("diag") or i2c.get("diag") or port.get("diag")
        endpoint_metadata["module_class"] = endpoint_metadata.get("module_class") or _module_class_from_hardware_type(endpoint.get("hardware_type"))
        endpoint_metadata["physical_port"] = endpoint_metadata.get("physical_port") or port.get("physical_port") or ""
        endpoint_metadata["port_id"] = endpoint_metadata.get("port_id") or port_id
        endpoint_metadata["source"] = endpoint_metadata.get("source") or "legacy_i2c_samples_v1"
        merged_endpoint = dict(endpoint)
        merged_endpoint["metadata"] = endpoint_metadata
        if device_online and merged_endpoint.get("readings") and _status_text(merged_endpoint.get("status"), "unknown").lower() in {"unknown", "detected", "present", "not_inserted", "empty", "offline"}:
            merged_endpoint["status"] = "online"
        merged_hardware.append(merged_endpoint)

    state = channel.get("state")
    channel_state = dict(state) if isinstance(state, dict) else {}
    current_activation = _status_text(channel_state.get("activation"), "")
    if current_activation.lower() in {"", "inactive", "unknown"} and device_online and merged_hardware:
        channel_state["activation"] = "channel_active"
    channel_state["diagnostic"] = i2c.get("diag") or channel_state.get("diagnostic") or port.get("diag") or "unknown"
    channel_state["interpretation"] = _inferred_i2c_interpretation(i2c, merged_hardware)
    if _status_text(channel_state.get("module_type"), "").lower() in {"", "none", "unknown"}:
        channel_state["module_type"] = channel_state["interpretation"]
    channel_state["detected_count"] = sum(1 for endpoint in merged_hardware if _endpoint_has_presence(endpoint))
    channel_state["status"] = _channel_status_from_endpoints(merged_hardware, device_online=device_online)

    merged_channel = dict(channel)
    merged_channel["state"] = channel_state
    merged_channel["hardware"] = merged_hardware
    return merged_channel


def _servo_endpoint(status_payload: JsonObject, *, device_online: bool) -> JsonObject:
    hardware_list = _list_value(status_payload, "hardware_list")
    sg90 = next(
        (
            item
            for item in hardware_list
            if isinstance(item, dict)
            and _status_text(item.get("type") or item.get("hardware_type"), "").upper() == "SG90"
        ),
        {},
    )
    last_execution = _dict_value(status_payload, "last_execution")
    status = "execution_feedback" if last_execution else "configured"
    if not device_online:
        status = "offline"
    return {
        "hardware_type": "SG90",
        "status": status,
        "capabilities": ["motor.servo.angle"],
        "control_methods": ["servo_set", "servo.sweep"],
        "metadata": {
            "last_execution": last_execution or None,
            "physical_detection": "not_supported_pwm_no_feedback",
            "source": "status_payload" if sg90 else "configured_channel",
        },
    }


def signal_topology(source: dict[str, object]) -> dict[str, object]:
    snapshot = source if isinstance(source, dict) else {}
    aht20_observation = latest_aht20_observation(snapshot.get("last_status"), snapshot.get("last_telemetry"))
    status_payload, telemetry_payload, i2c = _normalize_i2c_payload(snapshot)
    device_online = bool(snapshot.get("_device_online", True))
    port_channels = _channels_from_ports(
        status_payload,
        telemetry_payload,
        i2c,
        aht20_observation,
        device_online=device_online,
        last_seen=snapshot.get("last_seen"),
    )
    if port_channels:
        return {
            "schema": "signal_topology.v3",
            "device_id": snapshot.get("device_id"),
            "last_seen": snapshot.get("last_seen"),
            "channels": port_channels,
        }

    endpoints = _i2c_endpoints(status_payload, telemetry_payload, i2c, aht20_observation, device_online=device_online)
    bus_id = str(i2c.get("bus") or "s1")
    last_seen = snapshot.get("last_seen")
    servo_endpoint = _servo_endpoint(status_payload, device_online=device_online)
    return {
        "schema": "signal_topology.v2",
        "device_id": snapshot.get("device_id"),
        "last_seen": last_seen,
        "channels": [
            {
                "id": f"i2c:{bus_id}",
                "name": f"I2C {bus_id.upper()}",
                "protocol": "I2C",
                "source": "device_state" if (status_payload or telemetry_payload) else "configured_baseline",
                "signals": [
                    {"name": "SDA", "direction": "bidirectional", "pin": "P309"},
                    {"name": "SCL", "direction": "clock", "pin": "P306"},
                ],
                "state": {
                    "diagnostic": i2c.get("diag") or "unknown",
                    "interpretation": i2c.get("interpretation") or "unknown",
                    "detected_count": len(endpoints),
                    "status": "offline" if not device_online else ("online" if any(item.get("status") == "online" for item in endpoints) else "waiting"),
                    "last_seen": last_seen,
                },
                "hardware": endpoints,
            },
            {
                "id": "pwm:servo.1",
                "name": "PWM SERVO 1",
                "protocol": "PWM",
                "source": "device_state" if status_payload else "configured_baseline",
                "signals": [
                    {"name": "PWM", "direction": "output", "pin": "P105"},
                    {"name": "VCC", "direction": "power", "pin": "external-5V"},
                    {"name": "GND", "direction": "ground", "pin": "common-GND"},
                ],
                "state": {
                    "diagnostic": status_payload.get("script_state") or "unknown",
                    "interpretation": "actuator_channel",
                    "detected_count": 1,
                    "status": "offline" if not device_online else "channel_ready",
                    "last_seen": last_seen,
                },
                "hardware": [servo_endpoint],
            }
        ]
    }
