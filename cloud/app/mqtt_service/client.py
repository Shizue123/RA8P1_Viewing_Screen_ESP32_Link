from __future__ import annotations

import json
from dataclasses import dataclass

from cloud.app.config import Settings
from cloud.app.models import MqttEnvelope


@dataclass(frozen=True)
class PublishResult:
    topic: str
    published: bool


class MqttPublisher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def script_topic(self, device_id: str) -> str:
        return f"cloudbridge/{device_id}/script"

    def publish_script(self, device_id: str, message: MqttEnvelope) -> PublishResult:
        topic = self.script_topic(device_id)
        if not self._settings.mqtt_enabled:
            return PublishResult(topic=topic, published=False)

        import paho.mqtt.client as mqtt

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self._settings.mqtt_client_id)
        if self._settings.mqtt_username:
            client.username_pw_set(self._settings.mqtt_username, self._settings.mqtt_password or None)
        if self._settings.mqtt_tls_enabled:
            tls_kwargs: dict[str, str] = {}
            if self._settings.mqtt_ca_cert_path:
                tls_kwargs["ca_certs"] = self._settings.mqtt_ca_cert_path
            client.tls_set(**tls_kwargs)
        client.connect(self._settings.mqtt_broker_url, self._settings.mqtt_port, keepalive=60)
        client.loop_start()
        result = client.publish(
            topic,
            json.dumps(message.model_dump(mode="json"), ensure_ascii=False),
            qos=1,
            retain=False,
        )
        result.wait_for_publish(timeout=5)
        client.loop_stop()
        client.disconnect()
        return PublishResult(topic=topic, published=True)
