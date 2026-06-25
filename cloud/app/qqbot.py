from __future__ import annotations

import binascii
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cloud.app.config import Settings


_ACCESS_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_PROCESSED_MESSAGE_IDS: dict[str, float] = {}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QQBotMessageEvent:
    event_type: str
    msg_id: str
    text: str
    conversation_key: str
    user_openid: str
    group_openid: str = ""


def qqbot_is_configured(settings: Settings) -> bool:
    return bool(
        settings.qqbot_enabled
        and settings.qqbot_app_id.strip()
        and settings.qqbot_app_secret.strip()
    )


def qqbot_verify_request_signature(
    *,
    bot_secret: str,
    signature_hex: str,
    timestamp: str,
    body: bytes,
) -> bool:
    if not bot_secret or not signature_hex or not timestamp:
        return False
    public_key = _qqbot_private_key(bot_secret).public_key()
    try:
        signature = binascii.unhexlify(signature_hex.strip())
    except (binascii.Error, ValueError):
        return False
    try:
        public_key.verify(signature, timestamp.encode("utf-8") + body)
    except InvalidSignature:
        return False
    return True


def qqbot_build_validation_response(*, bot_secret: str, plain_token: str, event_ts: str) -> dict[str, str]:
    signature = _qqbot_private_key(bot_secret).sign((event_ts + plain_token).encode("utf-8")).hex()
    return {
        "plain_token": plain_token,
        "signature": signature,
    }


def qqbot_parse_message_event(payload: dict[str, object]) -> QQBotMessageEvent | None:
    if int(payload.get("op") or 0) != 0:
        return None
    event_type = str(payload.get("t") or "").strip()
    data = payload.get("d")
    if not isinstance(data, dict):
        return None
    msg_id = str(data.get("id") or "").strip()
    text = str(data.get("content") or "").strip()
    author = data.get("author")
    author = author if isinstance(author, dict) else {}
    if event_type == "C2C_MESSAGE_CREATE":
        user_openid = str(author.get("user_openid") or "").strip()
        if not user_openid or not msg_id or not text:
            return None
        return QQBotMessageEvent(
            event_type=event_type,
            msg_id=msg_id,
            text=text,
            conversation_key=f"qqbot:c2c:{user_openid}",
            user_openid=user_openid,
        )
    if event_type == "GROUP_AT_MESSAGE_CREATE":
        group_openid = str(data.get("group_openid") or "").strip()
        member_openid = str(author.get("member_openid") or "").strip()
        if not group_openid or not member_openid or not msg_id or not text:
            return None
        return QQBotMessageEvent(
            event_type=event_type,
            msg_id=msg_id,
            text=text,
            conversation_key=f"qqbot:group:{group_openid}:{member_openid}",
            user_openid=member_openid,
            group_openid=group_openid,
        )
    return None


def qqbot_message_already_processed(message_id: str, *, ttl_sec: int = 600) -> bool:
    _purge_expired_processed_messages(ttl_sec)
    return message_id in _PROCESSED_MESSAGE_IDS


def qqbot_mark_message_processed(message_id: str) -> None:
    if message_id:
        _PROCESSED_MESSAGE_IDS[message_id] = time.time()


def qqbot_fetch_access_token(settings: Settings) -> str:
    if not settings.qqbot_app_id.strip():
        raise ValueError("QQBOT_APP_ID is not configured")
    if not settings.qqbot_app_secret.strip():
        raise ValueError("QQBOT_APP_SECRET is not configured")

    cache_key = settings.qqbot_app_id.strip()
    now = time.time()
    cached = _ACCESS_TOKEN_CACHE.get(cache_key)
    if cached and cached[1] > now:
        return cached[0]

    payload = json.dumps(
        {
            "appId": settings.qqbot_app_id.strip(),
            "clientSecret": settings.qqbot_app_secret.strip(),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://bots.qq.com/app/getAppAccessToken",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"QQ Bot access token request failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"QQ Bot access token request failed: {exc}") from exc

    access_token = str(decoded.get("access_token") or "").strip()
    expires_in = int(decoded.get("expires_in") or 0)
    if not access_token or expires_in <= 0:
        raise ValueError(f"QQ Bot access token response is invalid: {decoded}")

    _ACCESS_TOKEN_CACHE[cache_key] = (access_token, now + max(60, expires_in - 60))
    return access_token


def qqbot_fetch_gateway_url(settings: Settings) -> str:
    access_token = qqbot_fetch_access_token(settings)
    request = urllib.request.Request(
        "https://api.sgroup.qq.com/gateway",
        method="GET",
        headers={
            "Authorization": f"QQBot {access_token}",
            "X-Union-Appid": settings.qqbot_app_id.strip(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"QQ Bot gateway request failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"QQ Bot gateway request failed: {exc}") from exc
    gateway_url = str(decoded.get("url") or "").strip()
    if not gateway_url:
        raise ValueError(f"QQ Bot gateway response is invalid: {decoded}")
    return gateway_url


def qqbot_send_text_reply(
    event: QQBotMessageEvent,
    content: str,
    settings: Settings,
) -> dict[str, object]:
    access_token = qqbot_fetch_access_token(settings)
    body: dict[str, object] = {
        "content": _truncate_message(content),
        "msg_type": 0,
        "msg_id": event.msg_id,
        "msg_seq": 1,
    }
    if event.event_type == "GROUP_AT_MESSAGE_CREATE":
        path = f"/v2/groups/{event.group_openid}/messages"
    elif event.event_type == "C2C_MESSAGE_CREATE":
        path = f"/v2/users/{event.user_openid}/messages"
    else:
        raise ValueError(f"unsupported QQ Bot event type: {event.event_type}")
    request = urllib.request.Request(
        "https://api.sgroup.qq.com" + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"QQBot {access_token}",
            "Content-Type": "application/json",
            "X-Union-Appid": settings.qqbot_app_id.strip(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"QQ Bot send message failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"QQ Bot send message failed: {exc}") from exc


def qqbot_send_proactive_text(
    *,
    channel: str,
    target_id: str,
    content: str,
    settings: Settings,
) -> dict[str, object]:
    access_token = qqbot_fetch_access_token(settings)
    if channel == "qq_group":
        path = f"/v2/groups/{target_id}/messages"
    elif channel == "qq_c2c":
        path = f"/v2/users/{target_id}/messages"
    else:
        raise ValueError(f"unsupported QQ Bot proactive channel: {channel}")
    body = {
        "content": _truncate_message(content),
        "msg_type": 0,
        "msg_seq": int(time.time()) % 100000,
    }
    request = urllib.request.Request(
        "https://api.sgroup.qq.com" + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"QQBot {access_token}",
            "Content-Type": "application/json",
            "X-Union-Appid": settings.qqbot_app_id.strip(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"QQ Bot proactive message failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"QQ Bot proactive message failed: {exc}") from exc


def _qqbot_private_key(bot_secret: str) -> Ed25519PrivateKey:
    seed = bot_secret
    while len(seed.encode("utf-8")) < 32:
        seed = seed + seed
    seed_bytes = seed.encode("utf-8")[:32]
    return Ed25519PrivateKey.from_private_bytes(seed_bytes)


def _purge_expired_processed_messages(ttl_sec: int) -> None:
    now = time.time()
    expired = [
        message_id
        for message_id, seen_at in _PROCESSED_MESSAGE_IDS.items()
        if now - seen_at > ttl_sec
    ]
    for message_id in expired:
        _PROCESSED_MESSAGE_IDS.pop(message_id, None)


def _truncate_message(content: str, *, limit: int = 1500) -> str:
    text = (content or "").strip()
    if not text:
        return "已收到消息，但当前没有可返回的内容。"
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
