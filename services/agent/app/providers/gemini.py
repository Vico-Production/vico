"""Google Gemini API adapter: text generation and audio transcription via generateContent.

Requests go to a chain of free-tier Flash models. When one model hits a rate limit, the
same request moves to the next model at once, so a long task keeps going without the
user noticing. Each model has its own cooldown; only when every model in the chain is
cooling down does the caller see a RATE_LIMITED error (with how long to wait).
"""

from __future__ import annotations

import base64
import time

import httpx

from app.contracts import LANGUAGE_NAMES, ErrorCode, VicoError
from app.providers.base import Completion, QuotaTracker, Transcript, send

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
EXCLUDE = ("image", "tts", "live", "embedding", "audio", "aqa", "vision", "learnlm", "veo", "imagen")
# Both listed as "Free of charge" on the Gemini API pricing page (checked 2026-10-14).
# Only models the account's live /models list actually returns are used.
FREE_CHAIN = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
UNLIMITED = 10**9  # Vico's own daily budget is enforced on the provider-level tracker


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
        self._model_quota: dict[str, QuotaTracker] = {}

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key}

    async def list_models(self) -> list[str]:
        if self._models is None:
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
        available = await self.list_models()
        chain = [m for m in FREE_CHAIN if m in available]
        if not chain:
            fallback = choose_gemini_model(available)
            chain = [fallback] if fallback else []
        if explicit:
            chain = [explicit] + [m for m in chain if m != explicit]
        if not chain:
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, "Gemini lists no Flash model for this account.")
        return chain

    def _tracker(self, model: str) -> QuotaTracker:
        if model not in self._model_quota:
            self._model_quota[model] = QuotaTracker(daily_budget=UNLIMITED)
        return self._model_quota[model]

    def cooldowns(self) -> dict[str, float]:
        """Seconds left before each rate-limited model can be used again."""
        return {m: round(q.cooldown_s(), 1) for m, q in self._model_quota.items() if q.cooldown_s() > 0}

    def cooldown_s(self) -> float:
        """Seconds until any model is usable again; 0 when at least one model is ready."""
        if not self._models:
            return 0.0
        chain = [m for m in FREE_CHAIN if m in self._models] or list(self._model_quota)
        waits = [self._tracker(m).cooldown_s() for m in chain]
        return round(min(waits), 1) if waits and all(w > 0 for w in waits) else 0.0

    async def _generate(self, kind: str, body: dict, audio_seconds: float = 0.0) -> tuple[str, str]:
        last: VicoError | None = None
        for model in await self.chain(kind):
            tracker = self._tracker(model)
            if tracker.cooldown_s() > 0:
                continue
            self.quota.check(self.name)  # Vico's own daily request budget
            req = self.client.build_request("POST", f"{BASE_URL}/models/{model}:generateContent",
                                            headers=self._headers, json=body, timeout=60)
            try:
                data = await send(self.client, self.name, tracker, req, audio_seconds=audio_seconds)
            except VicoError as exc:
                if exc.code is ErrorCode.RATE_LIMITED:
                    last = exc  # switch to the next model straight away
                    continue
                raise
            self.quota.record(audio_seconds)
            try:
                parts = data["candidates"][0]["content"]["parts"]
                return "".join(p.get("text", "") for p in parts), model
            except (KeyError, IndexError, TypeError) as exc:
                reason = data.get("promptFeedback", {}).get("blockReason") if isinstance(data, dict) else None
                raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE,
                                f"Gemini returned no answer{f' ({reason})' if reason else ''}.", status=502) from exc
        wait = self.cooldown_s() or (last.retry_after_s if last else 20.0) or 20.0
        message = last.message if last else f"Your Gemini key is cooling down for {wait:.0f}s."
        raise VicoError(ErrorCode.RATE_LIMITED, message, retryable=True, retry_after_s=wait, status=429)

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

    async def transcribe(self, audio: bytes, mime: str, language: str) -> Transcript:
        lang_name = LANGUAGE_NAMES.get(language, language)  # type: ignore[call-overload]
        prompt = (f"Transcribe this {lang_name} speech exactly as spoken, keeping diacritics and any English "
                  "words. Return only the transcript text, nothing else. If there is no speech, return an empty string.")
        body = {"contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode("ascii")}},
            {"text": prompt}]}], "generationConfig": {"temperature": 0}}
        started = time.monotonic()
        text, model = await self._generate("stt", body, audio_seconds=max(0.0, (len(audio) - 44) / 32000))
        return Transcript(text=text.strip(), language=language, provider=self.name, model=model,
                          latency_ms=int((time.monotonic() - started) * 1000))
