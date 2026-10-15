"""Agent Mode state machine.

text -> (translate to English) -> plan one step -> validate + policy -> approval ->
execute -> verify -> feed result back -> ... -> done. The model only proposes; every
step goes through preflight and, where required, the user's approval.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from app.agent import policy
from app.agent.language import guess_language
from app.agent.offline_parser import OFFLINE_HELP, parse_offline
from app.agent.prompts import PLANNER_SYSTEM, planner_user_prompt
from app.agent.schemas import ClarifyPlan, DonePlan, Plan, ToolCallPlan, UnsupportedPlan, parse_plan
from app.config import APPROVAL_TIMEOUT_S, MAX_CLARIFICATIONS, MAX_TEXT_INPUT_CHARS, TOOL_TIMEOUT_S, data_dir
from app.contracts import TERMINAL_STATES, ErrorCode, Language, RunState, VicoError
from app.platform.base import PlatformAdapter
from app.providers.base import parse_json_text
from app.providers.registry import ProviderHub
from app.security.paths import PathPolicy
from app.security.redaction import redact_args, redact_text
from app.store.history import HistoryRepository
from app.store.settings import Settings, SettingsRepository
from app.tools.base import ToolContext, ToolRegistry, ToolResult

log = logging.getLogger(__name__)
T = TypeVar("T")
MAX_FAILED_STEPS = 3
AUTO = "auto"  # language not given: detected from the request
# Short rate limits (per-minute) are waited out and the task continues; longer ones
# (the daily free quota) stop the task with a clear message.
MAX_COOLDOWN_WAIT_S = 120
MAX_RUNS_KEPT = 20
SLOW_TOOLS = {"browser_open", "browser_click", "browser_type", "browser_read", "run_command", "summarize_document",
              "find_files", "open_app", "open_file"}


class Cancelled(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass
class Step:
    id: str
    tool: str
    arguments: dict[str, Any]
    explanation: str
    effect: str = ""
    targets: list[str] = field(default_factory=list)
    outcome: str = ""
    reason: str = ""
    content_upload: bool = False
    approval: str = "pending"  # auto | approved | rejected | timed_out | denied | pending
    status: str = "proposed"  # proposed | awaiting_approval | running | succeeded | unverified | failed | denied | rejected
    message: str = ""
    verification: str = ""
    verified: bool = False
    observation: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id, "tool": self.tool, "arguments": redact_args(self.arguments),
            "explanation": self.explanation, "effect": self.effect, "targets": self.targets,
            "outcome": self.outcome, "reason": self.reason, "content_upload": self.content_upload,
            "approval": self.approval, "status": self.status, "message": self.message,
            "verification": self.verification, "verified": self.verified, "data": _safe_data(self.data),
        }


def _safe_data(data: dict[str, Any]) -> dict[str, Any]:
    """Data shown in the UI. Large text blobs are cut down."""
    out = {}
    for k, v in data.items():
        if isinstance(v, str) and len(v) > 4000:
            v = v[:4000] + "..."
        out[k] = v
    return out


@dataclass
class Run:
    id: str
    text: str
    language: str
    original: str
    mode: str = "cloud"
    state: RunState = RunState.IDLE
    canonical: str = ""
    steps: list[Step] = field(default_factory=list)
    question: str | None = None
    message: str | None = None
    message_localized: str | None = None
    error: dict[str, Any] | None = None
    cooldown_until: str | None = None
    timeline: list[dict[str, str]] = field(default_factory=list)
    clarifications: list[dict[str, str]] = field(default_factory=list)
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    decision_event: asyncio.Event = field(default_factory=asyncio.Event)
    decision: dict[str, Any] | None = None
    created: float = field(default_factory=time.monotonic)
    task: asyncio.Task | None = None

    def set_state(self, state: RunState, note: str = "") -> None:
        self.state = state
        self.timeline.append({"state": state.value, "at": _now(), "note": note})

    @property
    def pending_step(self) -> Step | None:
        if self.state is RunState.AWAITING_APPROVAL and self.steps:
            return self.steps[-1]
        return None

    def public(self) -> dict[str, Any]:
        pending = self.pending_step
        return {
            "id": self.id, "state": self.state.value, "mode": self.mode, "language": self.language,
            "text": self.text, "original": self.original, "canonical": self.canonical,
            "steps": [s.public() for s in self.steps],
            "pending_step_id": pending.id if pending else None,
            "question": self.question, "message": self.message, "message_localized": self.message_localized,
            "error": self.error, "cooldown_until": self.cooldown_until, "timeline": self.timeline,
        }


class Orchestrator:
    def __init__(self, *, registry: ToolRegistry, hub: ProviderHub, settings: SettingsRepository,
                 history: HistoryRepository, platform: PlatformAdapter, browser: Any = None,
                 approval_timeout_s: float = APPROVAL_TIMEOUT_S):
        self.registry = registry
        self.hub = hub
        self.settings_repo = settings
        self.history = history
        self.platform = platform
        self.browser = browser
        self.approval_timeout_s = approval_timeout_s
        self.runs: dict[str, Run] = {}

    # --- public API ----------------------------------------------------------------------
    def start(self, text: str, language: str | None = None, original: str | None = None) -> Run:
        text = text.strip()
        if not text:
            raise VicoError(ErrorCode.VALIDATION_ERROR, "Say or type what you want Vico to do.")
        if len(text) > MAX_TEXT_INPUT_CHARS:
            raise VicoError(ErrorCode.VALIDATION_ERROR, f"Requests are limited to {MAX_TEXT_INPUT_CHARS} characters.")
        if language is not None:
            Language(language)
        if any(r.state not in TERMINAL_STATES for r in self.runs.values()):
            raise VicoError(ErrorCode.CONFLICT, "Another task is still running. Finish or cancel it first.", status=409)
        run = Run(id=uuid.uuid4().hex[:12], text=text, language=language or AUTO, original=original or text)
        run.set_state(RunState.NORMALIZING, "Heard")
        self.runs[run.id] = run
        self._trim()
        run.task = asyncio.create_task(self._drive(run))
        return run

    def get(self, run_id: str) -> Run:
        run = self.runs.get(run_id)
        if run is None:
            raise VicoError(ErrorCode.NOT_FOUND, "That task no longer exists.", status=404)
        return run

    def decide(self, run_id: str, step_id: str, approved: bool, confirm: bool = False) -> Run:
        run = self.get(run_id)
        step = run.pending_step
        if step is None or step.id != step_id:
            raise VicoError(ErrorCode.CONFLICT, "That step is not waiting for approval.", status=409)
        if approved and step.outcome == policy.Outcome.CONFIRM_REQUIRED and not confirm:
            raise VicoError(ErrorCode.VALIDATION_ERROR, "This step needs the extra confirmation box ticked.")
        if run.decision is None:
            run.decision = {"step_id": step_id, "approved": approved}
            run.decision_event.set()
        return run

    def reply(self, run_id: str, answer: str) -> Run:
        run = self.get(run_id)
        if run.state is not RunState.AWAITING_CLARIFICATION:
            raise VicoError(ErrorCode.CONFLICT, "Vico is not waiting for an answer.", status=409)
        answer = answer.strip()[:MAX_TEXT_INPUT_CHARS]
        if not answer:
            raise VicoError(ErrorCode.VALIDATION_ERROR, "Type an answer.")
        run.decision = {"answer": answer}
        run.decision_event.set()
        return run

    def cancel(self, run_id: str) -> Run:
        run = self.get(run_id)
        if run.state not in TERMINAL_STATES:
            run.cancel.set()
        return run

    async def shutdown(self) -> None:
        for run in self.runs.values():
            run.cancel.set()
        tasks = [r.task for r in self.runs.values() if r.task and not r.task.done()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # --- driver --------------------------------------------------------------------------
    def _context(self, settings: Settings, run: Run) -> ToolContext:
        from pathlib import Path

        paths = PathPolicy(Path(settings.workspace), [Path(r) for r in settings.allowed_roots],
                           extra_protected=[data_dir()])
        paths.workspace.mkdir(parents=True, exist_ok=True)
        return ToolContext(settings=settings, paths=paths, platform=self.platform, browser=self.browser,
                           summarizer=self.hub.summarize, language=run.language, cancel=run.cancel)

    async def _drive(self, run: Run) -> None:
        try:
            settings = self.settings_repo.load()
            ctx = self._context(settings, run)
            cloud = self.hub.has_role("llm") and await self.hub.online()
            if cloud:
                await self._cloud(run, ctx, settings)
            else:
                run.mode = "offline"
                await self._offline(run, ctx)
        except Cancelled:
            run.set_state(RunState.CANCELLED, "Cancelled")
            run.message = "Cancelled. Nothing further was done."
        except VicoError as exc:
            self._fail(run, exc.code, exc.message)
        except asyncio.CancelledError:
            run.set_state(RunState.CANCELLED, "Stopped")
            raise
        except Exception:
            log.exception("run %s crashed", run.id)
            self._fail(run, ErrorCode.INTERNAL, "Something went wrong inside Vico. Nothing further was done.")

    def _fail(self, run: Run, code: ErrorCode, message: str) -> None:
        run.error = {"code": code.value, "message": message}
        run.message = message
        run.set_state(RunState.FAILED, message)

    async def _until(self, run: Run, awaitable: Awaitable[T]) -> T:
        """Await something, but stop at once if the user cancels."""
        task = asyncio.ensure_future(awaitable)
        cancel = asyncio.ensure_future(run.cancel.wait())
        done, _ = await asyncio.wait({task, cancel}, return_when=asyncio.FIRST_COMPLETED)
        if cancel in done:
            task.cancel()
            raise Cancelled
        cancel.cancel()
        return task.result()

    async def _cloud_call(self, run: Run, call: Callable[[], Awaitable[T]]) -> T:
        """Run a cloud call; if every free model is briefly rate-limited, show a cooldown and retry."""
        while True:
            try:
                return await self._until(run, call())
            except VicoError as exc:
                wait = exc.retry_after_s
                if exc.code is not ErrorCode.RATE_LIMITED or wait is None or wait > MAX_COOLDOWN_WAIT_S:
                    raise
                previous = run.state
                until = datetime.now(UTC) + timedelta(seconds=wait)
                run.cooldown_until = until.isoformat(timespec="seconds")
                run.set_state(RunState.COOLING_DOWN, f"{wait:.0f}s")
                try:
                    await self._until(run, asyncio.sleep(wait + 0.5))
                finally:
                    run.cooldown_until = None
                run.set_state(previous)

    async def _wait_decision(self, run: Run) -> dict[str, Any] | None:
        run.decision = None
        run.decision_event.clear()
        try:
            await self._until(run, asyncio.wait_for(run.decision_event.wait(), self.approval_timeout_s))
        except TimeoutError:
            return None
        return run.decision

    # --- offline -------------------------------------------------------------------------
    async def _offline(self, run: Run, ctx: ToolContext) -> None:
        run.canonical = run.text
        if run.language == AUTO:
            run.language = Language.EN.value
        plan = parse_offline(run.text)
        if plan is None:
            self._fail(run, ErrorCode.OFFLINE, OFFLINE_HELP)
            return
        step = await self._step(run, ctx, plan)
        if run.state in TERMINAL_STATES:
            return
        if step.status in ("succeeded", "unverified"):
            run.message = step.message
            run.set_state(RunState.COMPLETED, "Done")
        else:
            self._fail(run, ErrorCode.POLICY_DENIED if step.status == "denied" else ErrorCode.INTERNAL,
                       step.message or step.reason)

    # --- cloud ---------------------------------------------------------------------------
    async def _cloud(self, run: Run, ctx: ToolContext, settings: Settings) -> None:
        if run.language == AUTO:
            guess = guess_language(run.text)
            if guess == Language.EN:
                run.language, run.canonical = Language.EN.value, run.text
            else:
                understood = await self._cloud_call(run, lambda: self.hub.understand(run.text))
                run.language, run.canonical = understood["language"], understood["english"]
                run.original = understood.get("restored") or run.original
        elif run.language != Language.EN:
            translated = await self._cloud_call(run, lambda: self.hub.translate(run.text, run.language, "en"))
            run.canonical = translated["text"]
        else:
            run.canonical = run.text
        ctx.language = run.language
        run.timeline.append({"state": "understood", "at": _now(), "note": run.canonical})

        failures = 0
        tool_steps = 0
        while True:
            if tool_steps >= settings.max_steps:
                self._fail(run, ErrorCode.CANCELLED, f"Stopped after {settings.max_steps} steps to stay safe.")
                return
            run.set_state(RunState.PLANNING)
            plan = await self._plan(run, ctx)
            if isinstance(plan, DonePlan):
                run.message = plan.message
                await self._localize(run)
                run.set_state(RunState.COMPLETED, "Done")
                return
            if isinstance(plan, UnsupportedPlan):
                self._fail(run, ErrorCode.UNSUPPORTED, plan.reason)
                return
            if isinstance(plan, ClarifyPlan):
                if len(run.clarifications) >= MAX_CLARIFICATIONS:
                    self._fail(run, ErrorCode.UNSUPPORTED, "Vico still isn't sure what to do. Try rephrasing.")
                    return
                run.question = plan.question
                run.set_state(RunState.AWAITING_CLARIFICATION, plan.question)
                decision = await self._wait_decision(run)
                if decision is None:
                    self._fail(run, ErrorCode.TIMEOUT, "No answer was given, so Vico stopped.")
                    return
                run.clarifications.append({"question": plan.question, "answer": decision["answer"]})
                run.question = None
                continue

            assert isinstance(plan, ToolCallPlan)
            step = await self._step(run, ctx, plan)
            if run.state in TERMINAL_STATES:
                return
            tool_steps += 1
            if step.status in ("failed", "denied"):
                failures += 1
                if failures >= MAX_FAILED_STEPS:
                    self._fail(run, ErrorCode.INTERNAL, f"Stopped after {failures} failed steps: {step.message}")
                    return
            else:
                failures = 0

    async def _plan(self, run: Run, ctx: ToolContext) -> Plan:
        tools = [t.manifest() for t in self.registry.available(_platform_key(), online=True)]
        steps = [{"tool": s.tool, "arguments": s.arguments, "status": s.status, "observation": s.observation}
                 for s in run.steps]
        prompt = planner_user_prompt(
            original=run.original, canonical=run.canonical, language=run.language, tools=tools,
            workspace=str(ctx.paths.workspace), allowed_roots=[str(r) for r in ctx.paths.allowed_roots],
            steps=steps, clarifications=run.clarifications,
        )
        last_error = ""
        for attempt in range(2):
            text = prompt if attempt == 0 else (
                prompt + f"\n\nYour previous reply was rejected: {last_error}. Reply with valid JSON only.")
            completion = await self._cloud_call(run, functools.partial(self.hub.complete, PLANNER_SYSTEM, text, json_mode=True))
            try:
                return parse_plan(parse_json_text(completion.text))
            except (ValueError, VicoError) as exc:
                last_error = str(exc)[:300]
        raise VicoError(ErrorCode.INVALID_PLAN, "The AI did not return a valid plan, so nothing was run.")

    async def _localize(self, run: Run) -> None:
        if run.language == Language.EN or not run.message:
            return
        try:
            result = await self._until(run, self.hub.translate(run.message or "", "en", run.language))
            run.message_localized = result["text"]
        except VicoError:
            run.message_localized = None

    # --- one step ------------------------------------------------------------------------
    async def _step(self, run: Run, ctx: ToolContext, plan: ToolCallPlan) -> Step:
        step = Step(id=uuid.uuid4().hex[:8], tool=plan.tool, arguments=plan.arguments, explanation=plan.explanation)
        run.steps.append(step)
        run.set_state(RunState.VALIDATING, plan.tool)
        pf = await self._until(run, policy.preflight(self.registry, ctx, plan.tool, plan.arguments))
        d = pf.decision
        step.effect, step.targets, step.outcome, step.reason = d.effect, d.targets, d.outcome.value, d.reason
        step.content_upload = d.content_upload

        if d.outcome is policy.Outcome.DENIED:
            step.approval, step.status = "denied", "denied"
            step.message = d.reason
            step.observation = f"Refused by Vico's safety policy: {d.reason}"
            self._record(run, step)
            if not d.fixable:
                self._fail(run, ErrorCode.POLICY_DENIED, d.reason)
            return step

        if d.outcome in (policy.Outcome.APPROVAL_REQUIRED, policy.Outcome.CONFIRM_REQUIRED):
            step.status = "awaiting_approval"
            run.set_state(RunState.AWAITING_APPROVAL, step.effect)
            decision = await self._wait_decision(run)
            if decision is None:
                step.approval, step.status, step.message = "timed_out", "rejected", "No answer, so it was not done."
                self._record(run, step)
                self._fail(run, ErrorCode.TIMEOUT, "Approval timed out, so Vico stopped. Nothing was changed.")
                return step
            if not decision.get("approved"):
                step.approval, step.status, step.message = "rejected", "rejected", "You declined this step."
                self._record(run, step)
                run.message = "You declined the step, so Vico stopped. Nothing was changed."
                run.set_state(RunState.CANCELLED, "Rejected")
                return step
            step.approval = "approved"
            run.timeline.append({"state": "approved", "at": _now(), "note": step.tool})
        else:
            step.approval = "auto"

        run.set_state(RunState.EXECUTING, step.tool)
        step.status = "running"
        result = await self._execute(run, ctx, pf, step)
        run.set_state(RunState.VERIFYING, step.tool)
        step.message, step.verification, step.verified = result.message, result.verification, result.verified
        step.data, step.observation = result.data, result.observation or result.message
        if not result.ok:
            step.status = "failed"
        else:
            step.status = "succeeded" if result.verified else "unverified"
        self._record(run, step)
        return step

    async def _execute(self, run: Run, ctx: ToolContext, pf: policy.Preflight, step: Step) -> ToolResult:
        assert pf.spec is not None and pf.args is not None
        timeout = TOOL_TIMEOUT_S * (3 if step.tool in SLOW_TOOLS else 1)
        try:
            return await self._until(run, asyncio.wait_for(pf.spec.handler(ctx, pf.args), timeout))
        except Cancelled:
            raise
        except TimeoutError:
            return ToolResult(ok=False, message=f"{step.tool} took longer than {timeout}s and was stopped.",
                              observation="Timed out.")
        except VicoError as exc:
            return ToolResult(ok=False, message=exc.message, observation=exc.message)
        except Exception as exc:
            log.exception("tool %s failed", step.tool)
            return ToolResult(ok=False, message=f"{step.tool} failed ({type(exc).__name__}).",
                              observation=f"Error: {type(exc).__name__}")

    def _record(self, run: Run, step: Step) -> None:
        try:
            self.history.add(language=run.language, summary=step.effect or step.explanation or step.tool,
                             tool=step.tool, approval=step.approval, outcome=step.status, verified=step.verified,
                             detail=redact_text(step.message)[:300] if step.message else None)
        except Exception:
            log.exception("history write failed")

    def _trim(self) -> None:
        if len(self.runs) <= MAX_RUNS_KEPT:
            return
        finished = sorted((r for r in self.runs.values() if r.state in TERMINAL_STATES), key=lambda r: r.created)
        for r in finished[: len(self.runs) - MAX_RUNS_KEPT]:
            self.runs.pop(r.id, None)


def _platform_key() -> str:
    import sys

    return "linux" if sys.platform.startswith("linux") else sys.platform

