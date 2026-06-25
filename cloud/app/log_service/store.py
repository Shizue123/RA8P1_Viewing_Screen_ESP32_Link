from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


JsonObject = dict[str, Any]


def _resolve_db_path(db_path: str) -> str:
    if db_path == ":temp:":
        return str(Path(tempfile.gettempdir()) / "embedded_agent_cloud.sqlite3")
    return db_path


class PersistentLogStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = _resolve_db_path(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def record_deploy(
        self,
        *,
        request_id: str,
        device_id: str,
        topic: str,
        intent: JsonObject,
        message: JsonObject,
        lua_validation: JsonObject,
        mqtt_enabled: bool,
        published: bool,
    ) -> None:
        payload = message.get("payload")
        deploy_payload = payload if isinstance(payload, dict) else {}
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO deployments (
                    request_id, device_id, script_id, topic, intent_json, lua_code,
                    mqtt_message_json, lua_validation_json, mqtt_enabled, published,
                    ack_received, ack_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    device_id=excluded.device_id,
                    script_id=excluded.script_id,
                    topic=excluded.topic,
                    intent_json=excluded.intent_json,
                    lua_code=excluded.lua_code,
                    mqtt_message_json=excluded.mqtt_message_json,
                    lua_validation_json=excluded.lua_validation_json,
                    mqtt_enabled=excluded.mqtt_enabled,
                    published=excluded.published,
                    updated_at=excluded.updated_at
                """,
                (
                    request_id,
                    device_id,
                    str(deploy_payload.get("script_id", "")),
                    topic,
                    _dump(intent),
                    str(deploy_payload.get("lua_code", "")),
                    _dump(message),
                    _dump(lua_validation),
                    int(mqtt_enabled),
                    int(published),
                    _now(),
                    _now(),
                ),
            )
            self._conn.commit()

    def record_ack(self, device_id: str, ack: JsonObject) -> None:
        request_id = str(ack.get("request_id", ""))
        if not request_id:
            return
        with self._lock:
            self._conn.execute(
                """
                UPDATE deployments
                SET ack_received=1, ack_json=?, updated_at=?
                WHERE request_id=? AND device_id=?
                """,
                (_dump(ack), _now(), request_id, device_id),
            )
            self._conn.commit()

    def record_device_message(self, *, topic: str, device_id: str, channel: str, message: JsonObject) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO device_messages (
                    request_id, device_id, channel, topic, message_type, message_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(message.get("request_id", "")),
                    device_id,
                    channel,
                    topic,
                    str(message.get("type", "")),
                    _dump(message),
                    _now(),
                ),
            )
            self._conn.commit()

    def record_agent_run(
        self,
        *,
        request_id: str,
        device_id: str,
        route: str,
        user_text: str,
        source: str,
        confidence: float,
        knowledge_snapshot: JsonObject,
        plan: JsonObject,
        deployment: JsonObject | None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO agent_runs (
                    request_id, device_id, route, user_text, source, confidence,
                    knowledge_snapshot_json, plan_json, deployment_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    device_id=excluded.device_id,
                    route=excluded.route,
                    user_text=excluded.user_text,
                    source=excluded.source,
                    confidence=excluded.confidence,
                    knowledge_snapshot_json=excluded.knowledge_snapshot_json,
                    plan_json=excluded.plan_json,
                    deployment_json=excluded.deployment_json,
                    updated_at=excluded.updated_at
                """,
                (
                    request_id,
                    device_id,
                    route,
                    user_text,
                    source,
                    float(confidence),
                    _dump(knowledge_snapshot),
                    _dump(plan),
                    _dump(deployment),
                    _now(),
                    _now(),
                ),
            )
            self._conn.commit()

    def get_deployment(self, request_id: str) -> JsonObject | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM deployments WHERE request_id=?",
                (request_id,),
            ).fetchone()
        return _deployment_row(row) if row else None

    def list_deployments(self, limit: int = 20) -> list[JsonObject]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM deployments ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_deployment_row(row) for row in rows]

    def list_device_messages(self, device_id: str, limit: int = 50, channel: str | None = None) -> list[JsonObject]:
        if channel:
            sql = "SELECT * FROM device_messages WHERE device_id=? AND channel=? ORDER BY created_at DESC LIMIT ?"
            args: tuple[Any, ...] = (device_id, channel, limit)
        else:
            sql = "SELECT * FROM device_messages WHERE device_id=? ORDER BY created_at DESC LIMIT ?"
            args = (device_id, limit)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [_device_message_row(row) for row in rows]

    def get_agent_run(self, request_id: str) -> JsonObject | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM agent_runs WHERE request_id=?",
                (request_id,),
            ).fetchone()
        return _agent_run_row(row) if row else None

    def list_agent_runs(self, limit: int = 20) -> list[JsonObject]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agent_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_agent_run_row(row) for row in rows]

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deployments (
                    request_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    script_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    intent_json TEXT NOT NULL,
                    lua_code TEXT NOT NULL,
                    mqtt_message_json TEXT NOT NULL,
                    lua_validation_json TEXT NOT NULL,
                    mqtt_enabled INTEGER NOT NULL,
                    published INTEGER NOT NULL,
                    ack_received INTEGER NOT NULL,
                    ack_json TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS device_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    message_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_device_messages_device_time ON device_messages(device_id, created_at)"
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_device_messages_request ON device_messages(request_id)")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    request_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    route TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    knowledge_snapshot_json TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    deployment_json TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_device_time ON agent_runs(device_id, created_at)")
            self._conn.commit()


def _now() -> int:
    return int(time.time())


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(value: str | None) -> object:
    if not value:
        return None
    return json.loads(value)


def _deployment_row(row: sqlite3.Row) -> JsonObject:
    return {
        "request_id": row["request_id"],
        "device_id": row["device_id"],
        "script_id": row["script_id"],
        "topic": row["topic"],
        "intent": _load(row["intent_json"]),
        "lua_code": row["lua_code"],
        "mqtt_message": _load(row["mqtt_message_json"]),
        "lua_validation": _load(row["lua_validation_json"]),
        "mqtt_enabled": bool(row["mqtt_enabled"]),
        "published": bool(row["published"]),
        "ack_received": bool(row["ack_received"]),
        "ack": _load(row["ack_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _device_message_row(row: sqlite3.Row) -> JsonObject:
    return {
        "id": row["id"],
        "request_id": row["request_id"],
        "device_id": row["device_id"],
        "channel": row["channel"],
        "topic": row["topic"],
        "message_type": row["message_type"],
        "message": _load(row["message_json"]),
        "created_at": row["created_at"],
    }


def _agent_run_row(row: sqlite3.Row) -> JsonObject:
    return {
        "request_id": row["request_id"],
        "device_id": row["device_id"],
        "route": row["route"],
        "user_text": row["user_text"],
        "source": row["source"],
        "confidence": row["confidence"],
        "knowledge_snapshot": _load(row["knowledge_snapshot_json"]),
        "plan": _load(row["plan_json"]),
        "deployment": _load(row["deployment_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
