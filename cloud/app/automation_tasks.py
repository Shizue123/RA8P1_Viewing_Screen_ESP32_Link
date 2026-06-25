from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta

from cloud.app.config import Settings
from cloud.app.device_state.store import device_state_store


JsonObject = dict[str, Any]
_LOCAL_TZ = ZoneInfo("Asia/Shanghai")
_SERVICES: dict[str, "AutomationTaskService"] = {}
_SERVICES_LOCK = threading.Lock()


def get_automation_task_service(settings: Settings) -> "AutomationTaskService":
    key = str(Path(settings.automation_task_db_path).resolve())
    with _SERVICES_LOCK:
        service = _SERVICES.get(key)
        if service is None:
            service = AutomationTaskService(settings)
            _SERVICES[key] = service
        return service


def close_automation_task_service(settings: Settings) -> None:
    key = str(Path(settings.automation_task_db_path).resolve())
    with _SERVICES_LOCK:
        service = _SERVICES.pop(key, None)
    if service is not None:
        service.close()


class AutomationTaskService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db_path = settings.automation_task_db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._init_db()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="automation-tasks", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def close(self) -> None:
        self.stop()
        with self._lock:
            self._conn.close()

    def create_task(
        self,
        *,
        owner_channel: str,
        owner_id: str,
        conversation_id: str,
        device_id: str,
        task_type: str,
        name: str,
        spec: JsonObject,
        schedule_kind: str = "",
        next_run_at: int | None = None,
        survives_conversation: bool = False,
    ) -> JsonObject:
        task_id = "task_" + uuid.uuid4().hex[:12]
        now = int(time.time())
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO automation_tasks (
                    task_id, owner_channel, owner_id, conversation_id, device_id,
                    task_type, name, spec_json, schedule_kind, next_run_at,
                    last_run_at, last_condition, enabled, last_result_json,
                    survives_conversation, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, 1, NULL, ?, ?, ?)
                """,
                (
                    task_id,
                    owner_channel,
                    owner_id,
                    conversation_id,
                    device_id,
                    task_type,
                    name[:160],
                    json.dumps(spec, ensure_ascii=False, sort_keys=True),
                    schedule_kind,
                    next_run_at,
                    int(survives_conversation),
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return self.get_task(task_id) or {}

    def get_task(self, task_id: str) -> JsonObject | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM automation_tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
        return _task_row(row) if row else None

    def list_tasks(self, owner_channel: str, owner_id: str, *, enabled_only: bool = True) -> list[JsonObject]:
        where = "owner_channel=? AND owner_id=?"
        args: list[object] = [owner_channel, owner_id]
        if enabled_only:
            where += " AND enabled=1"
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM automation_tasks WHERE {where} ORDER BY created_at DESC",
                tuple(args),
            ).fetchall()
        return [_task_row(row) for row in rows]

    def latest_conversation_task(
        self,
        owner_channel: str,
        owner_id: str,
        conversation_id: str,
    ) -> JsonObject | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM automation_tasks
                WHERE owner_channel=? AND owner_id=? AND conversation_id=?
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (owner_channel, owner_id, conversation_id),
            ).fetchone()
        return _task_row(row) if row else None

    def update_task(
        self,
        task_id: str,
        owner_channel: str,
        owner_id: str,
        *,
        spec: JsonObject | None = None,
        schedule_kind: str | None = None,
        next_run_at: int | None = None,
        survives_conversation: bool | None = None,
        enabled: bool = True,
    ) -> JsonObject | None:
        task = self.get_task(task_id)
        if (
            task is None
            or task["owner_channel"] != owner_channel
            or task["owner_id"] != owner_id
        ):
            return None
        updates = ["enabled=?", "updated_at=?"]
        values: list[object] = [int(enabled), int(time.time())]
        if spec is not None:
            updates.append("spec_json=?")
            values.append(json.dumps(spec, ensure_ascii=False, sort_keys=True))
        if schedule_kind is not None:
            updates.append("schedule_kind=?")
            values.append(schedule_kind)
        if next_run_at is not None:
            updates.append("next_run_at=?")
            values.append(next_run_at)
        if survives_conversation is not None:
            updates.append("survives_conversation=?")
            values.append(int(survives_conversation))
        values.extend([task_id, owner_channel, owner_id])
        with self._lock:
            self._conn.execute(
                f"""
                UPDATE automation_tasks SET {", ".join(updates)}
                WHERE task_id=? AND owner_channel=? AND owner_id=?
                """,
                tuple(values),
            )
            self._conn.commit()
        return self.get_task(task_id)

    def cancel_task(self, task_id: str, owner_channel: str, owner_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE automation_tasks SET enabled=0, updated_at=?
                WHERE task_id=? AND owner_channel=? AND owner_id=? AND enabled=1
                """,
                (int(time.time()), task_id, owner_channel, owner_id),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def cancel_conversation_tasks(
        self,
        owner_channel: str,
        owner_id: str,
        conversation_id: str,
    ) -> int:
        now = int(time.time())
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE automation_tasks SET enabled=0, updated_at=?
                WHERE owner_channel=? AND owner_id=? AND conversation_id=?
                  AND survives_conversation=0 AND enabled=1
                """,
                (now, owner_channel, owner_id, conversation_id),
            )
            self._conn.execute(
                """
                DELETE FROM automation_preferences
                WHERE owner_channel=? AND owner_id=? AND conversation_id=?
                """,
                (owner_channel, owner_id, conversation_id),
            )
            self._conn.commit()
        return cursor.rowcount

    def servo_auto_reset_preference(
        self,
        owner_channel: str,
        owner_id: str,
        conversation_id: str,
    ) -> bool:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT servo_auto_reset FROM automation_preferences
                WHERE owner_channel=? AND owner_id=? AND conversation_id=?
                """,
                (owner_channel, owner_id, conversation_id),
            ).fetchone()
        return bool(row["servo_auto_reset"]) if row else False

    def set_servo_auto_reset_preference(
        self,
        owner_channel: str,
        owner_id: str,
        conversation_id: str,
        enabled: bool,
    ) -> None:
        now = int(time.time())
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO automation_preferences (
                    owner_channel, owner_id, conversation_id, servo_auto_reset, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(owner_channel, owner_id, conversation_id)
                DO UPDATE SET servo_auto_reset=excluded.servo_auto_reset,
                              updated_at=excluded.updated_at
                """,
                (owner_channel, owner_id, conversation_id, int(enabled), now),
            )
            self._conn.commit()

    def run_once(self, now: int | None = None) -> None:
        now = int(now or time.time())
        for task in self._enabled_tasks():
            try:
                if task["task_type"] == "sensor_rule":
                    self._evaluate_sensor_rule(task, now)
                elif task["task_type"] == "scheduled_report":
                    self._evaluate_scheduled_report(task, now)
                elif task["task_type"] == "scheduled_action":
                    self._evaluate_scheduled_action(task, now)
            except Exception as exc:
                self._record_result(task["task_id"], {"ok": False, "error": str(exc)}, now)

    def _run(self) -> None:
        while not self._stop.wait(1.0):
            self.run_once()

    def _enabled_tasks(self) -> list[JsonObject]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM automation_tasks WHERE enabled=1 ORDER BY created_at"
            ).fetchall()
        return [_task_row(row) for row in rows]

    def _evaluate_sensor_rule(self, task: JsonObject, now: int) -> None:
        spec = task["spec"]
        observation = _latest_capability_value(task["device_id"], str(spec["capability"]))
        if observation is None:
            self._set_condition(task["task_id"], False, now)
            return
        condition_met = _compare(
            float(observation["value"]),
            str(spec["operator"]),
            float(spec["value"]),
        )
        last_condition = bool(task["last_condition"])
        self._set_condition(task["task_id"], condition_met, now)
        if not condition_met or last_condition:
            return
        cooldown_sec = max(0, int(spec.get("cooldown_sec") or 30))
        last_run_at = task.get("last_run_at")
        if isinstance(last_run_at, int) and now - last_run_at < cooldown_sec:
            return
        result = self._execute_servo(task, observation)
        self._record_result(task["task_id"], result, now)

    def _evaluate_scheduled_report(self, task: JsonObject, now: int) -> None:
        next_run_at = task.get("next_run_at")
        if not isinstance(next_run_at, int) or now < next_run_at:
            return
        result = self._deliver_report(task)
        schedule_kind = str(task.get("schedule_kind") or "once")
        if schedule_kind == "daily":
            next_time = _next_daily_run(str(task["spec"]["local_time"]), now + 1)
            self._record_result(task["task_id"], result, now, next_run_at=next_time)
        else:
            self._record_result(task["task_id"], result, now, enabled=False)

    def _evaluate_scheduled_action(self, task: JsonObject, now: int) -> None:
        next_run_at = task.get("next_run_at")
        if not isinstance(next_run_at, int) or now < next_run_at:
            return
        result = self._execute_servo(task, {"source": "scheduled_time", "value": now})
        if str(task.get("schedule_kind") or "once") == "daily":
            next_time = _next_daily_run(str(task["spec"]["local_time"]), now + 1)
            self._record_result(task["task_id"], result, now, next_run_at=next_time)
        else:
            self._record_result(task["task_id"], result, now, enabled=False)

    def _execute_servo(self, task: JsonObject, observation: JsonObject) -> JsonObject:
        from cloud.app.api.web_routes import _deploy_manual_action

        spec = task["spec"]
        settings = self.settings.model_copy(
            update={
                "device_id": task["device_id"],
                "web_hardware_wait_for_ack": False,
            }
        )
        response = _deploy_manual_action(
            {
                "angle": int(spec["angle"]),
                "times": int(spec["times"]),
                "duration_ms": int(spec.get("duration_ms") or 350),
                "direction": str(spec.get("direction") or "both"),
                "auto_reset": bool(spec.get("auto_reset")),
            },
            settings,
            source=f"automation_task:{task['task_id']}",
            confidence=1.0,
            reasoning_summary=(
                (
                    f"{spec['capability']} {spec['operator']} {spec['value']} "
                    f"matched live value {observation['value']}"
                )
                if task["task_type"] == "sensor_rule"
                else f"scheduled execution at {spec.get('local_time')}"
            ),
        )
        return {
            "ok": True,
            "observation": observation,
            "deployment": response.get("hardware_control", {}).get("deployment"),
        }

    def _deliver_report(self, task: JsonObject) -> JsonObject:
        from cloud.app.api.web_routes import (
            WebObservationQuery,
            _build_observation_query_response,
        )

        settings = self.settings.model_copy(update={"device_id": task["device_id"]})
        requested_capabilities = [
            str(item)
            for item in task["spec"].get(
                "capabilities",
                ["env.temperature", "env.humidity", "env.light.lux"],
            )
            if str(item) in {"env.temperature", "env.humidity", "env.light.lux"}
        ]
        if not requested_capabilities:
            requested_capabilities = ["env.temperature", "env.humidity", "env.light.lux"]
        requested_devices: list[str] = []
        if any(item in requested_capabilities for item in ("env.temperature", "env.humidity")):
            requested_devices.append("AHT20")
        if "env.light.lux" in requested_capabilities:
            requested_devices.append("BH1750")
        response = _build_observation_query_response(
            settings,
            query=WebObservationQuery(
                devices=requested_devices,
                capabilities=requested_capabilities,
            ),
            source=f"automation_task:{task['task_id']}",
            confidence=1.0,
        )
        message = str(response.get("assistant_message") or "定时环境汇报暂时没有可用数据。")
        prefix = f"【任务 {task['name']}】"
        content = f"{prefix}\n{message}"
        channel = str(task["owner_channel"])
        if channel == "web":
            from cloud.app.auth import AuthStore

            store = AuthStore(self.settings)
            try:
                store.append_chat_message(
                    int(task["owner_id"]),
                    task["conversation_id"],
                    "assistant",
                    content,
                )
            except Exception:
                if not task.get("survives_conversation"):
                    raise
                conversation = store.create_conversation(
                    int(task["owner_id"]),
                    title=f"长期任务：{task['name']}"[:80],
                )
                replacement_id = str(conversation["id"])
                self._update_conversation_id(task["task_id"], replacement_id)
                store.append_chat_message(
                    int(task["owner_id"]),
                    replacement_id,
                    "assistant",
                    content,
                )
        elif channel in {"qq_c2c", "qq_group"}:
            from cloud.app.qqbot import qqbot_send_proactive_text

            qqbot_send_proactive_text(
                channel=channel,
                target_id=task["conversation_id"],
                content=content,
                settings=self.settings,
            )
        return {"ok": True, "message": content}

    def _set_condition(self, task_id: str, value: bool, now: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE automation_tasks SET last_condition=?, updated_at=? WHERE task_id=?",
                (int(value), now, task_id),
            )
            self._conn.commit()

    def _record_result(
        self,
        task_id: str,
        result: JsonObject,
        now: int,
        *,
        enabled: bool | None = None,
        next_run_at: int | None = None,
    ) -> None:
        updates = ["last_run_at=?", "last_result_json=?", "updated_at=?"]
        values: list[object] = [now, json.dumps(result, ensure_ascii=False), now]
        if enabled is not None:
            updates.append("enabled=?")
            values.append(int(enabled))
        if next_run_at is not None:
            updates.append("next_run_at=?")
            values.append(next_run_at)
        values.append(task_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE automation_tasks SET {', '.join(updates)} WHERE task_id=?",
                tuple(values),
            )
            self._conn.commit()

    def _update_conversation_id(self, task_id: str, conversation_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE automation_tasks SET conversation_id=?, updated_at=? WHERE task_id=?",
                (conversation_id, int(time.time()), task_id),
            )
            self._conn.commit()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS automation_tasks (
                    task_id TEXT PRIMARY KEY,
                    owner_channel TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    schedule_kind TEXT NOT NULL,
                    next_run_at INTEGER,
                    last_run_at INTEGER,
                    last_condition INTEGER NOT NULL,
                    enabled INTEGER NOT NULL,
                    last_result_json TEXT,
                    survives_conversation INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_automation_owner ON automation_tasks(owner_channel, owner_id, enabled)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_automation_due ON automation_tasks(enabled, next_run_at)"
            )
            columns = {
                str(row["name"])
                for row in self._conn.execute("PRAGMA table_info(automation_tasks)").fetchall()
            }
            if "survives_conversation" not in columns:
                self._conn.execute(
                    "ALTER TABLE automation_tasks ADD COLUMN survives_conversation INTEGER NOT NULL DEFAULT 0"
                )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS automation_preferences (
                    owner_channel TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    servo_auto_reset INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY(owner_channel, owner_id, conversation_id)
                )
                """
            )
            self._conn.commit()


def automation_task_from_text(text: str, *, now: int | None = None) -> JsonObject | None:
    normalized = text.strip().lower().replace("，", ",").replace("。", ".")
    if any(token in normalized for token in ("查看任务", "任务列表", "有哪些任务", "列出任务")):
        return {"operation": "list"}
    cancel_match = re.search(r"(?:取消|删除|停止)\s*(task_[a-f0-9]{6,12})", normalized)
    if cancel_match:
        return {"operation": "cancel", "task_id": cancel_match.group(1)}

    has_clock = _extract_clock(normalized)[0] is not None
    if has_clock and any(token in normalized for token in ("舵机", "sg90", "servo")):
        schedule = _parse_schedule(normalized, now=now)
        if schedule.get("operation") == "clarify":
            return schedule
        action = _parse_servo_action(normalized)
        return {
            "operation": "create",
            "task_type": "scheduled_action",
            "name": f"{schedule['schedule_kind']} {schedule['spec']['local_time']} SG90定时动作",
            "survives_conversation": bool(schedule["survives_conversation"]),
            "schedule_kind": schedule["schedule_kind"],
            "next_run_at": schedule["next_run_at"],
            "spec": {
                **schedule["spec"],
                **action,
                "auto_reset": _explicit_auto_reset(normalized),
            },
        }

    if has_clock and any(token in normalized for token in ("汇报", "报告", "上报", "告诉我")):
        schedule = _parse_report_schedule(normalized, now=now)
        if schedule:
            if schedule.get("operation") == "clarify":
                return schedule
            return {"operation": "create", "task_type": "scheduled_report", **schedule}

    condition = _parse_sensor_condition(normalized)
    if condition and any(token in normalized for token in ("舵机", "sg90", "servo")):
        action = _parse_servo_action(normalized)
        return {
            "operation": "create",
            "task_type": "sensor_rule",
            "name": _task_name(condition, action),
            "survives_conversation": _long_lived_intent(normalized),
            "spec": {
                **condition,
                **action,
                "auto_reset": _explicit_auto_reset(normalized),
                "cooldown_sec": 30,
            },
        }
    return None


def contextual_automation_task_from_text(
    text: str,
    *,
    conversation_history: list[JsonObject],
    latest_task: JsonObject | None,
    now: int | None = None,
) -> JsonObject | None:
    direct = automation_task_from_text(text, now=now)
    if direct is not None:
        return direct

    normalized = text.strip().lower().replace("，", ",").replace("。", ".")
    modification = any(
        token in normalized
        for token in ("改成", "改到", "改为", "调整到", "换成", "延后到", "提前到", "修改")
    )
    cancellation = any(
        token in normalized
        for token in ("取消刚才", "删除刚才", "不要刚才", "刚才那个不要了", "取消这个任务")
    )
    if cancellation and latest_task is not None:
        return {"operation": "cancel", "task_id": latest_task["task_id"]}

    hour, minute = _extract_clock(normalized)
    recurrence_daily = any(token in normalized for token in ("改成每天", "以后每天", "每天执行", "长期"))
    recurrence_once = any(
        token in normalized
        for token in ("只执行一次", "仅今天", "就今天", "今天", "今晚", "今日", "一次性", "短期")
    )
    if latest_task is not None and (modification or recurrence_daily or recurrence_once):
        schedule_kind = str(latest_task.get("schedule_kind") or "once")
        if recurrence_daily:
            schedule_kind = "daily"
        elif recurrence_once:
            schedule_kind = "once"
        local_time = str(latest_task.get("spec", {}).get("local_time") or "")
        if hour is not None:
            local_time = f"{hour:02d}:{minute:02d}"
        if local_time and latest_task["task_type"] in {"scheduled_report", "scheduled_action"}:
            next_run_at = _next_run_for_kind(
                local_time,
                schedule_kind,
                int(now or time.time()),
                previous_run_at=latest_task.get("next_run_at"),
            )
            if next_run_at is None:
                return {
                    "operation": "clarify",
                    "question": f"今天的 {local_time} 已经过了。你希望改到明天，还是换一个今天尚未到的时间？",
                }
            spec = dict(latest_task["spec"])
            spec["local_time"] = local_time
            spec["timezone"] = "Asia/Shanghai"
            if schedule_kind == "once":
                spec["target_local_iso"] = datetime.fromtimestamp(
                    next_run_at,
                    _LOCAL_TZ,
                ).isoformat(timespec="seconds")
            else:
                spec.pop("target_local_iso", None)
            return {
                "operation": "update",
                "task_id": latest_task["task_id"],
                "task_type": latest_task["task_type"],
                "schedule_kind": schedule_kind,
                "next_run_at": next_run_at,
                "survives_conversation": schedule_kind == "daily",
                "spec": spec,
            }

    if not modification and not recurrence_daily and not recurrence_once:
        return None
    base = _latest_parsed_task_from_history(
        conversation_history,
        current_text=normalized,
        now=now,
    )
    if base is None or base.get("operation") != "create":
        return None
    if hour is None:
        return base
    schedule_kind = str(base.get("schedule_kind") or "once")
    local_time = f"{hour:02d}:{minute:02d}"
    next_run_at = _next_run_for_kind(
        local_time,
        schedule_kind,
        int(now or time.time()),
        previous_run_at=base.get("next_run_at"),
    )
    if next_run_at is None:
        return {
            "operation": "clarify",
            "question": f"今天的 {local_time} 已经过了。你希望改到明天，还是换一个今天尚未到的时间？",
        }
    updated = dict(base)
    updated["next_run_at"] = next_run_at
    updated["schedule_kind"] = schedule_kind
    updated["survives_conversation"] = schedule_kind == "daily"
    if updated.get("task_type") == "scheduled_report":
        updated["name"] = ("每日" if schedule_kind == "daily" else "一次性") + f"{local_time}环境汇报"
    elif updated.get("task_type") == "scheduled_action":
        updated["name"] = ("每日" if schedule_kind == "daily" else "一次性") + f"{local_time}舵机动作"
    spec = dict(updated.get("spec") or {})
    spec["local_time"] = local_time
    spec["timezone"] = "Asia/Shanghai"
    if schedule_kind == "once":
        spec["target_local_iso"] = datetime.fromtimestamp(
            next_run_at,
            _LOCAL_TZ,
        ).isoformat(timespec="seconds")
    else:
        spec.pop("target_local_iso", None)
    updated["spec"] = spec
    return updated


def automation_next_run(local_time: str, *, now: int | None = None) -> int:
    return _next_daily_run(local_time, int(now or time.time()))


def _parse_sensor_condition(text: str) -> JsonObject | None:
    sensor_specs = [
        (("温度", "temperature"), "env.temperature"),
        (("湿度", "humidity"), "env.humidity"),
        (("光照", "照度", "lux", "light"), "env.light.lux"),
    ]
    operators = [
        ((">=", "达到", "到达", "不低于", "至少"), ">="),
        (("<=", "不超过", "至多"), "<="),
        ((">", "超过", "大于", "高于"), ">"),
        (("<", "低于", "小于"), "<"),
    ]
    for aliases, capability in sensor_specs:
        if not any(alias in text for alias in aliases):
            continue
        for tokens, operator in operators:
            for token in tokens:
                match = re.search(rf"{re.escape(token)}\s*(\d+(?:\.\d+)?)", text)
                if match:
                    return {
                        "capability": capability,
                        "operator": operator,
                        "value": float(match.group(1)),
                    }
    return None


def _parse_servo_action(text: str) -> JsonObject:
    angle_matches = re.findall(r"(\d{1,3})\s*度", text)
    angle = max(1, min(int(angle_matches[-1]) if angle_matches else 30, 90))
    repeat_match = re.search(r"([一二两三四五六七八九十\d]+)\s*(?:次|遍|回)", text)
    times = _parse_count(repeat_match.group(1)) if repeat_match else 1
    times = max(1, min(times, 10))
    if ("向左" in text or "左转" in text) and not ("向右" in text or "右转" in text):
        direction = "left"
    elif ("向右" in text or "右转" in text) and not ("向左" in text or "左转" in text):
        direction = "right"
    else:
        direction = "both"
    duration_match = re.search(r"(\d+)\s*(?:ms|毫秒)", text)
    duration_ms = max(50, min(int(duration_match.group(1)) if duration_match else 350, 5000))
    return {
        "direction": direction,
        "angle": angle,
        "times": times,
        "duration_ms": duration_ms,
    }


def _parse_report_schedule(text: str, *, now: int | None) -> JsonObject | None:
    schedule = _parse_schedule(text, now=now)
    if schedule.get("operation") == "clarify":
        return schedule
    local_time = str(schedule["spec"]["local_time"])
    return {
        "name": ("每日" if schedule["schedule_kind"] == "daily" else "一次性") + f"{local_time}环境汇报",
        "spec": {
            **schedule["spec"],
            "capabilities": _report_capabilities(text),
        },
        **{key: value for key, value in schedule.items() if key != "spec"},
    }


def _parse_schedule(text: str, *, now: int | None) -> JsonObject:
    hour, minute, second = _extract_clock_parts(text)
    if hour is None:
        return {"operation": "clarify", "question": "请补充具体执行时间。"}
    local_time = _format_local_time(hour, minute, second)
    daily = any(token in text for token in ("每天", "每日", "长期任务", "长期", "永久"))
    once = any(
        token in text
        for token in (
            "今天",
            "今晚",
            "今日",
            "明天",
            "后天",
            "仅一次",
            "一次性",
            "短期任务",
            "短期",
        )
    ) or _has_explicit_calendar_date(text)
    if not daily and not once:
        return {
            "operation": "clarify",
            "question": f"你希望这个 {local_time} 的定时任务每天执行，还是仅今天执行一次？",
            "local_time": local_time,
        }
    current = int(now or time.time())
    next_run_at = _next_daily_run(local_time, current)
    spec: JsonObject = {
        "local_time": local_time,
        "timezone": "Asia/Shanghai",
    }
    if once:
        local_now = datetime.fromtimestamp(current, _LOCAL_TZ)
        target_date = _extract_target_date(text, local_now)
        candidate = datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            second,
            tzinfo=_LOCAL_TZ,
        )
        next_run_at = int(candidate.timestamp())
        if next_run_at <= current:
            return {
                "operation": "clarify",
                "question": (
                    f"目标时间 {candidate.isoformat(timespec='seconds')} 已经过了；"
                    f"服务器当前时间是 {local_now.isoformat(timespec='seconds')}。"
                    "请指定一个未来时间。"
                ),
                "local_time": local_time,
            }
        spec["target_local_iso"] = candidate.isoformat(timespec="seconds")
    return {
        "schedule_kind": "daily" if daily else "once",
        "next_run_at": next_run_at,
        "survives_conversation": daily or _long_lived_intent(text),
        "spec": spec,
    }


def _long_lived_intent(text: str) -> bool:
    return any(token in text for token in ("每天", "每日", "长期", "永久", "一直保留", "删除对话也保留"))


def _report_capabilities(text: str) -> list[str]:
    capabilities: list[str] = []
    if any(token in text for token in ("温度", "温湿度", "temperature")):
        capabilities.append("env.temperature")
    if any(token in text for token in ("湿度", "温湿度", "humidity")):
        capabilities.append("env.humidity")
    if any(token in text for token in ("光照", "照度", "lux", "light")):
        capabilities.append("env.light.lux")
    return capabilities or ["env.temperature", "env.humidity", "env.light.lux"]


def _has_explicit_calendar_date(text: str) -> bool:
    return bool(
        re.search(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*[日号]", text)
        or re.search(r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]", text)
    )


def _extract_target_date(text: str, local_now: datetime):
    full = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", text)
    if full:
        return datetime(int(full.group(1)), int(full.group(2)), int(full.group(3))).date()
    month_day = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", text)
    if month_day:
        return datetime(local_now.year, int(month_day.group(1)), int(month_day.group(2))).date()
    if "后天" in text:
        return (local_now + timedelta(days=2)).date()
    if "明天" in text:
        return (local_now + timedelta(days=1)).date()
    return local_now.date()


def _explicit_auto_reset(text: str) -> bool:
    return any(token in text for token in ("自动复位", "自动回中", "回到90", "回到 90", "回中"))


def _extract_clock(text: str) -> tuple[int | None, int]:
    hour, minute, _second = _extract_clock_parts(text)
    return hour, minute


def _extract_clock_parts(text: str) -> tuple[int | None, int, int]:
    colon = re.search(r"(\d{1,2})\s*[:：]\s*(\d{1,2})(?:\s*[:：]\s*(\d{1,2}))?", text)
    if colon:
        hour = int(colon.group(1))
        minute = int(colon.group(2))
        second = int(colon.group(3) or 0)
    else:
        number = r"[零〇一二三四五六七八九十两\d]{1,3}"
        clock = re.search(
            rf"({number})\s*[点时]\s*(半|({number})\s*分?)?(?:\s*({number})\s*秒)?",
            text,
        )
        if not clock:
            return None, 0, 0
        hour = _parse_number_token(clock.group(1))
        minute = 30 if clock.group(2) == "半" else _parse_number_token(clock.group(3) or "0")
        second = _parse_number_token(clock.group(4) or "0")
    if "下午" in text or "晚上" in text:
        if hour < 12:
            hour += 12
    elif "中午" in text and hour < 11:
        hour += 12
    elif "凌晨" in text and hour == 12:
        hour = 0
    if not 0 <= hour <= 23 or not 0 <= minute <= 59 or not 0 <= second <= 59:
        return None, 0, 0
    return hour, minute, second


def _format_local_time(hour: int, minute: int, second: int) -> str:
    if second:
        return f"{hour:02d}:{minute:02d}:{second:02d}"
    return f"{hour:02d}:{minute:02d}"


def _parse_local_time(local_time: str) -> tuple[int, int, int]:
    parts = [int(part) for part in local_time.split(":")]
    if len(parts) == 2:
        return parts[0], parts[1], 0
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    raise ValueError(f"invalid local time: {local_time}")


def _next_daily_run(local_time: str, now: int) -> int:
    hour, minute, second = _parse_local_time(local_time)
    local_now = datetime.fromtimestamp(now, _LOCAL_TZ)
    candidate = local_now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if candidate.timestamp() <= now:
        candidate += timedelta(days=1)
    return int(candidate.timestamp())


def _next_run_for_kind(
    local_time: str,
    schedule_kind: str,
    now: int,
    *,
    previous_run_at: object = None,
) -> int | None:
    if schedule_kind == "daily":
        return _next_daily_run(local_time, now)
    hour, minute, second = _parse_local_time(local_time)
    local_now = datetime.fromtimestamp(now, _LOCAL_TZ)
    base_date = local_now
    if isinstance(previous_run_at, int):
        previous = datetime.fromtimestamp(previous_run_at, _LOCAL_TZ)
        if previous.date() >= local_now.date():
            base_date = previous
    candidate = base_date.replace(hour=hour, minute=minute, second=second, microsecond=0)
    return int(candidate.timestamp()) if candidate.timestamp() > now else None


def _latest_parsed_task_from_history(
    conversation_history: list[JsonObject],
    *,
    current_text: str,
    now: int | None,
) -> JsonObject | None:
    for item in reversed(conversation_history[:-1]):
        if str(item.get("role") or "") != "user":
            continue
        prior_text = str(item.get("content") or "")
        parsed = automation_task_from_text(prior_text, now=now)
        if parsed is not None and parsed.get("operation") == "create":
            return parsed
        if parsed is not None and parsed.get("operation") == "clarify":
            combined = automation_task_from_text(f"{prior_text} {current_text}", now=now)
            if combined is not None and combined.get("operation") == "create":
                return combined
    return None


def _latest_capability_value(device_id: str, capability: str) -> JsonObject | None:
    snapshot = device_state_store.snapshot(device_id)
    last_seen = snapshot.get("last_seen")
    now = time.time()
    if not isinstance(last_seen, (int, float)) or now - float(last_seen) > 45:
        return None
    candidates: list[tuple[float, JsonObject]] = []
    for key in ("last_telemetry", "last_status"):
        message = snapshot.get(key)
        payload = message.get("payload") if isinstance(message, dict) else None
        if not isinstance(payload, dict):
            continue
        samples = payload.get("samples")
        if isinstance(samples, list):
            for sample in samples:
                if not isinstance(sample, dict) or str(sample.get("capability")) != capability:
                    continue
                value = sample.get("value")
                if not isinstance(value, (int, float)):
                    continue
                ts = sample.get("ts_ms")
                score = float(ts) if isinstance(ts, (int, float)) else float(last_seen)
                candidates.append(
                    (
                        score,
                        {
                            "capability": capability,
                            "value": float(value),
                            "unit": str(sample.get("unit") or ""),
                            "timestamp": score,
                            "fresh": True,
                        },
                    )
                )
        aht20 = payload.get("aht20")
        if isinstance(aht20, dict) and str(aht20.get("status")) == "online":
            legacy_key = {
                "env.temperature": "temp",
                "env.humidity": "humidity",
            }.get(capability)
            value = aht20.get(legacy_key) if legacy_key else None
            if isinstance(value, (int, float)):
                candidates.append(
                    (
                        float(last_seen),
                        {
                            "capability": capability,
                            "value": float(value),
                            "unit": "C" if capability == "env.temperature" else "%RH",
                            "timestamp": float(last_seen),
                            "fresh": True,
                        },
                    )
                )
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _compare(actual: float, operator: str, threshold: float) -> bool:
    return {
        ">": actual > threshold,
        ">=": actual >= threshold,
        "<": actual < threshold,
        "<=": actual <= threshold,
        "==": actual == threshold,
    }.get(operator, False)


def _task_name(condition: JsonObject, action: JsonObject) -> str:
    labels = {
        "env.temperature": "温度",
        "env.humidity": "湿度",
        "env.light.lux": "光照",
    }
    direction = {"both": "左右", "left": "向左", "right": "向右"}[str(action["direction"])]
    return (
        f"{labels[str(condition['capability'])]}{condition['operator']}{condition['value']:g}"
        f"时SG90{direction}{action['times']}次{action['angle']}度"
    )


def _parse_count(value: str) -> int:
    return int(value) if value.isdigit() else _parse_chinese_number(value)


def _parse_number_token(value: str) -> int:
    return int(value) if value.isdigit() else _parse_chinese_number(value)


def _parse_chinese_number(value: str) -> int:
    if not value or value in {"零", "〇"}:
        return 0
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if value == "十":
        return 10
    if "十" in value:
        left, _, right = value.partition("十")
        return (digits.get(left, 1) * 10) + digits.get(right, 0)
    if all(character in digits for character in value):
        return int("".join(str(digits[character]) for character in value))
    return 0


def _task_row(row: sqlite3.Row) -> JsonObject:
    return {
        "task_id": row["task_id"],
        "owner_channel": row["owner_channel"],
        "owner_id": row["owner_id"],
        "conversation_id": row["conversation_id"],
        "device_id": row["device_id"],
        "task_type": row["task_type"],
        "name": row["name"],
        "spec": json.loads(row["spec_json"]),
        "schedule_kind": row["schedule_kind"],
        "next_run_at": row["next_run_at"],
        "last_run_at": row["last_run_at"],
        "last_condition": bool(row["last_condition"]),
        "enabled": bool(row["enabled"]),
        "survives_conversation": bool(row["survives_conversation"]),
        "last_result": json.loads(row["last_result_json"]) if row["last_result_json"] else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
