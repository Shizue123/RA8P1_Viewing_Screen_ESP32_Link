from __future__ import annotations

import json
import mimetypes
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass

from cloud.app.config import Settings


@dataclass(frozen=True)
class Transcription:
    text: str
    provider: str
    model: str


def transcribe_audio(
    *,
    settings: Settings,
    audio: bytes,
    filename: str,
    content_type: str,
    mock_transcript: str = "",
) -> Transcription:
    if not audio:
        raise ValueError("audio payload is empty")

    provider = settings.asr_provider.lower()
    if provider == "mock":
        text = _mock_transcribe(audio, mock_transcript)
        return Transcription(text=text, provider="mock", model="mock-asr-v1")
    if provider == "openai":
        text = _openai_transcribe(settings, audio, filename, content_type)
        return Transcription(text=text, provider="openai", model=settings.asr_model)
    raise ValueError(f"unsupported ASR provider: {settings.asr_provider}")


def _mock_transcribe(audio: bytes, mock_transcript: str) -> str:
    if mock_transcript.strip():
        return mock_transcript.strip()
    try:
        decoded = audio.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("mock ASR requires X-Mock-Transcript for binary audio") from exc
    if not decoded:
        raise ValueError("mock ASR transcript is empty")
    return decoded


def _openai_transcribe(settings: Settings, audio: bytes, filename: str, content_type: str) -> str:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required when ASR_PROVIDER=openai")

    boundary = "----embedded-agent-" + uuid.uuid4().hex
    body = _multipart_body(
        boundary=boundary,
        fields={"model": settings.asr_model, "response_format": "json"},
        files={
            "file": (
                filename or "audio.wav",
                content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
                audio,
            )
        },
    )
    request = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=body,
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI ASR failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI ASR failed: {exc.reason}") from exc

    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("OpenAI ASR response did not contain text")
    return text.strip()


def _multipart_body(
    *,
    boundary: str,
    fields: dict[str, str],
    files: dict[str, tuple[str, str, bytes]],
) -> bytes:
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    for name, (filename, content_type, content) in files.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
                content,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks)
