"""GroqCloud adapter (OpenAI-compatible endpoints): Whisper speech-to-text and chat models."""

from __future__ import annotations

import time

import httpx

from app.contracts import ErrorCode, VicoError
from app.providers.base import Completion, QuotaTracker, Transcript, pick_model, send

BASE_URL = "https://api.groq.com/openai/v1"
# Whisper's published language list includes Yoruba and Hausa but not Igbo or Pidgin.
WHISPER_LANGUAGES = {"en", "yo", "ha"}
STT_PREFERENCES = ["whisper-large-v3", "whisper"]
LLM_PREFERENCES = ["llama-3.3-70b", "gpt-oss-120b", "llama-4", "qwen", "gpt-oss", "llama", "mixtral", "gemma"]
LLM_EXCLUDE = ("whisper", "guard", "tts", "playai", "distil", "orpheus")


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

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def list_models(self) -> list[str]:
        if self._models is None:
            req = self.client.build_request("GET", f"{BASE_URL}/models", headers=self._headers, timeout=15)
            data = await send(self.client, self.name, self.quota, req)
            self._models = sorted(m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m)
        return self._models

    async def _model(self, kind: str) -> str:
        explicit = self.stt_model if kind == "stt" else self.llm_model
        if explicit:
            return explicit
        models = await self.list_models()
        chosen = (pick_model(models, STT_PREFERENCES) if kind == "stt"
                  else pick_model(models, LLM_PREFERENCES, LLM_EXCLUDE))
        if not chosen:
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE,
                            f"Groq lists no {'speech' if kind == 'stt' else 'chat'} model for this account.")
        return chosen

    async def transcribe(self, audio: bytes, mime: str, language: str) -> Transcript:
        model = await self._model("stt")
        form = {"model": model, "temperature": "0", "response_format": "json"}
        if language in WHISPER_LANGUAGES:
            form["language"] = language
        ext = "wav" if "wav" in mime else "webm"
        req = self.client.build_request(
            "POST", f"{BASE_URL}/audio/transcriptions", headers=self._headers, data=form,
            files={"file": (f"audio.{ext}", audio, mime)}, timeout=60,
        )
        started = time.monotonic()
        seconds = max(0.0, (len(audio) - 44) / 32000)  # 16 kHz mono 16-bit WAV
        data = await send(self.client, self.name, self.quota, req, audio_seconds=seconds)
        text = data.get("text")
        if not isinstance(text, str):
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, "Groq returned no transcript.", status=502)
        return Transcript(text=text.strip(), language=language, provider=self.name, model=model,
                          latency_ms=int((time.monotonic() - started) * 1000))

    async def complete(self, system: str, user: str, *, json_mode: bool) -> Completion:
        model = await self._model("llm")
        body: dict = {"model": model, "temperature": 0,
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        req = self.client.build_request("POST", f"{BASE_URL}/chat/completions", headers=self._headers, json=body,
                                        timeout=45)
        started = time.monotonic()
        data = await send(self.client, self.name, self.quota, req)
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, "Groq returned an empty answer.", status=502) from exc
        return Completion(text=text or "", provider=self.name, model=model,
                          latency_ms=int((time.monotonic() - started) * 1000))
