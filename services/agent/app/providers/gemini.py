"""Google Gemini API adapter: text generation and audio transcription via generateContent.

Requests go to a chain of free-tier Flash models (see ModelChain): a rate-limited model
is replaced by the next one inside the same request, so long tasks keep going.
"""

from __future__ import annotations

import base64
import time

import httpx

from app.contracts import ErrorCode, VicoError
from app.providers.base import (
    UNLIMITED,
    Completion,
    ModelChain,
    QuotaTracker,
    Transcript,
    normalize_language,
    parse_json_text,
    send,
)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
EXCLUDE = ("image", "tts", "live", "embedding", "audio", "aqa", "vision", "learnlm", "veo", "imagen")
# Both listed as "Free of charge" on the Gemini API pricing page (checked 2026-10-14).
# Only models the account's live /models list actually returns are used.
FREE_CHAIN = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]

TRANSCRIBE_PROMPT = (
    "Transcribe this speech exactly as spoken. The speaker uses English, Yoruba, Hausa, Igbo or Nigerian Pidgin, "
    "possibly mixed. Keep diacritics and tone marks, and keep English words in English. Reply with JSON "
    '{"language": "<en|yo|ha|ig|pcm, the main language spoken>", "text": "<the transcript>"}. '
    'If there is no speech, reply {"language": "en", "text": ""}.'
)


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
        self._list_retry_at = 0.0
        self.models = ModelChain(self.name, quota)

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key}

    async def list_models(self) -> list[str]:
        if self._models is None and time.monotonic() < self._list_retry_at:
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, f"{self.name} model list is temporarily unavailable.")
        if self._models is None:
            self._list_retry_at = time.monotonic() + 60  # until this listing succeeds
            req = self.client.build_request("GET", f"{BASE_URL}/models", params={"pageSize": 200},
                                            headers=self._headers, timeout=15)
            data = await send(self.client, self.name, QuotaTracker(daily_budget=UNLIMITED), req)
            self._models = sorted(
                m["name"].removeprefix("models/") for m in data.get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
            )
        return self._models

    async def chain(self, kind: str) -> list[str]:
        """Models to try, in order: the user's chosen model first, then the free Flash chain."""
        explicit = self.stt_model if kind == "stt" else self.llm_model
        try:
            available = await self.list_models()
        except VicoError:
            if not explicit:
                raise
            available = []  # the chosen model can still be tried directly
        chain = [m for m in FREE_CHAIN if m in available]
        if not chain:
            fallback = choose_gemini_model(available)
            chain = [fallback] if fallback else []
        if explicit:
            chain = [explicit] + [m for m in chain if m != explicit]
        if not chain:
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, "Gemini lists no Flash model for this account.")
        return chain

    def cooldowns(self) -> dict[str, float]:
        return self.models.cooldowns()

    def cooldown_s(self) -> float:
        return self.models.cooldown_s()

    async def _generate(self, kind: str, body: dict, audio_seconds: float = 0.0) -> tuple[str, str]:
        async def attempt(model: str, tracker: QuotaTracker) -> str:
            req = self.client.build_request("POST", f"{BASE_URL}/models/{model}:generateContent",
                                            headers=self._headers, json=body, timeout=60)
            data = await send(self.client, self.name, tracker, req, audio_seconds=audio_seconds)
            try:
                parts = data["candidates"][0]["content"]["parts"]
                return "".join(p.get("text", "") for p in parts)
            except (KeyError, IndexError, TypeError) as exc:
                reason = data.get("promptFeedback", {}).get("blockReason") if isinstance(data, dict) else None
                raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE,
                                f"Gemini returned no answer{f' ({reason})' if reason else ''}.", status=502) from exc

        return await self.models.run(await self.chain(kind), attempt, audio_seconds)

    async def complete(self, system: str, user: str, *, json_mode: bool) -> Completion:
        config: dict = {"temperature": 0}
        if json_mode:
            config["responseMimeType"] = "application/json"
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": config}
        started = time.monotonic()
        text, model = await self._generate("llm", body)
        return Completion(text=text, provider=self.name, model=model,
                          latency_ms=int((time.monotonic() - started) * 1000))

    async def transcribe(self, audio: bytes, mime: str, language: str | None) -> Transcript:
        prompt = TRANSCRIBE_PROMPT
        if language:
            prompt += f" The speaker said they are using language code '{language}'."
        body = {"contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode("ascii")}},
            {"text": prompt}]}], "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
        started = time.monotonic()
        raw, model = await self._generate("stt", body, audio_seconds=max(0.0, (len(audio) - 44) / 32000))
        try:
            data = parse_json_text(raw)
            text = str(data.get("text", "")).strip()
            detected = normalize_language(data.get("language"))
        except (VicoError, AttributeError):
            text, detected = raw.strip(), None
        return Transcript(text=text, language=language or detected or "en", provider=self.name, model=model,
                          latency_ms=int((time.monotonic() - started) * 1000))
