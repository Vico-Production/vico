"""Strict argument models for every tool and the planner output contract.

Unknown fields are rejected everywhere. Bounds keep model output from smuggling huge
payloads into tools.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from app.config import READ_TEXT_MAX_BYTES, SUMMARY_MAX_CHARS
from app.contracts import StrictModel

PathStr = Annotated[str, Field(min_length=1, max_length=400)]
_URL = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
_KEYS = re.compile(r"^[A-Za-z0-9+_\- ]{1,60}$")


_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):(?!\d)")


def _check_url(value: str) -> str:
    value = value.strip()
    scheme = _SCHEME.match(value)
    if scheme and scheme.group(1).lower() not in ("http", "https"):
        raise ValueError("Only http and https web addresses are allowed.")
    if not value.lower().startswith(("http://", "https://")):
        value = "https://" + value
    if not _URL.match(value) or len(value) > 2000:
        raise ValueError("Only http and https web addresses are allowed.")
    return value


class NoArgs(StrictModel):
    pass


# --- files -----------------------------------------------------------------------------
class ListFolderArgs(StrictModel):
    path: PathStr = "."
    page: int = Field(default=1, ge=1, le=1000)


class FindFilesArgs(StrictModel):
    query: str = Field(min_length=1, max_length=100)
    path: PathStr = "."
    max_results: int = Field(default=25, ge=1, le=100)


class ReadTextArgs(StrictModel):
    path: PathStr
    max_chars: int = Field(default=8000, ge=100, le=READ_TEXT_MAX_BYTES)


class CreateFolderArgs(StrictModel):
    path: PathStr


class SaveNoteArgs(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(default="", max_length=100_000)
    folder: PathStr = "."
    format: Literal["txt", "md"] = "txt"


class MovePathArgs(StrictModel):
    source: PathStr
    destination: PathStr


class DeletePathArgs(StrictModel):
    path: PathStr


class OpenFileArgs(StrictModel):
    path: PathStr


class SummarizeDocumentArgs(StrictModel):
    path: PathStr
    max_chars: int = Field(default=SUMMARY_MAX_CHARS, ge=200, le=SUMMARY_MAX_CHARS)


# --- apps ------------------------------------------------------------------------------
class OpenAppArgs(StrictModel):
    name: str = Field(min_length=1, max_length=80)


class ListAppsArgs(StrictModel):
    query: str = Field(default="", max_length=80)


# --- web -------------------------------------------------------------------------------
class UrlArgs(StrictModel):
    url: str = Field(min_length=1, max_length=2000)

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        return _check_url(value)


class BrowserClickArgs(StrictModel):
    target: str = Field(min_length=1, max_length=200)


class BrowserTypeArgs(StrictModel):
    target: str = Field(min_length=1, max_length=200)
    text: str = Field(max_length=5000)
    submit: bool = False


class KeyArgs(StrictModel):
    key: str = Field(min_length=1, max_length=60)

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not _KEYS.match(value):
            raise ValueError("Keys must be names like Enter, Tab or ctrl+s.")
        return value


class BrowserReadArgs(StrictModel):
    max_chars: int = Field(default=6000, ge=200, le=20_000)


class BrowserScrollArgs(StrictModel):
    direction: Literal["up", "down"] = "down"


# --- desktop ---------------------------------------------------------------------------
class FocusWindowArgs(StrictModel):
    title: str = Field(min_length=1, max_length=200)


class TypeTextArgs(StrictModel):
    text: str = Field(min_length=1, max_length=2000)


class PressKeysArgs(StrictModel):
    keys: str = Field(min_length=1, max_length=60)

    @field_validator("keys")
    @classmethod
    def _keys(cls, value: str) -> str:
        if not _KEYS.match(value):
            raise ValueError("Keys must be names like enter, tab or ctrl+s.")
        return value


class ClickElementArgs(StrictModel):
    window: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)


# --- system ----------------------------------------------------------------------------
class RunCommandArgs(StrictModel):
    command: str = Field(min_length=1, max_length=2000)
    shell: Literal["auto", "powershell", "cmd", "bash", "sh"] = "auto"
    cwd: PathStr = "."


# --- planner contract ------------------------------------------------------------------
class ToolCallPlan(StrictModel):
    kind: Literal["tool_call"]
    tool: str = Field(min_length=1, max_length=60)
    arguments: dict[str, Any] = Field(default_factory=dict)
    explanation: str = Field(default="", max_length=500)


class ClarifyPlan(StrictModel):
    kind: Literal["clarify"]
    question: str = Field(min_length=1, max_length=500)


class UnsupportedPlan(StrictModel):
    kind: Literal["unsupported"]
    reason: str = Field(min_length=1, max_length=500)


class DonePlan(StrictModel):
    kind: Literal["done"]
    message: str = Field(min_length=1, max_length=1000)


class ControlPlan(StrictModel):
    """The request is about Vico itself (stay, go, move, greeting), not a task."""

    kind: Literal["control"]
    action: Literal["stay", "go", "move", "greet"]
    where: str | None = Field(default=None, max_length=20)


Plan = ToolCallPlan | ClarifyPlan | UnsupportedPlan | DonePlan | ControlPlan
_PLAN_TYPES: dict[str, type[StrictModel]] = {
    "tool_call": ToolCallPlan,
    "clarify": ClarifyPlan,
    "unsupported": UnsupportedPlan,
    "done": DonePlan,
    "control": ControlPlan,
}


def parse_plan(raw: Any) -> Plan:
    """Strictly parse planner output. Raises ValueError on anything malformed."""
    if not isinstance(raw, dict):
        raise ValueError("Planner output must be a JSON object.")
    kind = raw.get("kind")
    model = _PLAN_TYPES.get(kind) if isinstance(kind, str) else None
    if model is None:
        raise ValueError(f"Unknown plan kind: {kind!r}")
    return model.model_validate(raw)  # type: ignore[return-value]
