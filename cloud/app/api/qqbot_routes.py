from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from cloud.app.agent_service.orchestrator import AgentOrchestrator
from cloud.app.api.web_routes import get_device_registry, get_orchestrator
from cloud.app.config import Settings, get_settings
from cloud.app.device_registry import DeviceRegistry
from cloud.app.qqbot import (
    qqbot_build_validation_response,
    qqbot_is_configured,
    qqbot_mark_message_processed,
    qqbot_message_already_processed,
    qqbot_parse_message_event,
    qqbot_send_text_reply,
    qqbot_verify_request_signature,
)
from cloud.app.qqbot_runtime import generate_qqbot_reply


router = APIRouter()


@router.post("/qqbot/callback")
async def qqbot_callback(
    request: Request,
    settings: Settings = Depends(get_settings),
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    registry: DeviceRegistry = Depends(get_device_registry),
    x_signature_ed25519: str = Header(default="", alias="X-Signature-Ed25519"),
    x_signature_timestamp: str = Header(default="", alias="X-Signature-Timestamp"),
    x_bot_appid: str = Header(default="", alias="X-Bot-Appid"),
) -> dict[str, object]:
    if not qqbot_is_configured(settings):
        raise HTTPException(status_code=503, detail="QQ Bot is not configured")
    if x_bot_appid.strip() and x_bot_appid.strip() != settings.qqbot_app_id.strip():
        raise HTTPException(status_code=401, detail="QQ Bot app id mismatch")

    body = await request.body()
    if not qqbot_verify_request_signature(
        bot_secret=settings.qqbot_app_secret,
        signature_hex=x_signature_ed25519,
        timestamp=x_signature_timestamp,
        body=body,
    ):
        raise HTTPException(status_code=401, detail="invalid QQ Bot callback signature")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid QQ Bot callback body: {exc}") from exc

    if int(payload.get("op") or 0) == 13:
        data = payload.get("d")
        data = data if isinstance(data, dict) else {}
        plain_token = str(data.get("plain_token") or "").strip()
        event_ts = str(data.get("event_ts") or "").strip()
        if not plain_token or not event_ts:
            raise HTTPException(status_code=400, detail="missing QQ Bot validation fields")
        return qqbot_build_validation_response(
            bot_secret=settings.qqbot_app_secret,
            plain_token=plain_token,
            event_ts=event_ts,
        )

    event = qqbot_parse_message_event(payload)
    if event is None:
        return {"op": 12}
    if qqbot_message_already_processed(event.msg_id):
        return {"op": 12, "duplicate": True}

    try:
        reply_text = generate_qqbot_reply(event, settings, orchestrator, registry)
    except Exception:
        reply_text = "服务器刚才处理这条指令时失败了，请稍后再试。"

    qqbot_send_text_reply(event, reply_text, settings)
    qqbot_mark_message_processed(event.msg_id)
    return {"op": 12}
