"""GroqCloud adapter (OpenAI-compatible endpoints): Whisper speech-to-text and chat models.

Used as the instant fallback when every Gemini model is resting. Like Gemini, it keeps
a chain of models and moves a rate-limited request to the next one at once.
"""

from __future__ import annotations

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
    send,
)

BASE_URL = "https://api.groq.com/openai/v1"
# Groq Whisper is used for English speech only: it is weak on Yoruba and Hausa and does not
# support Igbo. Other languages go to Gemini or the Omnilingual speech server first.
WHISPER_LANGUAGES = {"en"}
STT_PREFERENCES = ["whisper-large-v3", "whisper-large-v3-turbo", "whisper"]
LLM_PREFERENCES = ["llama-3.3-70b", "gpt-oss-120b", "llama-4", "qwen", "gpt-oss", "llama", "mixtral", "gemma"]
LLM_EXCLUDE = ("whisper", "guard", "tts", "playai", "distil", "orpheus")
CHAIN_LENGTH = 3


def ordered_models(available: list[str], preferences: list[str], exclude: tuple[str, ...] = (),
                   limit: int = CHAIN_LENGTH) -> list[str]:
    """Up to `limit` distinct models from the live list, in preference order."""
    usable = [m for m in available if not any(x in m.lower() for x in exclude)]
    chosen: list[str] = []
    for pref in preferences:
        for model in usable:
            if pref in model.lower() and model not in chosen:
                chosen.append(model)
                if len(chosen) >= limit:
                    return chosen
    return chosen


class GroqProvider:
    name = "groq"

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
        return {"Authorization": f"Bearer {self.api_key}"}

    async def list_models(self) -> list[str]:
        if self._models is None and time.monotonic() < self._list_retry_at:
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, f"{self.name} model list is temporarily unavailable.")
        if self._models is None:
            self._list_retry_at = time.monotonic() + 60  # until this listing succeeds
            req = self.client.build_request("GET", f"{BASE_URL}/models", headers=self._headers, timeout=15)
            data = await send(self.client, self.name, QuotaTracker(daily_budget=UNLIMITED), req)
            self._models = sorted(m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m)
        return self._models

    async def chain(self, kind: str) -> list[str]:
        explicit = self.stt_model if kind == "stt" else self.llm_model
        try:
            available = await self.list_models()
        except VicoError:
            if not explicit:
                raise
            available = []  # the chosen model can still be tried directly
        chain = (ordered_models(available, STT_PREFERENCES) if kind == "stt"
                 else ordered_models(available, LLM_PREFERENCES, LLM_EXCLUDE))
        if explicit:
            chain = [explicit] + [m for m in chain if m != explicit]
        if not chain:
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE,
                            f"Groq lists no {'speech' if kind == 'stt' else 'chat'} model for this account.")
        return chain

    def cooldowns(self) -> dict[str, float]:
        return self.models.cooldowns()

    def cooldown_s(self) -> float:
        return self.models.cooldown_s()

    async def transcribe(self, audio: bytes, mime: str, language: str | None) -> Transcript:
        if language is not None and language not in WHISPER_LANGUAGES:
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE,
                            "Groq Whisper is only used for English; set up Gemini or a speech server for this language.")
        form = {"temperature": "0", "response_format": "verbose_json"}
        if language in WHISPER_LANGUAGES:
            form["language"] = str(language)
        ext = "wav" if "wav" in mime else "webm"
        seconds = max(0.0, (len(audio) - 44) / 32000)  # 16 kHz mono 16-bit WAV

        async def attempt(model: str, tracker: QuotaTracker) -> dict:
            req = self.client.build_request(
                "POST", f"{BASE_URL}/audio/transcriptions", headers=self._headers, data={**form, "model": model},
                files={"file": (f"audio.{ext}", audio, mime)}, timeout=60,
            )
            return await send(self.client, self.name, tracker, req, audio_seconds=seconds)

        started = time.monotonic()
        data, model = await self.models.run(await self.chain("stt"), attempt, seconds)
        text = data.get("text")
        if not isinstance(text, str):
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, "Groq returned no transcript.", status=502)
        detected = normalize_language(data.get("language"))
        if language is None and detected not in (None, "en"):
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE,
                            "Groq Whisper heard a language other than English, which it is not used for.")
        return Transcript(text=text.strip(), language=language or detected or "en", provider=self.name,
                          model=model, latency_ms=int((time.monotonic() - started) * 1000))

    async def complete(self, system: str, user: str, *, json_mode: bool) -> Completion:
        async def attempt(model: str, tracker: QuotaTracker) -> str:
            body: dict = {"model": model, "temperature": 0,
                          "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            req = self.client.build_request("POST", f"{BASE_URL}/chat/completions", headers=self._headers,
                                            json=body, timeout=45)
            data = await send(self.client, self.name, tracker, req)
            try:
                return data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as exc:
                raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, "Groq returned an empty answer.", status=502) from exc

        started = time.monotonic()
        text, model = await self.models.run(await self.chain("llm"), attempt)
        return Completion(text=text, provider=self.name, model=model,
                          latency_ms=int((time.monotonic() - started) * 1000))
