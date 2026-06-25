from __future__ import annotations

import hashlib
import secrets
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


def _default_label(device_id: str) -> str:
    return device_id.replace("_", " ")


class DeviceRegistry:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._db_path = Path(settings.device_registry_db_path)
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
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    ra8p1_uid TEXT NOT NULL DEFAULT '',
                    esp32_mac TEXT NOT NULL DEFAULT '',
                    esp32_chip_id TEXT NOT NULL DEFAULT '',
                    device_secret TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'registered',
                    status TEXT NOT NULL DEFAULT 'registered',
                    first_seen INTEGER NOT NULL,
                    last_seen INTEGER,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_devices_ra8p1_uid ON devices(ra8p1_uid)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_devices_esp32_mac ON devices(esp32_mac)")

    def ensure_default_device(self) -> JsonObject:
        device_id = _clean_token(self._settings.device_id, max_length=64) or "ra8p1_demo_001"
        now = _now()
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO devices (
                        device_id, label, source, status, first_seen, last_seen, created_at, updated_at
                    ) VALUES (?, ?, 'default', 'registered', ?, NULL, ?, ?)
                    """,
                    (device_id, _default_label(device_id), now, now, now),
                )
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        return self._row_to_dict(row, include_secret=True) if row else {"device_id": device_id}

    def list_devices(self) -> list[JsonObject]:
        self.ensure_default_device()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM devices
                ORDER BY COALESCE(last_seen, first_seen, created_at) DESC, device_id ASC
                """
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get(self, device_id: str) -> JsonObject | None:
        clean_id = _clean_token(device_id, max_length=64)
        if not clean_id:
            return None
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM devices WHERE device_id = ?", (clean_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def register(
        self,
        *,
        ra8p1_uid: str = "",
        esp32_mac: str = "",
        esp32_chip_id: str = "",
        label: str = "",
    ) -> JsonObject:
        clean_uid = _clean_token(ra8p1_uid.upper(), max_length=64)
        clean_mac = _clean_token(esp32_mac.upper(), max_length=32)
        clean_chip_id = _clean_token(esp32_chip_id.upper(), max_length=64)
        if not clean_uid and not clean_mac and not clean_chip_id:
            raise ValueError("ra8p1_uid, esp32_mac or esp32_chip_id is required")

        fingerprint = "|".join([clean_uid, clean_mac, clean_chip_id])
        device_id = "ra8p1_" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12]
        now = _now()
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
            if row is None:
                device_secret = secrets.token_urlsafe(24)
                connection.execute(
                    """
                    INSERT INTO devices (
                        device_id, label, ra8p1_uid, esp32_mac, esp32_chip_id, device_secret,
                        source, status, first_seen, last_seen, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'self_registered', 'registered', ?, NULL, ?, ?)
                    """,
                    (
                        device_id,
                        label.strip()[:80] or _default_label(device_id),
                        clean_uid,
                        clean_mac,
                        clean_chip_id,
                        device_secret,
                        now,
                        now,
                        now,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE devices
                    SET label = COALESCE(NULLIF(?, ''), label),
                        ra8p1_uid = COALESCE(NULLIF(?, ''), ra8p1_uid),
                        esp32_mac = COALESCE(NULLIF(?, ''), esp32_mac),
                        esp32_chip_id = COALESCE(NULLIF(?, ''), esp32_chip_id),
                        status = 'registered',
                        updated_at = ?
                    WHERE device_id = ?
                    """,
                    (label.strip()[:80], clean_uid, clean_mac, clean_chip_id, now, device_id),
                )
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        return self._row_to_dict(row, include_secret=True) if row else {"device_id": device_id}

    def touch_observed(self, device_id: str, *, source: str = "mqtt") -> JsonObject:
        clean_id = _clean_token(device_id, max_length=64)
        if not clean_id:
            raise ValueError("device_id is required")
        now = _now()
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM devices WHERE device_id = ?", (clean_id,)).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO devices (
                        device_id, label, source, status, first_seen, last_seen, created_at, updated_at
                    ) VALUES (?, ?, ?, 'observed', ?, ?, ?, ?)
                    """,
                    (clean_id, _default_label(clean_id), source, now, now, now, now),
                )
            else:
                connection.execute(
                    "UPDATE devices SET last_seen = ?, status = 'registered', updated_at = ? WHERE device_id = ?",
                    (now, now, clean_id),
                )
        return self.get(clean_id) or {"device_id": clean_id}

    def _row_to_dict(self, row: sqlite3.Row, *, include_secret: bool = False) -> JsonObject:
        data = dict(row)
        data["has_secret"] = bool(data.get("device_secret"))
        if not include_secret:
            data.pop("device_secret", None)
        return data
