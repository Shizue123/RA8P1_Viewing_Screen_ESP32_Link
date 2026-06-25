from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


JsonObject = dict[str, Any]


@dataclass(frozen=True)
class HardwareCatalogEntry:
    type: str
    bus: str
    addresses: tuple[str, ...]
    category: str
    capabilities: tuple[str, ...]
    driver: str
    confidence: str
    compatible: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)


_CAPABILITY_ALIASES = {
    "AHT20.temp": "env.temperature",
    "AHT20.temperature": "env.temperature",
    "AHT20.humidity": "env.humidity",
    "SG90.servo_set": "motor.servo.angle",
    "SG90.angle": "motor.servo.angle",
}

_CAPABILITY_LEGACY_SENSORS = {
    "env.temperature": "AHT20.temp",
}

_ACTION_CAPABILITIES = {
    ("SG90", "servo_set"): "motor.servo.angle",
}

I2C_HARDWARE_CATALOG: tuple[HardwareCatalogEntry, ...] = (
    HardwareCatalogEntry(
        type="AHT20",
        bus="i2c",
        addresses=("0x38",),
        category="env_sensor",
        capabilities=("env.temperature", "env.humidity"),
        driver="aht20",
        confidence="exact",
        compatible=("aosong,aht20", "env-sensor"),
        notes=("AHT20 status register can confirm calibrated state.",),
    ),
    HardwareCatalogEntry(
        type="BME280",
        bus="i2c",
        addresses=("0x76", "0x77"),
        category="env_sensor",
        capabilities=("env.temperature", "env.humidity", "env.pressure"),
        driver="bme280",
        confidence="exact",
        compatible=("bosch,bme280", "env-sensor"),
        notes=("Read register 0xD0 and expect chip id 0x60.",),
    ),
    HardwareCatalogEntry(
        type="SHT3x",
        bus="i2c",
        addresses=("0x44", "0x45"),
        category="env_sensor",
        capabilities=("env.temperature", "env.humidity"),
        driver="sht3x",
        confidence="exact",
        compatible=("sensirion,sht3x", "env-sensor"),
        notes=("Use status/serial read commands for safe family confirmation.",),
    ),
    HardwareCatalogEntry(
        type="BMP280",
        bus="i2c",
        addresses=("0x76", "0x77"),
        category="env_sensor",
        capabilities=("env.temperature", "env.pressure"),
        driver="bmp280",
        confidence="exact",
        compatible=("bosch,bmp280", "env-sensor"),
        notes=("Read register 0xD0 and expect chip id 0x58.",),
    ),
    HardwareCatalogEntry(
        type="SSD1306",
        bus="i2c",
        addresses=("0x3C", "0x3D"),
        category="display",
        capabilities=("display.text", "display.bitmap"),
        driver="ssd1306",
        confidence="class",
        compatible=("solomon,ssd1306", "display"),
        notes=("Most SSD1306 modules do not expose a reliable chip id; treat as class until driver init succeeds.",),
    ),
    HardwareCatalogEntry(
        type="MPU6050",
        bus="i2c",
        addresses=("0x68", "0x69"),
        category="motion_sensor",
        capabilities=("imu.accel", "imu.gyro", "env.temperature"),
        driver="mpu6050",
        confidence="exact",
        compatible=("invensense,mpu6050", "imu"),
        notes=("Read WHO_AM_I register 0x75 to confirm device family.",),
    ),
    HardwareCatalogEntry(
        type="PCA9685",
        bus="i2c",
        addresses=("0x40", "0x41", "0x42", "0x43", "0x44", "0x45", "0x46", "0x47"),
        category="pwm_controller",
        capabilities=("pwm.channel", "motor.servo.angle"),
        driver="pca9685",
        confidence="exact",
        compatible=("nxp,pca9685", "pwm-controller"),
        notes=("Use MODE registers for safe probe; avoid moving outputs during identification.",),
    ),
    HardwareCatalogEntry(
        type="ADS1115",
        bus="i2c",
        addresses=("0x48", "0x49", "0x4A", "0x4B"),
        category="adc",
        capabilities=("adc.voltage",),
        driver="ads1115",
        confidence="exact",
        compatible=("ti,ads1115", "adc"),
        notes=("Probe configuration register without changing mux/gain state.",),
    ),
    HardwareCatalogEntry(
        type="PCF8574",
        bus="i2c",
        addresses=("0x20", "0x21", "0x22", "0x23", "0x24", "0x25", "0x26", "0x27"),
        category="io_expander",
        capabilities=("io.digital_in", "io.digital_out"),
        driver="pcf8574",
        confidence="class",
        compatible=("nxp,pcf8574", "io-expander"),
        notes=("No unique chip id; expose as candidate until user or driver verification confirms wiring.",),
    ),
    HardwareCatalogEntry(
        type="MCP23017",
        bus="i2c",
        addresses=("0x20", "0x21", "0x22", "0x23", "0x24", "0x25", "0x26", "0x27"),
        category="io_expander",
        capabilities=("io.digital_in", "io.digital_out"),
        driver="mcp23017",
        confidence="class",
        compatible=("microchip,mcp23017", "io-expander"),
        notes=("Shares common IO-expander address range; user confirmation may be required.",),
    ),
)


def normalize_capability(value: str) -> str:
    return _CAPABILITY_ALIASES.get(value, value)


def legacy_sensor_for_capability(value: str) -> str:
    capability = normalize_capability(value)
    return _CAPABILITY_LEGACY_SENSORS.get(capability, value)


def capability_for_sensor(value: str) -> str:
    return normalize_capability(value)


def capability_for_action(device: str, method: str) -> str:
    return _ACTION_CAPABILITIES.get((_normalize_device(device), method), f"{_normalize_device(device).lower()}.{method}")


def known_trigger_capabilities() -> set[str]:
    return set(_CAPABILITY_LEGACY_SENSORS)


def catalog_status() -> JsonObject:
    return {
        "version": "platform-hardware-catalog.v1",
        "bus_types": ["i2c"],
        "entries": [_entry_to_dict(entry) for entry in I2C_HARDWARE_CATALOG],
        "capability_aliases": dict(_CAPABILITY_ALIASES),
    }


def build_platform_hardware_registry(snapshot: JsonObject) -> JsonObject:
    status_payload = _message_payload(snapshot.get("last_status"))
    telemetry_payload = _message_payload(snapshot.get("last_telemetry"))
    registry = _registry_from_ports_payload(status_payload, telemetry_payload)
    if registry is None:
        registry = _registry_from_v2_payload(status_payload)
    if registry is None:
        registry = _registry_from_legacy_payload(status_payload, telemetry_payload)
    return registry


def capability_available(registry: JsonObject, capability: str) -> bool:
    normalized = normalize_capability(capability)
    for item in registry.get("capabilities", []):
        if not isinstance(item, dict):
            continue
        if item.get("id") == normalized and item.get("status") not in {
            "offline",
            "error",
            "blocked",
            "empty",
            "not_supported",
            "reserved",
            "unknown",
        }:
            return True
    return False


def _registry_from_ports_payload(status_payload: JsonObject, telemetry_payload: JsonObject) -> JsonObject | None:
    ports = status_payload.get("ports")
    if not isinstance(ports, list):
        ports = telemetry_payload.get("ports") if isinstance(telemetry_payload.get("ports"), list) else []
    if not ports:
        return None

    normalized_ports: list[JsonObject] = []
    buses: list[JsonObject] = []
    devices: list[JsonObject] = []
    capabilities: list[JsonObject] = []

    for raw_port in ports:
        if not isinstance(raw_port, dict):
            continue
        port_id = str(raw_port.get("port_id") or "unknown")
        port_type = str(raw_port.get("type") or "unknown")
        module = raw_port.get("module")
        module = module if isinstance(module, dict) else {}
        module_type = str(module.get("module_type") or "none")
        module_id = str(module.get("module_id") or "")
        address = _normalize_address(module.get("address"))
        status = str(raw_port.get("status") or "unknown")
        raw_capabilities = raw_port.get("capabilities")
        raw_capabilities = raw_capabilities if isinstance(raw_capabilities, list) else []

        normalized_capabilities: list[str] = []
        capability_records: list[JsonObject] = []
        for capability in raw_capabilities:
            if not isinstance(capability, dict):
                continue
            capability_id = normalize_capability(str(capability.get("id") or ""))
            if not capability_id:
                continue
            capability_status = str(capability.get("status") or status or "unknown")
            normalized_capabilities.append(capability_id)
            capability_records.append(
                {
                    "id": capability_id,
                    "status": capability_status,
                    "source": {
                        "bus": port_id,
                        "address": address,
                        "type": module_type,
                    },
                    "confidence": module.get("confidence") or "unknown",
                    "safe_for_automation": capability_status not in {"offline", "error", "blocked", "empty", "reserved", "not_supported"},
                }
            )

        normalized_ports.append(
            {
                "id": port_id,
                "physical_port": raw_port.get("physical_port") or "",
                "channel": raw_port.get("channel") or "",
                "type": port_type,
                "activation": raw_port.get("activation") or "",
                "status": status,
                "diag": raw_port.get("diag"),
                "module": {
                    "module_id": module_id,
                    "module_type": module_type,
                    "module_class": module.get("module_class") or "",
                    "driver": module.get("driver") or "",
                    "model_state": module.get("model_state") or "",
                    "binding_source": module.get("binding_source") or "",
                    "confidence": module.get("confidence") or "unknown",
                    "address": address,
                    "device_key": module.get("device_key") or "",
                },
                "capabilities": normalized_capabilities,
                "last_sample_ms": raw_port.get("last_sample_ms"),
            }
        )

        has_module = module_type.lower() not in {"", "none", "reserved"}
        if has_module:
            device = {
                "bus": port_id,
                "address": address,
                "type": module_type,
                "category": port_type,
                "module_class": module.get("module_class") or "",
                "driver": module.get("driver") or "",
                "model_state": module.get("model_state") or "",
                "binding_source": module.get("binding_source") or "",
                "confidence": module.get("confidence") or "unknown",
                "status": status,
                "safe_for_automation": status not in {"offline", "error", "blocked", "empty", "reserved", "not_supported"},
                "capabilities": normalized_capabilities,
                "device_key": module.get("device_key") or "",
            }
            devices.append(device)

        capabilities.extend(capability_records)

        if port_type == "i2c":
            buses.append(
                {
                    "id": port_id,
                    "type": "i2c",
                    "diag": raw_port.get("diag"),
                    "count": 1 if has_module else 0,
                    "devices": [device] if has_module else [],
                }
            )

    return {
        "schema": "platform.hardware_registry.v1",
        "source": "ports_status_payload",
        "ports": normalized_ports,
        "buses": buses,
        "devices": devices,
        "capabilities": _dedupe_capabilities(capabilities),
    }


def _registry_from_v2_payload(payload: JsonObject) -> JsonObject | None:
    buses = payload.get("buses")
    if not isinstance(buses, list):
        return None

    devices: list[JsonObject] = []
    capabilities: list[JsonObject] = []
    normalized_buses: list[JsonObject] = []
    for bus in buses:
        if not isinstance(bus, dict):
            continue
        bus_id = str(bus.get("id") or bus.get("bus") or "unknown")
        bus_devices: list[JsonObject] = []
        for device in bus.get("devices", []):
            if not isinstance(device, dict):
                continue
            enriched = _enrich_device(device, bus_id=bus_id)
            devices.append(enriched)
            bus_devices.append(enriched)
            capabilities.extend(_capabilities_for_device(enriched, bus_id=bus_id))
        normalized_buses.append({**bus, "id": bus_id, "devices": bus_devices})

    return {
        "schema": "platform.hardware_registry.v1",
        "source": "device_payload_v2",
        "buses": normalized_buses,
        "devices": devices,
        "capabilities": _dedupe_capabilities(capabilities),
    }


def _registry_from_legacy_payload(status_payload: JsonObject, telemetry_payload: JsonObject) -> JsonObject:
    i2c = status_payload.get("i2c")
    if not isinstance(i2c, dict):
        i2c = telemetry_payload.get("i2c") if isinstance(telemetry_payload.get("i2c"), dict) else {}
    bus_id = f"i2c.{str(i2c.get('bus') or 's1')}"
    devices: list[JsonObject] = []

    for raw in _legacy_hardware_items(status_payload, i2c):
        if not isinstance(raw, dict):
            continue
        devices.append(_enrich_device(raw, bus_id=bus_id))

    capabilities: list[JsonObject] = []
    for device in devices:
        capabilities.extend(_capabilities_for_device(device, bus_id=bus_id))

    return {
        "schema": "platform.hardware_registry.v1",
        "source": "legacy_status_payload",
        "buses": [
            {
                "id": bus_id,
                "type": "i2c",
                "diag": i2c.get("diag"),
                "count": i2c.get("count") if i2c.get("count") is not None else len(devices),
                "devices": devices,
            }
        ],
        "devices": devices,
        "capabilities": _dedupe_capabilities(capabilities),
    }


def _legacy_hardware_items(status_payload: JsonObject, i2c: JsonObject) -> list[JsonObject]:
    hardware_list = status_payload.get("hardware_list")
    if isinstance(hardware_list, list) and hardware_list:
        return [item for item in hardware_list if isinstance(item, dict)]
    devices = i2c.get("devices")
    return [item for item in devices if isinstance(item, dict)] if isinstance(devices, list) else []


def _enrich_device(device: JsonObject, *, bus_id: str) -> JsonObject:
    address = _normalize_address(device.get("address"))
    device_type = str(device.get("type") or device.get("device_type") or "unknown")
    catalog_entry = _match_catalog_entry(address, device_type)
    confidence = str(device.get("confidence") or (catalog_entry.confidence if catalog_entry else "unknown"))
    capabilities = device.get("capabilities")
    if not isinstance(capabilities, list):
        capabilities = list(catalog_entry.capabilities) if catalog_entry else []
    status = str(device.get("status") or ("present" if address else "unknown"))
    return {
        "bus": bus_id,
        "address": address,
        "type": device_type,
        "category": device.get("category") or (catalog_entry.category if catalog_entry else "unknown"),
        "driver": device.get("driver") or (catalog_entry.driver if catalog_entry else ""),
        "confidence": confidence,
        "status": status,
        "safe_for_automation": confidence == "exact" and status in {"online", "present", "available"},
        "capabilities": [normalize_capability(str(item)) for item in capabilities],
    }


def _capabilities_for_device(device: JsonObject, *, bus_id: str) -> list[JsonObject]:
    capabilities: list[JsonObject] = []
    status = str(device.get("status") or "unknown")
    for capability in device.get("capabilities", []):
        capabilities.append(
            {
                "id": normalize_capability(str(capability)),
                "status": "online" if status == "online" else status,
                "source": {
                    "bus": bus_id,
                    "address": device.get("address"),
                    "type": device.get("type"),
                },
                "confidence": device.get("confidence") or "unknown",
                "safe_for_automation": bool(device.get("safe_for_automation")),
            }
        )
    return capabilities


def _dedupe_capabilities(items: list[JsonObject]) -> list[JsonObject]:
    seen: set[tuple[str, str, str]] = set()
    result: list[JsonObject] = []
    for item in items:
        source = item.get("source")
        source = source if isinstance(source, dict) else {}
        key = (str(item.get("id") or ""), str(source.get("bus") or ""), str(source.get("address") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _match_catalog_entry(address: str, device_type: str) -> HardwareCatalogEntry | None:
    normalized_type = _normalize_device(device_type)
    for entry in I2C_HARDWARE_CATALOG:
        if _normalize_device(entry.type) == normalized_type:
            return entry
    class_aliases = {
        "OLED_CLASS": "display",
        "ENV_CLASS": "env_sensor",
        "IMU_RTC_CLASS": "motion_sensor",
        "EEPROM_CLASS": "storage",
    }
    expected_category = class_aliases.get(normalized_type)
    if expected_category:
        for entry in I2C_HARDWARE_CATALOG:
            if address in entry.addresses and entry.category == expected_category:
                return entry
    for entry in I2C_HARDWARE_CATALOG:
        if address in entry.addresses and _type_matches_class(normalized_type, entry):
            return entry
    return None


def _type_matches_class(device_type: str, entry: HardwareCatalogEntry) -> bool:
    if device_type == "UNKNOWN":
        return False
    if device_type.endswith("CLASS"):
        return entry.category.upper().replace("_", "") in device_type or entry.type.upper() in device_type
    return False


def _message_payload(message: object) -> JsonObject:
    if not isinstance(message, dict):
        return {}
    payload = message.get("payload")
    return payload if isinstance(payload, dict) else {}


def _entry_to_dict(entry: HardwareCatalogEntry) -> JsonObject:
    return {
        "type": entry.type,
        "bus": entry.bus,
        "addresses": list(entry.addresses),
        "category": entry.category,
        "capabilities": list(entry.capabilities),
        "driver": entry.driver,
        "confidence": entry.confidence,
        "compatible": list(entry.compatible),
        "notes": list(entry.notes),
    }


def _normalize_address(value: object) -> str:
    if isinstance(value, int):
        return f"0x{value:02X}"
    text = str(value or "").strip()
    if not text:
        return ""
    if text.lower().startswith("0x"):
        try:
            return f"0x{int(text, 16):02X}"
        except ValueError:
            return text
    try:
        return f"0x{int(text):02X}"
    except ValueError:
        return text


def _normalize_device(value: str) -> str:
    return value.upper().replace(" ", "").replace("-", "_").replace(".", "_")
