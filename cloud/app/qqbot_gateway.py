from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path
import threading
import time

from websockets.asyncio.client import connect

from cloud.app.agent_service.orchestrator import AgentOrchestrator
from cloud.app.config import Settings
from cloud.app.device_registry import DeviceRegistry
from cloud.app.mqtt_service.client import MqttPublisher
from cloud.app.qqbot import (
    qqbot_fetch_access_token,
    qqbot_fetch_gateway_url,
    qqbot_is_configured,
    qqbot_mark_message_processed,
    qqbot_message_already_processed,
    qqbot_parse_message_event,
    qqbot_send_text_reply,
)
from cloud.app.qqbot_runtime import generate_qqbot_reply


logger = logging.getLogger("uvicorn.error")
QQ_GROUP_AND_C2C_INTENTS = 1 << 25
STATUS_PATH = Path(__file__).resolve().parents[1] / "runtime" / "qqbot_gateway_status.json"


class QQBotGatewayService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._orchestrator = AgentOrchestrator(settings, MqttPublisher(settings))
        self._registry = DeviceRegistry(settings)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._thread is not None or not qqbot_is_configured(self._settings):
            return
        self._stop_event.clear()
        self._write_status("starting")
        logger.info("QQ Bot gateway background service starting")
        self._thread = threading.Thread(
            target=self._run,
            name="qqbot-gateway",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._write_status("stopping")
        thread = self._thread
        if thread is None:
            return
        thread.join(timeout=5)
        self._thread = None
        self._write_status("stopped")

    def _run(self) -> None:
        asyncio.run(self._runner())

    async def _runner(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._connect_once()
            except Exception as exc:
                self._write_status("error", detail=str(exc))
                logger.warning("QQ Bot gateway connection failed: %s", exc)
            if self._stop_event.is_set():
                break
            await asyncio.sleep(5)

    async def _connect_once(self) -> None:
        gateway_url = qqbot_fetch_gateway_url(self._settings)
        access_token = qqbot_fetch_access_token(self._settings)
        self._write_status("connecting", gateway_url=gateway_url)
        logger.info("Connecting QQ Bot gateway: %s", gateway_url)
        async with connect(gateway_url, ping_interval=None, open_timeout=15, close_timeout=10) as websocket:
            hello = json.loads(await asyncio.wait_for(websocket.recv(), timeout=15))
            interval_ms = int(((hello.get("d") or {}) if isinstance(hello.get("d"), dict) else {}).get("heartbeat_interval") or 45000)
            state: dict[str, int | str | None] = {"seq": None, "session_id": None}
            await websocket.send(
                json.dumps(
                    {
                        "op": 2,
                        "d": {
                            "token": f"QQBot {access_token}",
                            "intents": QQ_GROUP_AND_C2C_INTENTS,
                            "shard": [0, 1],
                            "properties": {
                                "$os": "linux",
                                "$browser": "embedded-agent-cloud",
                                "$device": "embedded-agent-cloud",
                            },
                        },
                    },
                    ensure_ascii=False,
                )
            )
            heartbeat_task = asyncio.create_task(self._heartbeat_loop(websocket, interval_ms, state))
            try:
                async for raw_message in websocket:
                    payload = json.loads(raw_message)
                    if payload.get("s") is not None:
                        state["seq"] = int(payload["s"])
                    op = int(payload.get("op") or 0)
                    if payload.get("t") == "READY":
                        data = payload.get("d")
                        if isinstance(data, dict):
                            state["session_id"] = str(data.get("session_id") or "")
                            self._write_status("ready", session_id=state["session_id"], seq=state["seq"])
                        logger.info("QQ Bot gateway READY session=%s", state["session_id"] or "unknown")
                    elif payload.get("t") == "RESUMED":
                        self._write_status("resumed", session_id=state.get("session_id"), seq=state.get("seq"))
                        logger.info("QQ Bot gateway RESUMED")
                    elif payload.get("t") in {"C2C_MESSAGE_CREATE", "GROUP_AT_MESSAGE_CREATE"}:
                        await asyncio.to_thread(self._handle_message_event, payload, state)
                    elif op == 7:
                        self._write_status("reconnect_requested", session_id=state.get("session_id"), seq=state.get("seq"))
                        logger.info("QQ Bot gateway requested reconnect")
                        return
                    elif op == 9:
                        raise RuntimeError("QQ Bot gateway invalid session")
            finally:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task

    async def _heartbeat_loop(self, websocket, interval_ms: int, state: dict[str, int | str | None]) -> None:
        interval_sec = max(5.0, interval_ms / 1000.0)
        while not self._stop_event.is_set():
            await asyncio.sleep(interval_sec)
            await websocket.send(json.dumps({"op": 1, "d": state.get("seq")}))
            self._write_status("heartbeat", session_id=state.get("session_id"), seq=state.get("seq"))

    def _write_status(self, state: str, **extra: object) -> None:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "state": state,
            "updated_at": int(time.time()),
        }
        payload.update(extra)
        STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _handle_message_event(self, payload: dict[str, object], state: dict[str, int | str | None]) -> None:
        event = qqbot_parse_message_event(payload)
        if event is None:
            return
        if qqbot_message_already_processed(event.msg_id):
            logger.info("QQ Bot duplicate message skipped: %s", event.msg_id)
            return
        logger.info("QQ Bot message received: type=%s msg_id=%s", event.event_type, event.msg_id)
        try:
            reply_text = generate_qqbot_reply(
                event,
                self._settings,
                self._orchestrator,
                self._registry,
            )
            qqbot_send_text_reply(event, reply_text, self._settings)
            qqbot_mark_message_processed(event.msg_id)
            self._write_status(
                "message_replied",
                session_id=state.get("session_id"),
                seq=state.get("seq"),
                msg_id=event.msg_id,
                event_type=event.event_type,
            )
            logger.info("QQ Bot reply sent: msg_id=%s", event.msg_id)
        except Exception as exc:
            self._write_status(
                "message_error",
                session_id=state.get("session_id"),
                seq=state.get("seq"),
                msg_id=event.msg_id,
                detail=str(exc),
            )
            logger.warning("QQ Bot reply failed for msg_id=%s: %s", event.msg_id, exc)
