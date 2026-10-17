"""Free OpenAI-compatible APIs: GroqCloud (Whisper and chat), Mistral (chat and Voxtral
speech-to-text) and OpenRouter (its free chat models).

They are the fallbacks behind Gemini, so Vico keeps working when a key is rate-limited or
down. Like Gemini, each keeps a chain of models and moves a rate-limited request to the next
one at once. Free offers checked 2026-10-16: Groq gpt-oss and Qwen models, 1,000 requests a
day each, and Whisper large-v3, 2,000 a day; Mistral's Free plan, $10 of credit a month;
OpenRouter's ":free" models, 50 requests a day.
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
# Languages Whisper is told about; Igbo and Pidgin have no Whisper code, so it detects them.
# Whisper is weaker than Gemini on Yoruba, Hausa and Igbo: it is the fallback, never first.
WHISPER_LANGUAGES = {"en", "yo", "ha"}
STT_PREFERENCES = ["whisper-large-v3", "whisper-large-v3-turbo", "whisper"]
# Groq's free plan has gpt-oss and Qwen (Llama was removed from it in 2026).
LLM_PREFERENCES = ["gpt-oss-120b", "qwen3", "qwen", "kimi", "gpt-oss", "llama-4", "llama", "gemma"]
LLM_EXCLUDE = ("whisper", "guard", "tts", "playai", "distil", "orpheus", "safeguard")
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
    base_url = BASE_URL
    stt_preferences: list[str] = STT_PREFERENCES
    llm_preferences: list[str] = LLM_PREFERENCES
    llm_exclude: tuple[str, ...] = LLM_EXCLUDE
    stt_languages: set[str] | None = WHISPER_LANGUAGES  # None: this provider has no speech-to-text
    json_mode_supported = True

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
            req = self.client.build_request("GET", f"{self.base_url}/models", headers=self._headers, timeout=15)
            data = await send(self.client, self.name, QuotaTracker(daily_budget=UNLIMITED), req)
            self._models = sorted(m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m
                                  and self.usable_model(m))
        return self._models

    def usable_model(self, model: dict) -> bool:
        return True

    async def chain(self, kind: str) -> list[str]:
        explicit = self.stt_model if kind == "stt" else self.llm_model
        try:
            available = await self.list_models()
        except VicoError:
            if not explicit:
                raise
            available = []  # the chosen model can still be tried directly
        chain = (ordered_models(available, self.stt_preferences) if kind == "stt"
                 else ordered_models(available, self.llm_preferences, self.llm_exclude))
        if explicit:
            chain = [explicit] + [m for m in chain if m != explicit]
        if not chain:
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE,
                            f"{self.name} lists no {'speech' if kind == 'stt' else 'chat'} model for this account.")
        return chain

    def cooldowns(self) -> dict[str, float]:
        return self.models.cooldowns()

    def cooldown_s(self) -> float:
        return self.models.cooldown_s()

    async def transcribe(self, audio: bytes, mime: str, language: str | None,
                         hints: list[str] | None = None) -> Transcript:
        if self.stt_languages is None or (self.stt_languages == {"en"} and language not in (None, "en", "pcm")):
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, f"{self.name} does not transcribe this language.")
        form = {"temperature": "0", "response_format": "verbose_json"}
        if language in self.stt_languages:
            form["language"] = str(language)
        if hints:
            # Names the user is likely to say (installed apps, open windows) spelled right.
            form["prompt"] = whisper_prompt(hints)
        ext = "wav" if "wav" in mime else "webm"
        seconds = max(0.0, (len(audio) - 44) / 32000)  # 16 kHz mono 16-bit WAV

        async def attempt(model: str, tracker: QuotaTracker) -> dict:
            req = self.client.build_request(
                "POST", f"{self.base_url}/audio/transcriptions", headers=self._headers, data={**form, "model": model},
                files={"file": (f"audio.{ext}", audio, mime)}, timeout=60,
            )
            return await send(self.client, self.name, tracker, req, audio_seconds=seconds)

        started = time.monotonic()
        data, model = await self.models.run(await self.chain("stt"), attempt, seconds)
        text = data.get("text")
        if not isinstance(text, str):
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, f"{self.name} returned no transcript.", status=502)
        detected = normalize_language(data.get("language"))
        return Transcript(text=text.strip(), language=language or detected or "en", provider=self.name,
                          model=model, latency_ms=int((time.monotonic() - started) * 1000))

    async def speak(self, text: str) -> bytes:
        """English speech from Groq Orpheus (WAV, in memory)."""
        from app.providers.tts import GROQ_TERMS_URL, GROQ_TTS_MODEL, GROQ_VOICE

        if self.name != "groq":
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, f"{self.name} has no voice.")
        try:
            r = await self.client.post(f"{self.base_url}/audio/speech", headers=self._headers, timeout=30,
                                       json={"model": GROQ_TTS_MODEL, "input": text[:4000], "voice": GROQ_VOICE,
                                             "response_format": "wav"})
        except httpx.HTTPError as exc:
            raise VicoError(ErrorCode.OFFLINE, "Groq's voice could not be reached.", retryable=True) from exc
        if r.status_code == 400 and "terms" in r.text:
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, "To use Groq's free voice, accept its terms once in "
                            f"your Groq account: {GROQ_TERMS_URL}")
        if r.status_code == 429:
            raise VicoError(ErrorCode.RATE_LIMITED, "Groq's voice is resting.", retryable=True, retry_after_s=20)
        if r.status_code >= 400 or not r.content.startswith(b"RIFF"):
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, f"Groq's voice failed ({r.status_code}).", retryable=True)
        return r.content

    async def complete(self, system: str, user: str, *, json_mode: bool) -> Completion:
        async def attempt(model: str, tracker: QuotaTracker) -> str:
            body: dict = {"model": model, "temperature": 0,
                          "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            if json_mode and self.json_mode_supported:
                body["response_format"] = {"type": "json_object"}
            req = self.client.build_request("POST", f"{self.base_url}/chat/completions", headers=self._headers,
                                            json=body, timeout=45)
            data = await send(self.client, self.name, tracker, req)
            try:
                return data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as exc:
                raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, f"{self.name} returned an empty answer.",
                                status=502) from exc

        started = time.monotonic()
        text, model = await self.models.run(await self.chain("llm"), attempt)
        return Completion(text=text, provider=self.name, model=model,
                          latency_ms=int((time.monotonic() - started) * 1000))


def whisper_prompt(hints: list[str], limit: int = 600) -> str:
    """A short spelling list for Whisper's prompt (it reads about 224 tokens)."""
    out = "Vico."
    for name in hints:
        if len(out) + len(name) + 2 > limit:
            break
        out += f" {name},"
    return out.rstrip(",") + "."


class MistralProvider(GroqProvider):
    """Mistral's free plan: Mistral chat models, and Voxtral speech-to-text for English."""

    name = "mistral"
    base_url = "https://api.mistral.ai/v1"
    stt_preferences = ["voxtral-mini-transcribe", "voxtral-mini-latest", "voxtral-mini", "voxtral"]
    llm_preferences = ["mistral-medium", "mistral-large", "mistral-small", "magistral-small", "ministral"]
    llm_exclude = ("embed", "moderation", "ocr", "voxtral", "codestral", "devstral", "pixtral")
    stt_languages = {"en"}


class OpenRouterProvider(GroqProvider):
    """OpenRouter's free chat models (ids ending in ":free"), as the last cloud fallback."""

    name = "openrouter"
    base_url = "https://openrouter.ai/api/v1"
    llm_preferences = ["gpt-oss-120b", "qwen3", "llama-4", "deepseek", "gemma", "mistral", "qwen", "llama", ""]
    llm_exclude = ("vision", "embed", "audio")
    stt_languages = None
    json_mode_supported = False  # not every free model accepts it; the prompt asks for JSON

    def usable_model(self, model: dict) -> bool:
        return str(model.get("id", "")).endswith(":free")
