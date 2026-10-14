"""Preflight policy: every proposed tool call passes through here before it can run.

Outcomes:
- allowed: run now (metadata reads, or any ordinary step with the approval switch off)
- approval_required: ordinary step with the approval switch on
- confirm_required: always asks, even with the switch off (delete, shell, content upload,
  and sends/posts/submissions unless the user allowed those)
- denied: hard limits (payments, passwords/card details), invalid arguments, unknown
  tools, paths outside allowed folders
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from app.contracts import ErrorCode, VicoError
from app.security.redaction import redact_args
from app.store.settings import Settings
from app.tools.base import Inspection, Risk, ToolContext, ToolRegistry, ToolSpec


class Outcome(StrEnum):
    ALLOWED = "allowed"
    APPROVAL_REQUIRED = "approval_required"
    CONFIRM_REQUIRED = "confirm_required"
    DENIED = "denied"


@dataclass
class Decision:
    outcome: Outcome
    reason: str
    effect: str = ""
    targets: list[str] = field(default_factory=list)
    content_upload: bool = False
    # True when the planner made a fixable mistake (bad argument, missing file) rather than hitting a limit.
    fixable: bool = False

    def public(self) -> dict[str, Any]:
        return {"outcome": self.outcome.value, "reason": self.reason, "effect": self.effect,
                "targets": self.targets, "content_upload": self.content_upload}


@dataclass
class Preflight:
    tool: str
    arguments: dict[str, Any]
    decision: Decision
    spec: ToolSpec | None = None
    args: BaseModel | None = None

    def public(self) -> dict[str, Any]:
        return {"tool": self.tool, "arguments": redact_args(self.arguments), **self.decision.public()}


def decide(spec: ToolSpec, inspection: Inspection, settings: Settings) -> Decision:
    def make(outcome: Outcome, reason: str) -> Decision:
        return Decision(outcome, reason, effect=inspection.effect, targets=inspection.targets,
                        content_upload=inspection.content_upload)

    if inspection.deny_reason:
        return make(Outcome.DENIED, inspection.deny_reason)
    if inspection.content_upload:
        return make(Outcome.CONFIRM_REQUIRED, "This sends file content to the cloud provider, so Vico always asks first.")
    if spec.risk is Risk.CONFIRM:
        return make(Outcome.CONFIRM_REQUIRED, "Deleting and running commands always need your confirmation.")
    if inspection.send_like and not settings.allow_send_without_approval:
        return make(Outcome.CONFIRM_REQUIRED, "This may send, post or submit something, so Vico always asks first.")
    if spec.risk is Risk.AUTO:
        return make(Outcome.ALLOWED, "Looking only; nothing changes.")
    if settings.require_approval:
        return make(Outcome.APPROVAL_REQUIRED, "Approval is switched on.")
    return make(Outcome.ALLOWED, "Approval is switched off in settings.")


async def preflight(registry: ToolRegistry, ctx: ToolContext, tool: str, arguments: dict[str, Any]) -> Preflight:
    """Validate the tool name, arguments and targets, then decide. Never executes anything."""
    try:
        spec = registry.get(tool)
        if ctx.platform and spec.platforms and _platform_key() not in spec.platforms:
            return Preflight(tool, arguments, Decision(Outcome.DENIED, f"{tool} is not available on this computer."))
        args = registry.parse_args(tool, arguments)
        inspection = await spec.inspect(ctx, args)
    except VicoError as exc:
        fixable = exc.code in (ErrorCode.VALIDATION_ERROR, ErrorCode.NOT_FOUND, ErrorCode.CONFLICT)
        return Preflight(tool, arguments, Decision(Outcome.DENIED, exc.message, fixable=fixable))
    except Exception as exc:  # an inspector failing must never let the step through
        return Preflight(tool, arguments, Decision(Outcome.DENIED, f"Could not check this step ({type(exc).__name__})."))
    return Preflight(tool, arguments, decide(spec, inspection, ctx.settings), spec, args)


def _platform_key() -> str:
    import sys

    return "linux" if sys.platform.startswith("linux") else sys.platform
