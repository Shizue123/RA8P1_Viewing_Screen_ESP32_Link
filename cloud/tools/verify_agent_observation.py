from __future__ import annotations

import json
import os
import time

from cloud.app.agent_service.orchestrator import AgentOrchestrator
from cloud.app.api.web_routes import _try_llm_first_web_hardware_action
from cloud.app.config import get_settings
from cloud.app.device_registry import DeviceRegistry
from cloud.app.device_state.store import device_state_store
from cloud.app.mqtt_service.client import MqttPublisher
from cloud.app.mqtt_service.subscriber import MqttStateSubscriber
from cloud.app.qqbot import QQBotMessageEvent
from cloud.app.qqbot_runtime import generate_qqbot_reply
from cloud.app.qqbot_runtime import _select_qqbot_device_id
from cloud.app.model_config import effective_model_settings, model_config_view


def main() -> None:
    base = get_settings()
    settings = base.model_copy(
        update={
            "mqtt_subscriber_client_id": "embedded-agent-agent-observation-verify",
            "log_db_path": "/tmp/embedded-agent-agent-observation-verify.sqlite3",
        }
    )
    subscriber = MqttStateSubscriber(settings, device_state_store)
    subscriber.start()
    try:
        deadline = time.time() + 15
        device_id = settings.device_id
        while time.time() < deadline:
            device_id = _select_qqbot_device_id(settings, DeviceRegistry(settings))
            snapshot = device_state_store.snapshot(device_id)
            if device_id != settings.device_id and snapshot.get("last_telemetry"):
                break
            time.sleep(0.5)

        active_provider = str(model_config_view(settings)["active"].get("provider") or "")
        providers = (
            (active_provider,)
            if os.environ.get("VERIFY_ACTIVE_ONLY") == "1" and active_provider
            else ("hermes_official", "deepseek")
        )
        results: list[dict[str, object]] = []
        for provider in providers:
            provider_settings = settings.model_copy(
                update={
                    "device_id": device_id,
                    "llm_provider": provider,
                }
            )
            orchestrator = AgentOrchestrator(
                provider_settings,
                MqttPublisher(provider_settings),
            )
            for text in ("读取光照", "读取温湿度", "看看温湿度和光照的情况"):
                response = _try_llm_first_web_hardware_action(
                    text,
                    provider_settings,
                    orchestrator,
                    conversation_history=[],
                )
                results.append(
                    {
                        "provider": provider,
                        "request": text,
                        "reply": response.get("assistant_message"),
                        "source": response.get("source"),
                        "hardware_control": response.get("hardware_control"),
                    }
                )

        active_settings = effective_model_settings(settings).model_copy(
            update={"device_id": device_id}
        )
        qq_orchestrator = AgentOrchestrator(
            active_settings,
            MqttPublisher(active_settings),
        )
        qq_results = []
        for index, text in enumerate(("读取光照", "读取温湿度", "看看温湿度和光照的情况"), start=1):
            event = QQBotMessageEvent(
                event_type="C2C_MESSAGE_CREATE",
                msg_id=f"verify-{index}",
                text=text,
                conversation_key="qqbot:verify",
                user_openid="verify-user",
            )
            qq_results.append(
                {
                    "request": text,
                    "reply": generate_qqbot_reply(
                        event,
                        active_settings,
                        qq_orchestrator,
                        DeviceRegistry(active_settings),
                    ),
                }
            )

        print(
            json.dumps(
                {
                    "device_id": device_id,
                    "active_model": model_config_view(settings)["active"],
                    "model_config": {
                        "hermes_gateway_url": settings.hermes_gateway_url,
                        "hermes_key_available": bool(
                            settings.hermes_gateway_api_key or settings.api_server_key
                        ),
                        "deepseek_key_available": bool(settings.deepseek_api_key),
                    },
                    "results": results,
                    "qq_results": qq_results,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        subscriber.stop()


if __name__ == "__main__":
    main()
