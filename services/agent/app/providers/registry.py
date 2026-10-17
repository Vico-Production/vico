"""ProviderHub: picks the configured provider per role, enforces consent, budgets and fallback rules.

Data goes to a provider only after the user accepted the cloud disclosure. A second
provider is tried only when it has a key AND the user consented to fallback.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import socket
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx

from app.agent import control
from app.agent.language import safe_restoration
from app.agent.prompts import SUMMARY_SYSTEM, UNDERSTAND_SYSTEM, translate_system
from app.contracts import LANGUAGE_NAMES, ErrorCode, ProviderStatus, VicoError
from app.providers import tts
from app.providers.base import QuotaTracker, normalize_language, parse_json_text, provider_status
from app.providers.gemini import GeminiProvider
from app.providers.groq import GroqProvider, MistralProvider, OpenRouterProvider
from app.providers.speech_server import OmnilingualProvider, SpeechServer, VoiceProvider
from app.security.secret_store import SecretStore
from app.store.settings import Settings

# Understanding order: Gemini, then each free fallback. A setting can move one to the front.
PROVIDERS = ("gemini", "groq", "mistral", "openrouter")
PROVIDER_CLASSES: dict[str, Any] = {"gemini": GeminiProvider, "groq": GroqProvider, "mistral": MistralProvider,
                                    "openrouter": OpenRouterProvider}
# Keys the user can store: the cloud providers and the token of their own speech server.
SECRET_NAMES = (*PROVIDERS, "speech_server", "tinyfish")  # tinyfish: free web search and page reading
# Speech-to-text order: Gemini, the user's speech server, Groq Whisper, Mistral Voxtral (English).
STT_ORDER = ("gemini", "omnilingual", "groq", "mistral")
HOSTS = {"groq": "api.groq.com", "gemini": "generativelanguage.googleapis.com", "mistral": "api.mistral.ai",
         "openrouter": "openrouter.ai"}
HEDGE_AFTER_S = 5.0  # a slow speech provider gets company: the next one starts too, first answer wins
FALLBACK_CODES = {ErrorCode.OFFLINE, ErrorCode.TIMEOUT, ErrorCode.RATE_LIMITED, ErrorCode.PROVIDER_UNAVAILABLE}
T = TypeVar("T")


ONLINE_CACHE_S = 30  # a failed request still shows a real outage at once


class ProviderHub:
    def __init__(self, secrets: SecretStore, settings: Callable[[], Settings],
                 client: httpx.AsyncClient | None = None, overrides: dict[str, Any] | None = None):
        self.secrets = secrets
        self.settings = settings
        self.client = client or httpx.AsyncClient(follow_redirects=False)
        self.overrides = overrides or {}
        self.quotas = {name: QuotaTracker() for name in (*PROVIDERS, "speech_server")}
        self._cache: dict[str, tuple[str, Any]] = {}
        self._online: tuple[float, bool] = (0.0, False)

    # --- construction ------------------------------------------------------------------
    def speech_server(self) -> SpeechServer | None:
        s = self.settings()
        token = self.secrets.get("speech_server")
        if not s.speech_server_url or not token:
            return None
        fingerprint = hashlib.sha256(f"{s.speech_server_url}|{token}".encode()).hexdigest()
        cached = self._cache.get("speech_server")
        if cached and cached[0] == fingerprint:
            return cached[1]
        try:
            server = SpeechServer(s.speech_server_url, token, self.client, self.quotas["speech_server"])
        except VicoError:
            return None  # an unusable address is reported when it is saved
        self._cache["speech_server"] = (fingerprint, server)
        return server

    def provider(self, name: str) -> Any | None:
        if name in self.overrides:
            return self.overrides[name]
        if name == "omnilingual":
            server = self.speech_server()
            return OmnilingualProvider(server) if server else None
        key = self.secrets.get(name)
        if not key:
            return None
        s = self.settings()
        self.quotas[name].daily_budget = s.daily_request_budget
        stt_model = s.stt_model if s.stt_provider == name else None
        llm_model = s.llm_model if s.llm_provider == name else None
        fingerprint = hashlib.sha256(f"{key}|{stt_model}|{llm_model}".encode()).hexdigest()
        cached = self._cache.get(name)
        if cached and cached[0] == fingerprint:
            return cached[1]
        cls = PROVIDER_CLASSES.get(name)
        if cls is None:
            return None
        instance = cls(key, self.client, self.quotas[name], stt_model=stt_model, llm_model=llm_model)
        self._cache[name] = (fingerprint, instance)
        return instance

    def configured(self, name: str) -> bool:
        if name in self.overrides:
            return True
        if name == "omnilingual":
            return self.speech_server() is not None
        return self.secrets.has(name)

    def _chain(self, role: str) -> list[Any]:
        s = self.settings()
        primary = s.stt_provider if role == "stt" else s.llm_provider
        names: list[str] = [] if primary == "none" else [primary]
        if s.fallback_consent:
            order = STT_ORDER if role == "stt" else PROVIDERS
            names += [n for n in order if n not in names]
        chain = [p for p in (self.provider(n) for n in names) if p is not None]
        if role == "stt":
            chain = [p for p in chain if getattr(p, "stt_languages", True) is not None]
        return chain

    def require_consent(self) -> None:
        if not self.settings().cloud_consent:
            raise VicoError(ErrorCode.CONSENT_REQUIRED,
                            "Cloud processing is off. Accept the cloud disclosure in Settings, or use typed "
                            "offline commands.", status=403)

    async def _run(self, role: str, fn: Callable[[Any], Awaitable[T]]) -> T:
        self.require_consent()
        chain = self._chain(role)
        if not chain:
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE,
                            "No cloud provider is set up. Add a free API key in Settings, or use typed offline "
                            "commands.", status=503)
        errors: list[VicoError] = []
        for provider in chain:
            try:
                return await fn(provider)
            except VicoError as exc:
                if exc.code not in FALLBACK_CODES:
                    raise
                errors.append(exc)  # resting or unreachable: go straight to the next provider
        limited = [e for e in errors if e.code is ErrorCode.RATE_LIMITED and e.retry_after_s]
        if limited:
            # Everything is resting: report the soonest moment any key is usable again.
            soonest = min(limited, key=lambda e: e.retry_after_s or 0)
            raise VicoError(ErrorCode.RATE_LIMITED, soonest.message, retryable=True,
                            retry_after_s=soonest.retry_after_s, status=429)
        raise errors[-1]

    # --- capabilities ------------------------------------------------------------------
    def has_role(self, role: str) -> bool:
        return bool(self.settings().cloud_consent and self._chain(role))

    async def transcribe(self, audio: bytes, mime: str, language: str | None, hints: list[str] | None = None):
        """Speech to text. If the first provider is slow, the next one starts alongside it and the
        first good answer is used, so one slow or failing key never leaves the user waiting."""
        self.require_consent()
        chain = self._chain("stt")
        if not chain:
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE,
                            "No cloud provider is set up. Add a free API key in Settings, or use typed offline "
                            "commands.", status=503)
        pending: set[asyncio.Task] = set()
        errors: list[VicoError] = []
        queue = list(chain)

        def launch() -> None:
            provider = queue.pop(0)
            pending.add(asyncio.ensure_future(provider.transcribe(audio, mime, language, hints=hints)))

        launch()
        try:
            while pending:
                done, _ = await asyncio.wait(pending, timeout=HEDGE_AFTER_S if queue else None,
                                             return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    launch()  # still waiting: start the next provider too
                    continue
                for task in done:
                    pending.discard(task)
                    exc = task.exception()
                    if exc is None:
                        return task.result()
                    if not isinstance(exc, VicoError) or exc.code not in FALLBACK_CODES:
                        raise exc
                    errors.append(exc)
                if not pending and queue:
                    launch()
        finally:
            for task in pending:
                task.cancel()
        limited = [e for e in errors if e.code is ErrorCode.RATE_LIMITED and e.retry_after_s]
        if limited:
            soonest = min(limited, key=lambda e: e.retry_after_s or 0)
            raise VicoError(ErrorCode.RATE_LIMITED, soonest.message, retryable=True,
                            retry_after_s=soonest.retry_after_s, status=429)
        raise errors[-1]

    async def complete(self, system: str, user: str, json_mode: bool = True):
        return await self._run("llm", lambda p: p.complete(system, user, json_mode=json_mode))

    async def understand(self, text: str) -> dict[str, Any]:
        """Detect the request's language and its English meaning in one call."""
        completion = await self.complete(UNDERSTAND_SYSTEM, text, json_mode=True)
        data = parse_json_text(completion.text)
        if not isinstance(data, dict):
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, "Could not understand the request.", retryable=True)
        english = data.get("english")
        return {"language": normalize_language(data.get("language")) or "en",
                "english": english.strip() if isinstance(english, str) and english.strip() else text,
                # Tone marks restored for display and planning, only if nothing but diacritics changed.
                "restored": safe_restoration(text, data.get("restored")) or text,
                # A request about Vico itself (stay, go, move, greeting) rather than a task.
                "control": control.clean(data.get("control"))}

    def voice_ready(self) -> bool:
        """Spoken replies are on (switched by voice: "Vico, talk to me")."""
        return bool(self.settings().voice_replies)

    async def speak(self, text: str, language: str) -> dict[str, Any]:
        """Speak a reply in the user's language from the first voice that works, so a used-up or
        resting Gemini key never silences Vico:

        English, Pidgin: Gemini TTS, Groq Orpheus, the user's speech server (YarnGPT), the
        computer's own voice. Hausa, Igbo: Gemini TTS, the speech server. Yorùbá: the speech
        server (no free cloud voice lists Yorùbá). Pidgin is spoken by English voices."""
        if not self.settings().voice_replies:
            raise VicoError(ErrorCode.UNSUPPORTED, "Voice replies are switched off.")
        part = tts.spoken_part(text)
        started = time.monotonic()
        cloud = self.settings().cloud_consent
        notes: list[str] = []

        def done(audio: bytes, provider: str, model: str) -> dict[str, Any]:
            return {"audio_b64": base64.b64encode(audio).decode("ascii"), "mime": "audio/wav",
                    "provider": provider, "model": model, "spoken": part,
                    "latency_ms": int((time.monotonic() - started) * 1000)}

        gemini = self.provider("gemini") if cloud else None
        model = tts.GEMINI_TTS_MODEL.get(language)
        if gemini is not None and model:
            try:
                return done(await gemini.speak(part, model), "gemini", model)
            except VicoError:
                pass  # resting, used up or offline: the next voice
        groq = self.provider("groq") if cloud else None
        if groq is not None and language in tts.GROQ_VOICE_LANGUAGES and hasattr(groq, "speak"):
            try:
                return done(await groq.speak(part), "groq", tts.GROQ_TTS_MODEL)
            except VicoError as exc:
                if "terms" in exc.message.lower():
                    notes.append(exc.message)
        voice = self.overrides.get("yarngpt")
        server = self.speech_server() if voice is None and cloud else None
        if (voice or server) and language in ("en", "yo", "ha", "ig", "pcm"):
            try:
                return await (voice or VoiceProvider(server)).speak(part, "en" if language == "pcm" else language)  # type: ignore[arg-type]
            except VicoError:
                pass
        if language in ("en", "pcm"):
            audio_bytes = await asyncio.to_thread(tts.system_voice, part)
            if audio_bytes:
                return done(audio_bytes, "system", "system voice")
        if language == "yo" and not (voice or server):
            raise VicoError(ErrorCode.UNSUPPORTED, "Yorùbá voice replies need your speech server.")
        raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, " ".join(notes) or "No voice is available for this reply "
                        "right now, so it stays as text.")

    async def speech_server_health(self) -> dict[str, Any]:
        self.require_consent()
        server = self.speech_server()
        if server is None:
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, "Add the speech server address and token first.")
        return await server.health()

    async def warm(self) -> None:
        """Check the connection and fetch each configured provider's model list ahead of time
        (opening its connection), so the first request is fast."""
        await self.online()
        for name in PROVIDERS:
            provider = self.provider(name)
            if provider is not None and self.settings().cloud_consent:
                try:
                    await provider.list_models()
                except VicoError:
                    pass

    async def translate(self, text: str, src: str, dst: str) -> dict[str, Any]:
        if src == dst:
            return {"text": text, "provider": "none", "model": "", "latency_ms": 0}
        completion = await self.complete(translate_system(src, dst), text, json_mode=True)
        data = parse_json_text(completion.text)
        translation = data.get("translation") if isinstance(data, dict) else None
        if not isinstance(translation, str) or not translation.strip():
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, "The translation came back empty.", retryable=True)
        return {"text": translation.strip(), "provider": completion.provider, "model": completion.model,
                "latency_ms": completion.latency_ms}

    def can_see(self) -> bool:
        return bool(self.settings().cloud_consent and any(hasattr(p, "see") for p in self._chain("llm")))

    async def see(self, image_jpeg: bytes, question: str) -> str:
        """Look at a screenshot (providers that can see images: Gemini)."""
        self.require_consent()
        errors: list[VicoError] = []
        for provider in [p for p in self._chain("llm") if hasattr(p, "see")]:
            try:
                return str(await provider.see(image_jpeg, question))
            except VicoError as exc:
                if exc.code not in FALLBACK_CODES:
                    raise
                errors.append(exc)
        if errors:
            raise errors[-1]
        raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, "Looking at the screen needs a Gemini access code.")

    async def summarize(self, text: str, language: str) -> str:
        lang = LANGUAGE_NAMES.get(language, "English")  # type: ignore[call-overload]
        completion = await self.complete(SUMMARY_SYSTEM.format(language=lang),
                                         f"<untrusted_content source=\"document\">\n{text}\n</untrusted_content>",
                                         json_mode=False)
        return completion.text.strip()

    async def list_models(self, name: str) -> list[str]:
        provider = self.provider(name)
        if provider is None:
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, f"No API key saved for {name}.", status=400)
        return await provider.list_models()

    # --- status ------------------------------------------------------------------------
    async def online(self) -> bool:
        stamp, value = self._online
        if time.monotonic() - stamp < ONLINE_CACHE_S:
            return value

        def probe(host: str) -> bool:
            try:
                with socket.create_connection((host, 443), timeout=3):
                    return True
            except OSError:
                return False

        # Online as soon as any provider answers; offline only when none does.
        pending = {asyncio.ensure_future(asyncio.to_thread(probe, h)) for h in HOSTS.values()}
        value = False
        while pending and not value:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            value = any(task.result() for task in done)
        for task in pending:
            task.cancel()
        self._online = (time.monotonic(), value)
        return value

    def status(self) -> dict[str, Any]:
        s = self.settings()
        out: dict[str, Any] = {}
        server = self.speech_server()
        out["speech_server"] = {"status": (ProviderStatus.READY if server and s.cloud_consent else
                                           ProviderStatus.DISABLED if server else ProviderStatus.NOT_CONFIGURED).value,
                                "configured": server is not None, **self.quotas["speech_server"].status(),
                                "cooldown_s": self.quotas["speech_server"].cooldown_s()}
        for name in PROVIDERS:
            configured = self.configured(name)
            state = provider_status(configured, self.quotas[name])
            provider = self._cache.get(name, (None, None))[1] or self.overrides.get(name)
            cooldown = float(provider.cooldown_s()) if provider is not None and hasattr(provider, "cooldown_s") else 0.0
            if cooldown > 0:
                state = ProviderStatus.RATE_LIMITED
            if not s.cloud_consent and configured:
                state = ProviderStatus.DISABLED
            out[name] = {"status": state.value, "configured": configured, **self.quotas[name].status(),
                         "cooldown_s": cooldown}
        return out

    async def aclose(self) -> None:
        await self.client.aclose()
