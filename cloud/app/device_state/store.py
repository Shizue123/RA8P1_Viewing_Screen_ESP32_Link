from __future__ import annotations

import threading
import time
from collections import deque
from copy import deepcopy
from typing import Any


JsonObject = dict[str, Any]


class DeviceStateStore:
    def __init__(self, max_events: int = 100) -> None:
        self._condition = threading.Condition()
        self._max_events = max_events
        self._state: dict[str, JsonObject] = {}

    def update_from_mqtt(self, topic: str, message: JsonObject) -> None:
        parts = topic.split("/")
        if len(parts) != 3 or parts[0] != "cloudbridge":
            return
        device_id = parts[1]
        channel = parts[2]
        observed_at = message.get("timestamp")
        if not isinstance(observed_at, (int, float)):
            observed_at = int(time.time())
            message = {**message, "timestamp": observed_at}
        with self._condition:
            entry = self._state.setdefault(device_id, self._new_entry(device_id))
            entry["last_seen"] = observed_at
            entry["channels"][channel] = deepcopy(message)
            if channel == "event":
                entry["last_event"] = deepcopy(message)
                payload = message.get("payload")
                if isinstance(payload, dict) and message.get("type") == "deploy_ack":
                    entry["last_deploy_ack"] = deepcopy(message)
            elif channel == "status":
                entry["last_status"] = deepcopy(message)
            elif channel == "telemetry":
                entry["last_telemetry"] = deepcopy(message)
            elif channel == "log":
                entry["last_log"] = deepcopy(message)
            events = entry["events"]
            if isinstance(events, deque):
                events.append({"topic": topic, "message": deepcopy(message)})
            self._condition.notify_all()

    def snapshot(self, device_id: str) -> JsonObject:
        with self._condition:
            entry = deepcopy(self._state.get(device_id, self._new_entry(device_id)))
            events = entry.get("events")
            if isinstance(events, deque):
                entry["events"] = list(events)
            return entry

    def events(self, device_id: str, limit: int = 20) -> list[JsonObject]:
        with self._condition:
            entry = self._state.get(device_id)
            if not entry:
                return []
            events = entry.get("events")
            if not isinstance(events, deque):
                return []
            return list(events)[-limit:]

    def wait_for_deploy_ack(self, device_id: str, request_id: str, timeout_sec: float) -> JsonObject | None:
        def find_ack() -> JsonObject | None:
            entry = self._state.get(device_id)
            if not entry:
                return None
            events = entry.get("events")
            if not isinstance(events, deque):
                return None
            for event in reversed(events):
                message = event.get("message")
                if (
                    isinstance(message, dict)
                    and message.get("type") == "deploy_ack"
                    and message.get("request_id") == request_id
                ):
                    return deepcopy(message)
            return None

        with self._condition:
            ack = find_ack()
            if ack is not None:
                return ack
            self._condition.wait_for(lambda: find_ack() is not None, timeout=timeout_sec)
            return find_ack()

    def wait_for_request_event(
        self,
        device_id: str,
        request_id: str,
        message_type: str,
        timeout_sec: float,
    ) -> JsonObject | None:
        def find_event() -> JsonObject | None:
            entry = self._state.get(device_id)
            if not entry:
                return None
            events = entry.get("events")
            if not isinstance(events, deque):
                return None
            for event in reversed(events):
                message = event.get("message")
                if (
                    isinstance(message, dict)
                    and message.get("type") == message_type
                    and message.get("request_id") == request_id
                ):
                    return deepcopy(message)
            return None

        with self._condition:
            matched = find_event()
            if matched is not None:
                return matched
            self._condition.wait_for(lambda: find_event() is not None, timeout=timeout_sec)
            return find_event()

    def _new_entry(self, device_id: str) -> JsonObject:
        return {
            "device_id": device_id,
            "last_seen": None,
            "last_status": None,
            "last_telemetry": None,
            "last_event": None,
            "last_deploy_ack": None,
            "last_log": None,
            "channels": {},
            "events": deque(maxlen=self._max_events),
        }


device_state_store = DeviceStateStore()
