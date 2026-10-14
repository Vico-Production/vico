"""Google Gemini API adapter: text generation and audio transcription via generateContent."""

from __future__ import annotations

import base64
import time

import httpx

from app.contracts import LANGUAGE_NAMES, ErrorCode, VicoError
from app.providers.base import Completion, QuotaTracker, Transcript, send

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
EXCLUDE = ("image", "tts", "live", "embedding", "audio", "aqa", "vision", "learnlm", "veo", "imagen")


def choose_gemini_model(models: list[str]) -> str | None:
    """Prefer stable Flash models, newest first; fall back to preview Flash models."""
    flash = [m for m in models if "flash" in m.lower() and not any(x in m.lower() for x in EXCLUDE)]
    stable = sorted((m for m in flash if "preview" not in m and "exp" not in m), reverse=True)
    rest = sorted((m for m in flash if m not in stable), reverse=True)
    ordered = stable + rest
    return ordered[0] if ordered else None


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, client: httpx.AsyncClient, quota: QuotaTracker,
                 stt_model: str | None = None, llm_model: str | None = None):
        self.api_key = api_key
        self.client = client
        self.quota = quota
        self.stt_model = stt_model
        self.llm_model = llm_model
        self._models: list[str] | None = None

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key}

    async def list_models(self) -> list[str]:
        if self._models is None:
            req = self.client.build_request("GET", f"{BASE_URL}/models", params={"pageSize": 200},
                                            headers=self._headers, timeout=15)
            data = await send(self.client, self.name, self.quota, req)
            self._models = sorted(
                m["name"].removeprefix("models/") for m in data.get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
            )
        return self._models

    async def _model(self, kind: str) -> str:
        explicit = self.stt_model if kind == "stt" else self.llm_model
        if explicit:
            return explicit
        chosen = choose_gemini_model(await self.list_models())
        if not chosen:
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, "Gemini lists no Flash model for this account.")
        return chosen

    async def _generate(self, model: str, body: dict, audio_seconds: float = 0.0) -> str:
        req = self.client.build_request("POST", f"{BASE_URL}/models/{model}:generateContent",
                                        headers=self._headers, json=body, timeout=60)
        data = await send(self.client, self.name, self.quota, req, audio_seconds=audio_seconds)
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError) as exc:
            reason = data.get("promptFeedback", {}).get("blockReason") if isinstance(data, dict) else None
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE,
                            f"Gemini returned no answer{f' ({reason})' if reason else ''}.", status=502) from exc

    async def complete(self, system: str, user: str, *, json_mode: bool) -> Completion:
        model = await self._model("llm")
        config: dict = {"temperature": 0}
        if json_mode:
            config["responseMimeType"] = "application/json"
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": config}
        started = time.monotonic()
        text = await self._generate(model, body)
        return Completion(text=text, provider=self.name, model=model,
                          latency_ms=int((time.monotonic() - started) * 1000))

    async def transcribe(self, audio: bytes, mime: str, language: str) -> Transcript:
        model = await self._model("stt")
        lang_name = LANGUAGE_NAMES.get(language, language)  # type: ignore[call-overload]
        prompt = (f"Transcribe this {lang_name} speech exactly as spoken, keeping diacritics and any English "
                  "words. Return only the transcript text, nothing else. If there is no speech, return an empty string.")
        body = {"contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode("ascii")}},
            {"text": prompt}]}], "generationConfig": {"temperature": 0}}
        started = time.monotonic()
        text = await self._generate(model, body, audio_seconds=max(0.0, (len(audio) - 44) / 32000))
        return Transcript(text=text.strip(), language=language, provider=self.name, model=model,
                          latency_ms=int((time.monotonic() - started) * 1000))
