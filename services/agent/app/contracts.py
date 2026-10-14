"""Shared, versioned API contracts. Mirrored in apps/desktop/src/lib/contracts.ts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

API_VERSION = "1"
API_PREFIX = "/api/v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Language(StrEnum):
    EN = "en"
    YO = "yo"
    HA = "ha"
    IG = "ig"
    PCM = "pcm"


LANGUAGE_NAMES: dict[Language, str] = {
    Language.EN: "English",
    Language.YO: "Yoruba",
    Language.HA: "Hausa",
    Language.IG: "Igbo",
    Language.PCM: "Nigerian Pidgin",
}


class RunState(StrEnum):
    IDLE = "idle"
    NORMALIZING = "normalizing"
    PLANNING = "planning"
    VALIDATING = "validating"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}


class ProviderStatus(StrEnum):
    READY = "ready"
    NOT_CONFIGURED = "not_configured"
    OFFLINE = "offline"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"
    DISABLED = "disabled"


class ErrorCode(StrEnum):
    UNAUTHORIZED = "unauthorized"
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    POLICY_DENIED = "policy_denied"
    CONSENT_REQUIRED = "consent_required"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_AUTH = "provider_auth"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    OFFLINE = "offline"
    INVALID_PLAN = "invalid_plan"
    CANCELLED = "cancelled"
    MIC_UNAVAILABLE = "mic_unavailable"
    UNSUPPORTED = "unsupported"
    CONFLICT = "conflict"
    INTERNAL = "internal"


class ApiError(StrictModel):
    code: ErrorCode
    message: str
    retryable: bool = False
    retry_after_s: float | None = None


T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")
    api_version: str = API_VERSION
    ok: bool
    data: T | None = None
    error: ApiError | None = None


def ok(data: Any) -> dict[str, Any]:
    return {"api_version": API_VERSION, "ok": True, "data": data, "error": None}


def fail(code: ErrorCode, message: str, retryable: bool = False, retry_after_s: float | None = None) -> dict:
    return {
        "api_version": API_VERSION,
        "ok": False,
        "data": None,
        "error": ApiError(
            code=code, message=message, retryable=retryable, retry_after_s=retry_after_s
        ).model_dump(),
    }


class VicoError(Exception):
    """An error with a public code that the API turns into an error envelope."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        retry_after_s: float | None = None,
        status: int = 400,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_after_s = retry_after_s
        self.status = status
