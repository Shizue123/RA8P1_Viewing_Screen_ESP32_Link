from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    api_token: str = ""
    auth_db_path: str = "runtime/web_auth.sqlite3"
    auth_session_ttl_hours: int = 168
    auth_cookie_name: str = "ra8p1_session"
    web_hardware_control_enabled: bool = False
    web_hardware_control_roles: str = "admin"
    web_hardware_wait_for_ack: bool = False
    qqbot_enabled: bool = False
    qqbot_app_id: str = ""
    qqbot_app_secret: str = ""
    qqbot_hardware_control_enabled: bool = False
    qqbot_allow_group_commands: bool = False
    qqbot_allowed_user_openids: str = ""
    qqbot_allowed_group_openids: str = ""
    automation_task_db_path: str = "runtime/automation_tasks.sqlite3"

    mqtt_broker_url: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_script_secret: str = ""
    mqtt_tls_enabled: bool = False
    mqtt_ca_cert_path: str = ""
    mqtt_client_id: str = "embedded-agent-cloud-dev"
    mqtt_subscriber_client_id: str = "embedded-agent-cloud-state-subscriber"
    mqtt_enabled: bool = False
    deploy_ack_timeout_sec: float = 5.0
    api_rate_limit_window_sec: int = 60
    api_rate_limit_max_requests: int = 120
    api_deploy_rate_limit_max_requests: int = 20

    llm_provider: str = "template"
    openai_api_key: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"
    hermes_official_enabled: bool = False
    hermes_official_uv_path: str = ""
    hermes_official_workdir: str = ""
    hermes_official_model: str = "deepseek-v4-pro"
    hermes_official_timeout_sec: float = 120.0
    hermes_gateway_url: str = ""
    hermes_gateway_api_key: str = ""
    api_server_key: str = ""
    api_server_port: int = 8642
    asr_provider: str = "mock"
    asr_model: str = "gpt-4o-mini-transcribe"

    device_id: str = "ra8p1_demo_001"
    device_registry_db_path: str = "runtime/device_registry.sqlite3"
    module_binding_db_path: str = "runtime/module_bindings.sqlite3"
    device_registration_secret: str = ""
    log_level: str = Field(default="INFO")
    log_db_path: str = ":temp:"

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
