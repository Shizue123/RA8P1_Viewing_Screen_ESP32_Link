from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from cloud.app.config import Settings


RUNTIME_MODEL_CONFIG_PATH = Path(__file__).resolve().parents[1] / "runtime" / "model_config.json"
CUSTOM_MODEL_PROFILES_PATH = Path(__file__).resolve().parents[1] / "runtime" / "model_profiles.json"


class ModelSelectionRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=120)


class ModelProfileRequest(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    provider: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=8, max_length=300)
    api_key: str = Field(min_length=1, max_length=500)
    protocol: str = Field(default="openai_compatible", max_length=40)
    description: str = Field(default="", max_length=240)

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        slug = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-")
        if not slug:
            raise ValueError("provider is required")
        return slug[:40]

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        text = value.strip().rstrip("/")
        if not text.startswith(("https://", "http://")):
            raise ValueError("base_url must start with http:// or https://")
        return text

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, value: str) -> str:
        text = value.strip().lower()
        if text != "openai_compatible":
            raise ValueError("only openai_compatible protocol is supported now")
        return text


def _mask_secret(value: object) -> str:
    text = str(value or "")
    if not text:
        return "未配置"
    if len(text) <= 8:
        return "已配置"
    return f"已配置 · ...{text[-4:]}"


def _configured_models(settings: Settings) -> list[dict[str, object]]:
    hermes_gateway_ready = bool(
        settings.hermes_gateway_url.strip()
        and (settings.hermes_gateway_api_key.strip() or settings.api_server_key.strip())
    )
    hermes_cli_ready = bool(
        settings.hermes_official_enabled
        and settings.hermes_official_uv_path.strip()
        and settings.hermes_official_workdir.strip()
        and settings.deepseek_api_key
    )
    hermes_ready = hermes_gateway_ready or hermes_cli_ready
    models: list[dict[str, object]] = [
        {
            "provider": "hermes_official",
            "model": settings.hermes_official_model,
            "label": "Hermes Agent",
            "version": settings.hermes_official_model,
            "description": "Hermes 负责理解、规划和工具编排，底层使用 DeepSeek 推理。",
            "ready": hermes_ready,
            "key_status": "Hermes + DeepSeek 已连接" if hermes_ready else "Hermes 运行时未连接",
            "tier": "cloud-agent",
        },
        {
            "provider": "deepseek",
            "model": settings.deepseek_model,
            "label": "DeepSeek Direct",
            "version": settings.deepseek_model,
            "description": "直接调用 DeepSeek 工具接口，跳过 Hermes 编排层。",
            "ready": bool(settings.deepseek_api_key),
            "key_status": "已配置" if settings.deepseek_api_key else "缺少 DEEPSEEK_API_KEY",
            "tier": "direct-api",
        },
    ]
    models.extend(_custom_model_entries())
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, object]] = []
    for item in models:
        key = (str(item["provider"]), str(item["model"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _read_custom_profiles() -> list[dict[str, object]]:
    try:
        data = json.loads(CUSTOM_MODEL_PROFILES_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    profiles = data.get("profiles") if isinstance(data, dict) else None
    return [item for item in profiles if isinstance(item, dict)] if isinstance(profiles, list) else []


def _write_custom_profiles(profiles: list[dict[str, object]]) -> None:
    CUSTOM_MODEL_PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CUSTOM_MODEL_PROFILES_PATH.write_text(
        json.dumps({"profiles": profiles}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _custom_model_entries() -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for profile in _read_custom_profiles():
        provider = str(profile.get("provider") or "").strip()
        model = str(profile.get("model") or "").strip()
        base_url = str(profile.get("base_url") or "").strip()
        api_key = str(profile.get("api_key") or "")
        if not provider or not model or not base_url:
            continue
        entries.append(
            {
                "id": profile.get("id") or f"{provider}:{model}",
                "provider": provider,
                "model": model,
                "label": profile.get("label") or provider,
                "version": model,
                "description": profile.get("description") or "自定义 OpenAI-compatible 模型配置。",
                "ready": bool(api_key),
                "key_status": _mask_secret(api_key),
                "tier": profile.get("tier") or "custom",
                "protocol": profile.get("protocol") or "openai_compatible",
                "base_url": base_url,
                "custom": True,
            }
        )
    return entries


def _read_runtime_selection() -> dict[str, object]:
    try:
        data = json.loads(RUNTIME_MODEL_CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _default_selection(settings: Settings) -> dict[str, object]:
    provider = settings.llm_provider
    model = settings.deepseek_model if provider == "deepseek" else settings.hermes_official_model
    if provider == "template":
        model = "rule-based-v1"
    return {"provider": provider, "model": model}


def model_config_view(settings: Settings) -> dict[str, object]:
    configured = _configured_models(settings)
    runtime = _read_runtime_selection()
    default_selection = _default_selection(settings)
    provider = str(runtime.get("provider") or default_selection["provider"])
    model = str(runtime.get("model") or default_selection["model"])
    active = next(
        (
            item
            for item in configured
            if item["provider"] == provider and item["model"] == model
        ),
        {
            "provider": provider,
            "model": model,
            "label": provider,
            "version": model,
            "description": "运行时自定义模型。",
            "ready": True,
            "key_status": "运行时配置",
            "tier": "custom",
        },
    )
    return {
        "active": active,
        "configured": configured,
        "default": default_selection,
        "runtime_override": bool(runtime),
        "updated_at": runtime.get("updated_at"),
    }


def effective_model_settings(settings: Settings) -> Settings:
    view = model_config_view(settings)
    active = view["active"] if isinstance(view.get("active"), dict) else {}
    provider = str(active.get("provider") or settings.llm_provider)
    model = str(active.get("model") or settings.deepseek_model)
    updates: dict[str, Any] = {"llm_provider": provider}
    if active.get("custom"):
        updates.update(
            {
                "llm_provider": "deepseek",
                "deepseek_model": model,
                "deepseek_base_url": str(active.get("base_url") or settings.deepseek_base_url),
            }
        )
        profile = next(
            (
                item
                for item in _read_custom_profiles()
                if item.get("provider") == provider and item.get("model") == model
            ),
            {},
        )
        updates["deepseek_api_key"] = str(profile.get("api_key") or "")
    elif provider == "deepseek":
        updates["deepseek_model"] = model
    elif provider == "hermes_official":
        updates["hermes_official_model"] = model
    return settings.model_copy(update=updates)


def update_model_selection(settings: Settings, selection: ModelSelectionRequest) -> dict[str, object]:
    provider = selection.provider.strip()
    model = selection.model.strip()
    configured = _configured_models(settings)
    selected = next(
        (
            item
            for item in configured
            if item["provider"] == provider and item["model"] == model
        ),
        None,
    )
    if selected is None:
        raise ValueError("model is not in configured model list")
    if not selected.get("ready"):
        raise ValueError("model runtime is not ready")
    RUNTIME_MODEL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_MODEL_CONFIG_PATH.write_text(
        json.dumps(
            {"provider": provider, "model": model, "updated_at": int(time.time())},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return model_config_view(settings)


def create_model_profile(settings: Settings, payload: ModelProfileRequest) -> dict[str, object]:
    profiles = _read_custom_profiles()
    provider = payload.provider
    model = payload.model.strip()
    profiles = [
        item
        for item in profiles
        if not (item.get("provider") == provider and item.get("model") == model)
    ]
    profiles.append(
        {
            "id": secrets.token_urlsafe(12),
            "label": payload.label.strip(),
            "provider": provider,
            "model": model,
            "base_url": payload.base_url,
            "api_key": payload.api_key,
            "protocol": payload.protocol,
            "description": payload.description.strip() or "自定义 OpenAI-compatible 模型配置。",
            "tier": "custom",
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
        }
    )
    _write_custom_profiles(profiles)
    return model_config_view(settings)


def delete_model_profile(settings: Settings, provider: str, model: str) -> dict[str, object]:
    provider = provider.strip().lower()
    model = model.strip()
    profiles = [
        item
        for item in _read_custom_profiles()
        if not (item.get("provider") == provider and item.get("model") == model)
    ]
    _write_custom_profiles(profiles)
    runtime = _read_runtime_selection()
    if runtime.get("provider") == provider and runtime.get("model") == model:
        try:
            RUNTIME_MODEL_CONFIG_PATH.unlink()
        except FileNotFoundError:
            pass
    return model_config_view(settings)
