"""ProviderHub: picks the configured provider per role, enforces consent, budgets and fallback rules.

Data goes to a provider only after the user accepted the cloud disclosure. A second
provider is tried only when it has a key AND the user consented to fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import socket
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx

from app.agent.prompts import SUMMARY_SYSTEM, UNDERSTAND_SYSTEM, translate_system
from app.contracts import LANGUAGE_NAMES, ErrorCode, ProviderStatus, VicoError
from app.providers.base import QuotaTracker, normalize_language, parse_json_text, provider_status
from app.providers.gemini import GeminiProvider
from app.providers.groq import GroqProvider
from app.security.secret_store import SecretStore
from app.store.settings import Settings

PROVIDERS = ("groq", "gemini")
HOSTS = {"groq": "api.groq.com", "gemini": "generativelanguage.googleapis.com"}
FALLBACK_CODES = {ErrorCode.OFFLINE, ErrorCode.TIMEOUT, ErrorCode.RATE_LIMITED, ErrorCode.PROVIDER_UNAVAILABLE}
T = TypeVar("T")


class ProviderHub:
    def __init__(self, secrets: SecretStore, settings: Callable[[], Settings],
                 client: httpx.AsyncClient | None = None, overrides: dict[str, Any] | None = None):
        self.secrets = secrets
        self.settings = settings
        self.client = client or httpx.AsyncClient(follow_redirects=False)
        self.overrides = overrides or {}
        self.quotas = {name: QuotaTracker() for name in PROVIDERS}
        self._cache: dict[str, tuple[str, Any]] = {}
        self._online: tuple[float, bool] = (0.0, False)

    # --- construction ------------------------------------------------------------------
    def provider(self, name: str) -> Any | None:
        if name in self.overrides:
            return self.overrides[name]
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
        cls = GroqProvider if name == "groq" else GeminiProvider
        instance = cls(key, self.client, self.quotas[name], stt_model=stt_model, llm_model=llm_model)
        self._cache[name] = (fingerprint, instance)
        return instance

    def configured(self, name: str) -> bool:
        return name in self.overrides or self.secrets.has(name)

    def _chain(self, role: str) -> list[Any]:
        s = self.settings()
        primary = s.stt_provider if role == "stt" else s.llm_provider
        names: list[str] = [] if primary == "none" else [primary]
        if s.fallback_consent:
            names += [n for n in PROVIDERS if n not in names]
        chain = [p for p in (self.provider(n) for n in names) if p is not None]
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

    async def transcribe(self, audio: bytes, mime: str, language: str | None):
        return await self._run("stt", lambda p: p.transcribe(audio, mime, language))

    async def complete(self, system: str, user: str, json_mode: bool = True):
        return await self._run("llm", lambda p: p.complete(system, user, json_mode=json_mode))

    async def understand(self, text: str) -> dict[str, str]:
        """Detect the request's language and its English meaning in one call."""
        completion = await self.complete(UNDERSTAND_SYSTEM, text, json_mode=True)
        data = parse_json_text(completion.text)
        if not isinstance(data, dict):
            raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, "Could not understand the request.", retryable=True)
        english = data.get("english")
        return {"language": normalize_language(data.get("language")) or "en",
                "english": english.strip() if isinstance(english, str) and english.strip() else text}

    async def warm(self) -> None:
        """Fetch each configured provider's model list ahead of time so the first request is fast."""
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
        if time.monotonic() - stamp < 5:
            return value

        def probe(host: str) -> bool:
            try:
                with socket.create_connection((host, 443), timeout=3):
                    return True
            except OSError:
                return False

        results = await asyncio.gather(*(asyncio.to_thread(probe, h) for h in HOSTS.values()))
        value = any(results)
        self._online = (time.monotonic(), value)
        return value

    def status(self) -> dict[str, Any]:
        s = self.settings()
        out: dict[str, Any] = {}
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
