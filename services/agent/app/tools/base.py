"""Tool registry primitives shared by every tool module."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from app.contracts import ErrorCode, StrictModel, VicoError
from app.security.paths import PathPolicy

if TYPE_CHECKING:
    from app.platform.base import PlatformAdapter
    from app.store.settings import Settings
    from app.tools.browser import BrowserController


class Risk(StrEnum):
    # Metadata reads: run without asking even when the approval switch is on.
    AUTO = "auto"
    # Ordinary actions: ask when the approval switch is on.
    STANDARD = "standard"
    # Always ask, even with the switch off: deletion, shell commands, content uploads.
    CONFIRM = "confirm"


class ToolResult(StrictModel):
    ok: bool
    message: str
    verified: bool = False
    verification: str = ""
    data: dict[str, Any] = {}
    # Text returned to the planner. Treated as untrusted data, never as instructions.
    observation: str = ""


Summarizer = Callable[[str, str], Awaitable[str]]


@dataclass
class ToolContext:
    settings: Settings
    paths: PathPolicy
    platform: PlatformAdapter
    browser: BrowserController | None = None
    summarizer: Summarizer | None = None
    language: str = "en"
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    tainted: bool = False  # this task has read untrusted text (a page, file or command output)


@dataclass
class Inspection:
    """Facts gathered before approval so the approval card and policy see the real target."""

    effect: str
    targets: list[str] = field(default_factory=list)
    label: str = ""
    deny_reason: str | None = None
    send_like: bool = False
    content_upload: bool = False


Handler = Callable[[ToolContext, Any], Awaitable[ToolResult]]
Inspector = Callable[[ToolContext, Any], Awaitable[Inspection]]


@dataclass
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    risk: Risk
    handler: Handler
    inspect: Inspector
    category: str
    offline: bool = True
    platforms: tuple[str, ...] = ("win32", "linux", "darwin")

    def manifest(self) -> dict[str, Any]:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        return {"name": self.name, "description": self.description, "arguments": schema}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        spec = self._tools.get(name)
        if spec is None:
            raise VicoError(ErrorCode.POLICY_DENIED, f"'{name}' is not a Vico tool.", status=403)
        return spec

    def names(self) -> list[str]:
        return sorted(self._tools)

    def available(self, platform: str, online: bool) -> list[ToolSpec]:
        return [
            t for t in self._tools.values()
            if platform in t.platforms and (online or t.offline)
        ]

    def parse_args(self, name: str, arguments: dict[str, Any]) -> BaseModel:
        spec = self.get(name)
        try:
            return spec.args_model.model_validate(arguments)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}" for e in exc.errors()
            )
            raise VicoError(ErrorCode.VALIDATION_ERROR, f"Invalid arguments for {name}: {problems}") from exc


def fail(message: str, observation: str | None = None) -> ToolResult:
    return ToolResult(ok=False, message=message, observation=observation or message)
