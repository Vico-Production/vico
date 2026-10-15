"""Provider protocols, normalized results, HTTP error mapping and quota tracking."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, TypeVar
from zoneinfo import ZoneInfo

import httpx

from app.contracts import ErrorCode, ProviderStatus, VicoError
from app.security.redaction import redact_text


@dataclass
class Transcript:
    text: str
    language: str
    provider: str
    model: str
    latency_ms: int
    confidence: float | None = None  # never invented: None when the provider gives none


@dataclass
class Completion:
    text: str
    provider: str
    model: str
    latency_ms: int


class SpeechProvider(Protocol):
    name: str

    async def transcribe(self, audio: bytes, mime: str, language: str) -> Transcript: ...


class TextProvider(Protocol):
    name: str

    async def complete(self, system: str, user: str, *, json_mode: bool) -> Completion: ...


class ModelLister(Protocol):
    async def list_models(self) -> list[str]: ...


@dataclass
class QuotaTracker:
    daily_budget: int = 500
    day: date = field(default_factory=date.today)
    requests_today: int = 0
    audio_seconds_today: float = 0.0
    rate_limited_until: float = 0.0
    last_error: str | None = None

    def check(self, provider: str) -> None:
        self._roll()
        now = time.monotonic()
        if now < self.rate_limited_until:
            wait = self.rate_limited_until - now
            raise VicoError(ErrorCode.RATE_LIMITED, f"{provider} asked Vico to wait {wait:.0f}s (rate limit).",
                            retryable=True, retry_after_s=round(wait, 1), status=429)
        if self.requests_today >= self.daily_budget:
            raise VicoError(ErrorCode.RATE_LIMITED,
                            f"Today's request budget for {provider} ({self.daily_budget}) is used up. "
                            "Raise it in Settings or use typed offline commands.", status=429)

    def record(self, audio_seconds: float = 0.0) -> None:
        self._roll()
        self.requests_today += 1
        self.audio_seconds_today += audio_seconds

    def limited(self, retry_after: float) -> None:
        self.rate_limited_until = time.monotonic() + retry_after

    def cooldown_s(self) -> float:
        return max(0.0, self.rate_limited_until - time.monotonic())

    def _roll(self) -> None:
        today = date.today()
        if today != self.day:
            self.day, self.requests_today, self.audio_seconds_today = today, 0, 0.0

    def status(self) -> dict[str, Any]:
        self._roll()
        return {"requests_today": self.requests_today, "daily_budget": self.daily_budget,
                "audio_seconds_today": round(self.audio_seconds_today, 1),
                "rate_limited": time.monotonic() < self.rate_limited_until}


_RETRY_DELAY = re.compile(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"')
PACIFIC = "America/Los_Angeles"


def seconds_until_quota_reset(now: datetime | None = None) -> float:
    """Gemini's daily quotas reset at midnight Pacific time."""
    tz = ZoneInfo(PACIFIC)
    now = (now or datetime.now(UTC)).astimezone(tz)
    reset = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tz)
    return max(60.0, (reset - now).total_seconds())


def local_reset_time() -> str:
    """The next quota reset in the computer's local time, e.g. '8:00 am'."""
    when = datetime.now().astimezone() + timedelta(seconds=seconds_until_quota_reset())
    return when.strftime("%I:%M %p").lstrip("0").lower()


def is_daily_limit(response: httpx.Response) -> bool:
    return "PerDay" in response.text


def _retry_after(response: httpx.Response) -> float:
    if is_daily_limit(response):
        return seconds_until_quota_reset()
    value = response.headers.get("retry-after")
    if not value:
        match = _RETRY_DELAY.search(response.text)
        value = match.group(1) if match else None
    try:
        return max(1.0, float(value)) if value else 20.0
    except ValueError:
        return 20.0


async def send(client: httpx.AsyncClient, provider: str, quota: QuotaTracker, request: httpx.Request,
               audio_seconds: float = 0.0) -> dict[str, Any]:
    """Send a request with stable error mapping. Never logs or returns secrets."""
    quota.check(provider)
    try:
        response = await client.send(request)
    except httpx.TimeoutException as exc:
        raise VicoError(ErrorCode.TIMEOUT, f"{provider} took too long to answer.", retryable=True, status=504) from exc
    except httpx.TransportError as exc:
        raise VicoError(ErrorCode.OFFLINE, f"Cannot reach {provider}. Check the internet connection.",
                        retryable=True, status=503) from exc
    quota.record(audio_seconds)
    if response.status_code in (401, 403):
        quota.last_error = "auth"
        raise VicoError(ErrorCode.PROVIDER_AUTH, f"{provider} rejected the API key. Check it in Settings.", status=401)
    if response.status_code == 429:
        wait = _retry_after(response)
        quota.limited(wait)
        if is_daily_limit(response):
            message = f"Today's free {provider} limit is used up. It resets at about {local_reset_time()}."
        else:
            message = f"{provider} free-tier limit reached; cooling down for {wait:.0f}s."
        raise VicoError(ErrorCode.RATE_LIMITED, message, retryable=True, retry_after_s=round(wait, 1), status=429)
    if response.status_code >= 400:
        detail = redact_text(response.text[:300])
        quota.last_error = f"http {response.status_code}"
        code = ErrorCode.PROVIDER_UNAVAILABLE if response.status_code >= 500 else ErrorCode.VALIDATION_ERROR
        raise VicoError(code, f"{provider} returned an error ({response.status_code}): {detail}",
                        retryable=response.status_code >= 500, status=502)
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise VicoError(ErrorCode.PROVIDER_UNAVAILABLE, f"{provider} sent an unreadable reply.", status=502) from exc


_LANGUAGE_ALIASES = {
    "en": "en", "english": "en", "yo": "yo", "yoruba": "yo", "ha": "ha", "hausa": "ha",
    "ig": "ig", "igbo": "ig", "pcm": "pcm", "pidgin": "pcm", "nigerian pidgin": "pcm",
}


def normalize_language(value: Any) -> str | None:
    """Map a provider's language label ('yoruba', 'yo', ...) to a Vico language code."""
    if not isinstance(value, str):
        return None
    return _LANGUAGE_ALIASES.get(value.strip().lower())


UNLIMITED = 10**9  # per-model trackers; Vico's own daily budget lives on the provider tracker
T = TypeVar("T")


class ModelChain:
    """Per-model cooldowns. On a rate limit the same request moves to the next model at
    once, and a resting model is skipped without any network call, so switching is
    instant. Only when every model is resting does the caller see RATE_LIMITED."""

    def __init__(self, provider: str, budget: QuotaTracker):
        self.provider = provider
        self.budget = budget
        self.last_chain: list[str] = []
        self._trackers: dict[str, QuotaTracker] = {}

    def tracker(self, model: str) -> QuotaTracker:
        if model not in self._trackers:
            self._trackers[model] = QuotaTracker(daily_budget=UNLIMITED)
        return self._trackers[model]

    def cooldowns(self) -> dict[str, float]:
        return {m: round(t.cooldown_s(), 1) for m, t in self._trackers.items() if t.cooldown_s() > 0}

    def cooldown_s(self, chain: list[str] | None = None) -> float:
        """Seconds until any model in the chain is usable; 0 when one is ready now."""
        chain = chain if chain is not None else self.last_chain
        if not chain:
            return 0.0
        waits = [self.tracker(m).cooldown_s() for m in chain]
        return round(min(waits), 1) if all(w > 0 for w in waits) else 0.0

    async def run(self, chain: list[str], attempt: Callable[[str, QuotaTracker], Awaitable[T]],
                  audio_seconds: float = 0.0) -> tuple[T, str]:
        self.last_chain = chain
        last: VicoError | None = None
        for model in chain:
            tracker = self.tracker(model)
            if tracker.cooldown_s() > 0:
                continue
            self.budget.check(self.provider)
            try:
                result = await attempt(model, tracker)
            except VicoError as exc:
                if exc.code is ErrorCode.RATE_LIMITED:
                    last = exc
                    continue
                raise
            self.budget.record(audio_seconds)
            return result, model
        wait = self.cooldown_s(chain) or (last.retry_after_s if last else None) or 20.0
        message = last.message if last else f"Your {self.provider} key is cooling down for {wait:.0f}s."
        raise VicoError(ErrorCode.RATE_LIMITED, message, retryable=True, retry_after_s=wait, status=429)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_text(text: str) -> Any:
    """Parse a model's JSON reply, tolerating a surrounding code fence only."""
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise VicoError(ErrorCode.INVALID_PLAN, "The AI reply was not valid JSON.", retryable=True, status=502) from exc


def pick_model(available: list[str], preferences: list[str], exclude: tuple[str, ...] = ()) -> str | None:
    """Choose a model from the live list. Only names the provider actually returned are used."""
    usable = [m for m in available if not any(x in m.lower() for x in exclude)]
    for pref in preferences:
        for model in usable:
            if pref in model.lower():
                return model
    return None


def provider_status(configured: bool, quota: QuotaTracker) -> ProviderStatus:
    if not configured:
        return ProviderStatus.NOT_CONFIGURED
    if quota.status()["rate_limited"]:
        return ProviderStatus.RATE_LIMITED
    if quota.last_error == "auth":
        return ProviderStatus.ERROR
    return ProviderStatus.READY
