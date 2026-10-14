"""Provider protocols, normalized results, HTTP error mapping and quota tracking."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

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

    def _roll(self) -> None:
        today = date.today()
        if today != self.day:
            self.day, self.requests_today, self.audio_seconds_today = today, 0, 0.0

    def status(self) -> dict[str, Any]:
        self._roll()
        return {"requests_today": self.requests_today, "daily_budget": self.daily_budget,
                "audio_seconds_today": round(self.audio_seconds_today, 1),
                "rate_limited": time.monotonic() < self.rate_limited_until}


def _retry_after(response: httpx.Response) -> float:
    value = response.headers.get("retry-after")
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
        raise VicoError(ErrorCode.RATE_LIMITED, f"{provider} free-tier limit reached; try again in {wait:.0f}s.",
                        retryable=True, retry_after_s=wait, status=429)
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
