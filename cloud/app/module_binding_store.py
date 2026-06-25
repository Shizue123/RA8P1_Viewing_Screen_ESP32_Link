from __future__ import annotations

import copy
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cloud.app.config import Settings


JsonObject = dict[str, Any]


def _now() -> int:
    return int(time.time())


def _clean_token(value: str, *, max_length: int = 128) -> str:
    return "".join(ch for ch in value.strip() if ch.isalnum() or ch in "-_:.").strip()[:max_length]


def _normalize_text(value: object, *, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _bool_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


MODULE_CLASS_LABELS: dict[str, str] = {
    "env.th": "温湿度模块",
    "env.light": "光照模块",
    "act.servo": "舵机模块",
    "io.expander": "I/O 扩展模块",
}


MODULE_BINDING_OPTIONS: dict[str, JsonObject] = {
    "generic.env.th": {
        "id": "generic.env.th",
        "module_class": "env.th",
        "module_type": "",
        "title": "温湿度模块",
        "model_label": "型号待补充",
        "generic": True,
        "capabilities": ["env.temperature", "env.humidity"],
    },
    "model.aht20": {
        "id": "model.aht20",
        "module_class": "env.th",
        "module_type": "AHT20",
        "title": "温湿度模块",
        "model_label": "AHT20",
        "generic": False,
        "capabilities": ["env.temperature", "env.humidity"],
    },
    "model.sht30": {
        "id": "model.sht30",
        "module_class": "env.th",
        "module_type": "SHT30",
        "title": "温湿度模块",
        "model_label": "SHT30",
        "generic": False,
        "capabilities": ["env.temperature", "env.humidity"],
    },
    "generic.env.light": {
        "id": "generic.env.light",
        "module_class": "env.light",
        "module_type": "",
        "title": "光照模块",
        "model_label": "型号待补充",
        "generic": True,
        "capabilities": ["env.illuminance"],
    },
    "model.bh1750": {
        "id": "model.bh1750",
        "module_class": "env.light",
        "module_type": "BH1750",
        "title": "光照模块",
        "model_label": "BH1750",
        "generic": False,
        "capabilities": ["env.illuminance"],
    },
    "generic.act.servo": {
        "id": "generic.act.servo",
        "module_class": "act.servo",
        "module_type": "",
        "title": "舵机模块",
        "model_label": "型号待补充",
        "generic": True,
        "capabilities": ["motor.servo.angle"],
    },
    "model.sg90": {
        "id": "model.sg90",
        "module_class": "act.servo",
        "module_type": "SG90",
        "title": "舵机模块",
        "model_label": "SG90",
        "generic": False,
        "capabilities": ["motor.servo.angle"],
    },
    "generic.io.expander": {
        "id": "generic.io.expander",
        "module_class": "io.expander",
        "module_type": "",
        "title": "I/O 扩展模块",
        "model_label": "型号待补充",
        "generic": True,
        "capabilities": ["io.digital_in", "io.digital_out"],
    },
    "model.pcf8575": {
        "id": "model.pcf8575",
        "module_class": "io.expander",
        "module_type": "PCF8575",
        "title": "I/O 扩展模块",
        "model_label": "PCF8575",
        "generic": False,
        "capabilities": ["io.digital_in", "io.digital_out"],
    },
}


MODULE_OPTIONS_BY_CLASS: dict[str, list[str]] = {
    "env.th": ["generic.env.th", "model.aht20", "model.sht30"],
    "env.light": ["generic.env.light", "model.bh1750"],
    "act.servo": ["generic.act.servo", "model.sg90"],
    "io.expander": ["generic.io.expander", "model.pcf8575"],
}


MODULE_OPTIONS_BY_PROTOCOL: dict[str, list[str]] = {
    "i2c": ["generic.env.th", "model.aht20", "model.sht30", "generic.env.light", "model.bh1750"],
    "pwm": ["generic.act.servo", "model.sg90"],
}


def module_class_label(value: object) -> str:
    key = _normalize_text(value).lower()
    return MODULE_CLASS_LABELS.get(key, _normalize_text(value, fallback="待识别模块"))


def module_binding_option(option_id: str) -> JsonObject | None:
    option = MODULE_BINDING_OPTIONS.get(_normalize_text(option_id))
    return copy.deepcopy(option) if option is not None else None


def _dynamic_exact_option(module_class: str, module_type: str) -> JsonObject | None:
    clean_class = _normalize_text(module_class)
    clean_type = _normalize_text(module_type)
    if not clean_class or not clean_type or clean_type.lower() in {"none", "reserved", "unknown"}:
        return None
    return {
        "id": f"reported.{clean_type.lower()}",
        "module_class": clean_class,
        "module_type": clean_type,
        "title": module_class_label(clean_class),
        "model_label": clean_type,
        "generic": False,
        "capabilities": [],
    }


def module_binding_options(
    *,
    port_type: str,
    activation: str,
    module_class: str,
    module_type: str,
    binding_source: str,
    model_state: str,
) -> list[JsonObject]:
    activation_key = _normalize_text(activation).lower()
    binding_source_key = _normalize_text(binding_source).lower()
    model_state_key = _normalize_text(model_state).lower()
    if activation_key in {"inactive", "reserved"}:
        return []
    if binding_source_key in {"system_fixed", "reserved"}:
        return []
    if binding_source_key == "auto_exact" or model_state_key == "exact":
        return []

    option_ids = MODULE_OPTIONS_BY_CLASS.get(_normalize_text(module_class).lower())
    if option_ids is None:
        option_ids = MODULE_OPTIONS_BY_PROTOCOL.get(_normalize_text(port_type).lower(), [])
    options = [
        copy.deepcopy(MODULE_BINDING_OPTIONS[option_id])
        for option_id in option_ids
        if option_id in MODULE_BINDING_OPTIONS
    ]
    exact_option = _dynamic_exact_option(module_class, module_type)
    if exact_option and not any(item.get("module_type") == exact_option["module_type"] for item in options):
        options.append(exact_option)
    return options


def _confirmation_hint(
    *,
    has_user_binding: bool,
    activation: str,
    model_state: str,
    binding_source: str,
) -> str:
    if has_user_binding:
        return "已记录当前口的模块确认，后续同一模块可直接继承。"
    activation_key = _normalize_text(activation).lower()
    model_state_key = _normalize_text(model_state).lower()
    binding_source_key = _normalize_text(binding_source).lower()
    if activation_key == "channel_active":
        return "通道已激活，但具体模块还未确认。"
    if model_state_key in {"candidate", "unknown"}:
        return "系统已识别到模块能力，请从名单中确认具体器件。"
    if binding_source_key == "user_confirmed":
        return "当前模块来自人工配置，如已更换硬件请重新确认。"
    return "可在这里补充模块类型，便于网页和后端统一理解。"


def _confirmation_state(
    *,
    has_user_binding: bool,
    activation: str,
    model_state: str,
    binding_source: str,
) -> str:
    if has_user_binding:
        return "user_confirmed"
    binding_source_key = _normalize_text(binding_source).lower()
    model_state_key = _normalize_text(model_state).lower()
    activation_key = _normalize_text(activation).lower()
    if binding_source_key == "auto_exact" or model_state_key == "exact":
        return "auto_exact"
    if activation_key == "channel_active" or model_state_key in {"candidate", "unknown"}:
        return "pending"
    return "reported"


def _binding_key_for_metadata(metadata: JsonObject, port_id: str) -> str:
    return _normalize_text(metadata.get("device_key") or metadata.get("binding_key") or port_id, fallback=port_id)


def _binding_index(bindings: list[JsonObject]) -> tuple[dict[tuple[str, str], JsonObject], dict[str, JsonObject]]:
    exact: dict[tuple[str, str], JsonObject] = {}
    fallback: dict[str, JsonObject] = {}
    for record in sorted(bindings, key=lambda item: int(item.get("updated_at") or 0), reverse=True):
        port_id = _normalize_text(record.get("port_id"))
        binding_key = _normalize_text(record.get("binding_key"), fallback=port_id)
        if not port_id:
            continue
        exact.setdefault((port_id, binding_key), record)
        fallback.setdefault(port_id, record)
    return exact, fallback


def resolve_module_binding(bindings: list[JsonObject], *, port_id: str, binding_key: str) -> JsonObject | None:
    exact, fallback = _binding_index(bindings)
    record = exact.get((port_id, binding_key))
    if record is not None:
        return copy.deepcopy(record)
    if binding_key != port_id:
        record = exact.get((port_id, port_id))
        if record is not None:
            return copy.deepcopy(record)
    fallback_record = fallback.get(port_id)
    return copy.deepcopy(fallback_record) if fallback_record is not None else None


def module_binding_public_view(record: JsonObject | None) -> JsonObject | None:
    if not record:
        return None
    module_class = _normalize_text(record.get("module_class"))
    title = _normalize_text(record.get("title"), fallback=module_class_label(module_class))
    model_label = _normalize_text(record.get("model_label"), fallback=_normalize_text(record.get("module_type")))
    return {
        "option_id": _normalize_text(record.get("option_id")),
        "port_id": _normalize_text(record.get("port_id")),
        "binding_key": _normalize_text(record.get("binding_key")),
        "module_class": module_class,
        "module_type": _normalize_text(record.get("module_type")),
        "title": title,
        "model_label": model_label,
        "generic": _bool_flag(record.get("generic")),
        "confirmed_by": _normalize_text(record.get("confirmed_by")),
        "updated_at": int(record.get("updated_at") or 0),
    }


def apply_bindings_to_signal_topology(topology: JsonObject, bindings: list[JsonObject]) -> JsonObject:
    result = copy.deepcopy(topology if isinstance(topology, dict) else {})
    channels = result.get("channels")
    if not isinstance(channels, list):
        return result

    for channel in channels:
        if not isinstance(channel, dict):
            continue
        state = channel.get("state")
        state = state if isinstance(state, dict) else {}
        hardware = channel.get("hardware")
        hardware = hardware if isinstance(hardware, list) else []
        channel_pending = False
        for endpoint in hardware:
            if not isinstance(endpoint, dict):
                continue
            metadata = endpoint.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            port_id = _normalize_text(metadata.get("port_id") or channel.get("id"))
            if not port_id:
                continue
            raw_module_class = _normalize_text(metadata.get("module_class") or state.get("interpretation"))
            raw_module_type = _normalize_text(endpoint.get("hardware_type"))
            raw_model_state = _normalize_text(metadata.get("model_state"))
            raw_binding_source = _normalize_text(metadata.get("binding_source"))
            activation = _normalize_text(metadata.get("activation") or state.get("activation"))
            binding_key = _binding_key_for_metadata(metadata, port_id)
            binding = resolve_module_binding(bindings, port_id=port_id, binding_key=binding_key)
            user_binding = module_binding_public_view(binding)
            options = module_binding_options(
                port_type=_normalize_text(channel.get("protocol")).lower(),
                activation=activation,
                module_class=raw_module_class,
                module_type=raw_module_type,
                binding_source=raw_binding_source,
                model_state=raw_model_state,
            )
            display_title = module_class_label(raw_module_class) if raw_module_class else raw_module_type or "待识别模块"
            display_model = raw_module_type if raw_module_type and display_title != raw_module_type else ""
            if user_binding:
                display_title = _normalize_text(user_binding.get("title"), fallback=display_title)
                display_model = _normalize_text(user_binding.get("model_label"), fallback=display_model)
            needs_confirmation = bool(options) and user_binding is None
            channel_pending = channel_pending or needs_confirmation
            metadata["reported_module_class"] = raw_module_class
            metadata["reported_module_type"] = raw_module_type
            metadata["reported_model_state"] = raw_model_state
            metadata["reported_binding_source"] = raw_binding_source
            metadata["binding_key"] = binding_key
            metadata["binding_options"] = options
            metadata["can_confirm_module"] = bool(options)
            metadata["needs_user_confirmation"] = needs_confirmation
            metadata["confirmation_state"] = _confirmation_state(
                has_user_binding=user_binding is not None,
                activation=activation,
                model_state=raw_model_state,
                binding_source=raw_binding_source,
            )
            metadata["confirmation_hint"] = _confirmation_hint(
                has_user_binding=user_binding is not None,
                activation=activation,
                model_state=raw_model_state,
                binding_source=raw_binding_source,
            )
            metadata["display_title"] = display_title
            metadata["display_model"] = display_model
            metadata["user_binding"] = user_binding
            endpoint["metadata"] = metadata
        state["needs_user_confirmation"] = channel_pending
        channel["state"] = state
        channel["hardware"] = hardware
    result["module_bindings"] = [
        view for view in (module_binding_public_view(item) for item in bindings) if view is not None
    ]
    return result


def apply_bindings_to_diagnostics(diagnostics: JsonObject, bindings: list[JsonObject]) -> JsonObject:
    result = copy.deepcopy(diagnostics if isinstance(diagnostics, dict) else {})
    registry = result.get("hardware_registry")
    if isinstance(registry, dict):
        ports = registry.get("ports")
        if isinstance(ports, list):
            for port in ports:
                if not isinstance(port, dict):
                    continue
                port_id = _normalize_text(port.get("id"))
                module = port.get("module")
                module = module if isinstance(module, dict) else {}
                binding_key = _normalize_text(module.get("device_key"), fallback=port_id)
                binding = resolve_module_binding(bindings, port_id=port_id, binding_key=binding_key)
                if binding is not None:
                    module["user_binding"] = module_binding_public_view(binding)
                options = module_binding_options(
                    port_type=_normalize_text(port.get("type")),
                    activation=_normalize_text(port.get("activation")),
                    module_class=_normalize_text(module.get("module_class")),
                    module_type=_normalize_text(module.get("module_type")),
                    binding_source=_normalize_text(module.get("binding_source")),
                    model_state=_normalize_text(module.get("model_state")),
                )
                if options:
                    module["binding_options"] = options
                port["module"] = module
        devices = registry.get("devices")
        if isinstance(devices, list):
            for device in devices:
                if not isinstance(device, dict):
                    continue
                port_id = _normalize_text(device.get("bus"))
                binding_key = _normalize_text(device.get("device_key"), fallback=port_id)
                binding = resolve_module_binding(bindings, port_id=port_id, binding_key=binding_key)
                if binding is not None:
                    device["user_binding"] = module_binding_public_view(binding)
        registry["module_bindings"] = [
            view for view in (module_binding_public_view(item) for item in bindings) if view is not None
        ]
        result["hardware_registry"] = registry
    result["module_bindings"] = [
        view for view in (module_binding_public_view(item) for item in bindings) if view is not None
    ]
    return result


class ModuleBindingStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._db_path = Path(settings.module_binding_db_path)
        if not self._db_path.is_absolute():
            self._db_path = Path(__file__).resolve().parents[1] / self._db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS module_bindings (
                    device_id TEXT NOT NULL,
                    port_id TEXT NOT NULL,
                    binding_key TEXT NOT NULL,
                    option_id TEXT NOT NULL,
                    module_class TEXT NOT NULL DEFAULT '',
                    module_type TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    model_label TEXT NOT NULL DEFAULT '',
                    generic INTEGER NOT NULL DEFAULT 0,
                    confirmed_by TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY(device_id, port_id, binding_key)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_module_bindings_device ON module_bindings(device_id, updated_at DESC)"
            )

    def list_for_device(self, device_id: str) -> list[JsonObject]:
        clean_device_id = _clean_token(device_id, max_length=64)
        if not clean_device_id:
            return []
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM module_bindings
                WHERE device_id = ?
                ORDER BY updated_at DESC, port_id ASC, binding_key ASC
                """,
                (clean_device_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def confirm(
        self,
        *,
        device_id: str,
        port_id: str,
        binding_key: str,
        option_id: str,
        confirmed_by: str,
    ) -> JsonObject:
        clean_device_id = _clean_token(device_id, max_length=64)
        clean_port_id = _clean_token(port_id, max_length=64)
        clean_binding_key = _clean_token(binding_key or port_id, max_length=128) or clean_port_id
        clean_confirmed_by = _clean_token(confirmed_by, max_length=80)
        option = module_binding_option(option_id)
        if not clean_device_id or not clean_port_id:
            raise ValueError("device_id and port_id are required")
        if option is None:
            raise ValueError("unsupported module binding option")
        now = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO module_bindings (
                    device_id, port_id, binding_key, option_id, module_class, module_type,
                    title, model_label, generic, confirmed_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id, port_id, binding_key) DO UPDATE SET
                    option_id = excluded.option_id,
                    module_class = excluded.module_class,
                    module_type = excluded.module_type,
                    title = excluded.title,
                    model_label = excluded.model_label,
                    generic = excluded.generic,
                    confirmed_by = excluded.confirmed_by,
                    updated_at = excluded.updated_at
                """,
                (
                    clean_device_id,
                    clean_port_id,
                    clean_binding_key,
                    option["id"],
                    option["module_class"],
                    option["module_type"],
                    option["title"],
                    option["model_label"],
                    1 if option.get("generic") else 0,
                    clean_confirmed_by,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM module_bindings
                WHERE device_id = ? AND port_id = ? AND binding_key = ?
                """,
                (clean_device_id, clean_port_id, clean_binding_key),
            ).fetchone()
        return dict(row) if row else {}
