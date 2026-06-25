from __future__ import annotations

import json
import threading
from typing import Any

from cloud.app.config import Settings
from cloud.app.device_state.store import DeviceStateStore
from cloud.app.device_registry import DeviceRegistry
from cloud.app.log_service.store import PersistentLogStore


JsonObject = dict[str, Any]


class MqttStateSubscriber:
    def __init__(self, settings: Settings, store: DeviceStateStore) -> None:
        self._settings = settings
        self._store = store
        self._log_store = PersistentLogStore(settings.log_db_path)
        self._registry = DeviceRegistry(settings)
        self._client: Any | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if not self._settings.mqtt_enabled:
            return
        with self._lock:
            if self._client is not None:
                return

            import paho.mqtt.client as mqtt

            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=self._settings.mqtt_subscriber_client_id,
            )
            if self._settings.mqtt_username:
                client.username_pw_set(self._settings.mqtt_username, self._settings.mqtt_password or None)
            if self._settings.mqtt_tls_enabled:
                tls_kwargs: dict[str, str] = {}
                if self._settings.mqtt_ca_cert_path:
                    tls_kwargs["ca_certs"] = self._settings.mqtt_ca_cert_path
                client.tls_set(**tls_kwargs)

            def on_connect(client: mqtt.Client, _userdata: object, _flags: object, rc: object, _props: object) -> None:
                print(f"mqtt state subscriber connected rc={rc}")
                for channel in ("status", "telemetry", "event", "log"):
                    client.subscribe(f"cloudbridge/+/{channel}", qos=1)

            def on_message(_client: mqtt.Client, _userdata: object, msg: mqtt.MQTTMessage) -> None:
                if getattr(msg, "retain", False):
                    return
                try:
                    decoded = json.loads(msg.payload.decode("utf-8"))
                except Exception as exc:
                    decoded = {"request_id": "decode_error", "type": "decode_error", "payload": {"error": str(exc)}}
                if isinstance(decoded, dict):
                    self._store.update_from_mqtt(msg.topic, decoded)
                    parts = msg.topic.split("/")
                    if len(parts) == 3 and parts[0] == "cloudbridge":
                        device_id = parts[1]
                        channel = parts[2]
                        self._registry.touch_observed(device_id, source="mqtt")
                        self._log_store.record_device_message(
                            topic=msg.topic,
                            device_id=device_id,
                            channel=channel,
                            message=decoded,
                        )
                        if channel == "event" and decoded.get("type") == "deploy_ack":
                            self._log_store.record_ack(device_id, decoded)

            client.on_connect = on_connect
            client.on_message = on_message
            client.connect(self._settings.mqtt_broker_url, self._settings.mqtt_port, keepalive=60)
            client.loop_start()
            self._client = client

    def stop(self) -> None:
        with self._lock:
            if self._client is None:
                return
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
