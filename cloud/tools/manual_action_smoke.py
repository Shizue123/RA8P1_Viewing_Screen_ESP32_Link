from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import paho.mqtt.client as mqtt

from cloud.app.api.web_routes import _deploy_manual_action
from cloud.app.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish a bounded SG90 action and collect request-scoped evidence.")
    parser.add_argument("--direction", choices=("both", "left", "right"), default="right")
    parser.add_argument("--angle", type=int, default=60)
    parser.add_argument("--times", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    settings = Settings()
    messages: list[dict[str, object]] = []
    connected = threading.Event()
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"sg90-smoke-{int(time.time())}",
    )
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password or None)
    if settings.mqtt_tls_enabled:
        client.tls_set(ca_certs=settings.mqtt_ca_cert_path or None)

    def on_connect(
        client: mqtt.Client,
        _userdata: object,
        _flags: object,
        _reason_code: object,
        _properties: object,
    ) -> None:
        client.subscribe(f"cloudbridge/{settings.device_id}/event", qos=1)
        client.subscribe(f"cloudbridge/{settings.device_id}/status", qos=1)
        connected.set()

    def on_message(
        _client: mqtt.Client,
        _userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if isinstance(payload, dict):
            messages.append({"topic": message.topic, "message": payload})

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(settings.mqtt_broker_url, settings.mqtt_port, keepalive=30)
    client.loop_start()
    if not connected.wait(5):
        raise SystemExit("MQTT evidence subscriber did not connect")

    response = _deploy_manual_action(
        {
            "direction": args.direction,
            "angle": args.angle,
            "times": args.times,
            "duration_ms": 350,
        },
        settings.model_copy(update={"web_hardware_wait_for_ack": False}),
        source="manual_action_smoke",
        confidence=1.0,
        reasoning_summary="request-scoped real-device SG90 validation",
    )
    request_id = str(response["hardware_control"]["request_id"])
    deadline = time.time() + args.timeout
    matched: list[dict[str, object]] = []
    while time.time() < deadline:
        matched = [
            item
            for item in messages
            if _matches_request(item.get("message"), request_id)
        ]
        if any(_execution_done(item.get("message")) for item in matched):
            break
        time.sleep(0.2)

    client.loop_stop()
    client.disconnect()
    print(
        json.dumps(
            {
                "request_id": request_id,
                "published": response["hardware_control"]["deployment"].get("published"),
                "direction": args.direction,
                "angle": args.angle,
                "times": args.times,
                "evidence": [_evidence_view(item) for item in matched],
            },
            ensure_ascii=False,
        )
    )


def _matches_request(message: object, request_id: str) -> bool:
    if not isinstance(message, dict):
        return False
    payload = message.get("payload")
    return message.get("request_id") == request_id or (
        isinstance(payload, dict)
        and (
            payload.get("request_id") == request_id
            or payload.get("last_request_id") == request_id
        )
    )


def _execution_done(message: object) -> bool:
    if not isinstance(message, dict):
        return False
    payload = message.get("payload")
    if not isinstance(payload, dict):
        return False
    state = str(payload.get("state") or payload.get("execution_state") or payload.get("script_state") or "")
    return state.upper() in {"DONE", "EXECUTED", "SUCCESS"}


def _evidence_view(item: dict[str, object]) -> dict[str, object]:
    message = item.get("message")
    message = message if isinstance(message, dict) else {}
    payload = message.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    return {
        "topic": item.get("topic"),
        "type": message.get("type"),
        "state": payload.get("state") or payload.get("execution_state") or payload.get("script_state"),
        "detail": payload.get("detail") or payload.get("message"),
    }


if __name__ == "__main__":
    main()
