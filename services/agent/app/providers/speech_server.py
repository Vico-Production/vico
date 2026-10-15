"""Client for the user's own Vico Speech Server (services/speech_server).

- "omnilingual": Meta Omnilingual ASR, for Yoruba, Hausa and Igbo speech Groq Whisper
  handles poorly or not at all.
- voice replies: YarnGPT Nigerian voices.

The server address is a setting and its token lives in the credential store. Audio is
sent as in-memory WAV bytes, only after the user's cloud consent (checked by the hub).
"""

from __future__ import annotations

import base64
import time
from typing import Any

import httpx

from app.contracts import ErrorCode, VicoError
from app.providers.base import QuotaTracker, Transcript, send

ASR_MODEL = "omniASR_CTC_300M"
VOICE_LANGUAGES = ("en", "yo", "ha", "ig")


def _clean_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.lower().startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise VicoError(ErrorCode.VALIDATION_ERROR,
                        "Use an https:// address for the speech server (plain http only for this computer).")
    return url


class SpeechServer:
    def __init__(self, url: str, token: str, client: httpx.AsyncClient, quota: QuotaTracker):
        self.url = _clean_url(url)
        self.token = token
        self.client = client
        self.quota = quota

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def health(self) -> dict[str, Any]:
        req = self.client.build_request("GET", f"{self.url}/v1/health", headers=self._headers, timeout=10)
        return await send(self.client, "speech server", self.quota, req)


class OmnilingualProvider:
    """Speech-to-text through the speech server. Language-independent (CTC model)."""

    name = "omnilingual"

    def __init__(self, server: SpeechServer):
        self.server = server

    async def list_models(self) -> list[str]:
        return [ASR_MODEL]

    def cooldown_s(self) -> float:
        return self.server.quota.cooldown_s()

    async def transcribe(self, audio: bytes, mime: str, language: str | None) -> Transcript:
        if "wav" not in mime:
            raise VicoError(ErrorCode.UNSUPPORTED, "The speech server accepts WAV audio only.")
        params = {"language": language} if language else None
        headers = {**self.server._headers, "Content-Type": "audio/wav"}
        req = self.server.client.build_request("POST", f"{self.server.url}/v1/transcribe", params=params,
                                               headers=headers, content=audio, timeout=90)
        started = time.monotonic()
        seconds = max(0.0, (len(audio) - 44) / 32000)
        data = await send(self.server.client, "speech server", self.server.quota, req, audio_seconds=seconds)
        text = data.get("text")
        if not isinstance(text, str):
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, "The speech server returned no transcript.", status=502)
        return Transcript(text=text.strip(), language=language or "auto", provider=self.name,
                          model=str(data.get("model") or ASR_MODEL),
                          latency_ms=int((time.monotonic() - started) * 1000))


class VoiceProvider:
    """Spoken replies (YarnGPT) through the speech server."""

    name = "yarngpt"

    def __init__(self, server: SpeechServer):
        self.server = server

    async def speak(self, text: str, language: str) -> dict[str, Any]:
        if language not in VOICE_LANGUAGES:
            raise VicoError(ErrorCode.UNSUPPORTED, f"No voice for '{language}'.")
        req = self.server.client.build_request(
            "POST", f"{self.server.url}/v1/speak", headers=self.server._headers,
            json={"text": text[:600], "language": language}, timeout=120)
        self.server.quota.check("speech server")
        try:
            response = await self.server.client.send(req)
        except httpx.TimeoutException as exc:
            raise VicoError(ErrorCode.TIMEOUT, "The voice took too long.", retryable=True, status=504) from exc
        except httpx.TransportError as exc:
            raise VicoError(ErrorCode.OFFLINE, "Cannot reach the speech server.", retryable=True, status=503) from exc
        self.server.quota.record()
        if response.status_code == 401:
            raise VicoError(ErrorCode.PROVIDER_AUTH, "The speech server rejected the token.", status=401)
        if response.status_code >= 400 or not response.headers.get("content-type", "").startswith("audio/wav"):
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, "The speech server could not speak this.", status=502)
        # Returned to the UI as base64 to play from memory; never saved.
        return {"audio_b64": base64.b64encode(response.content).decode("ascii"), "mime": "audio/wav",
                "model": response.headers.get("x-model", "YarnGPT2b"),
                "latency_ms": int(response.headers.get("x-latency-ms", "0") or 0)}
