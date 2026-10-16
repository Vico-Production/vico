"""Agent Mode state machine.

text -> (translate to English) -> plan one step -> validate + policy -> approval ->
execute -> verify -> feed result back -> ... -> done. The model only proposes; every
step goes through preflight and, where required, the user's approval.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from app.agent import control, policy, stage
from app.agent.language import guess_language, safe_restoration
from app.agent.offline_parser import OFFLINE_HELP, parse_fast, parse_offline
from app.agent.prompts import PLANNER_SYSTEM, planner_user_prompt
from app.agent.schemas import (
    BatchPlan,
    ClarifyPlan,
    ControlPlan,
    DonePlan,
    Plan,
    ToolCallPlan,
    UnsupportedPlan,
    parse_plan,
    split_meta,
)
from app.config import APPROVAL_TIMEOUT_S, MAX_TEXT_INPUT_CHARS, TOOL_TIMEOUT_S, data_dir
from app.contracts import TERMINAL_STATES, ErrorCode, Language, RunState, VicoError
from app.platform.base import PlatformAdapter
from app.providers.base import parse_json_text
from app.providers.registry import ProviderHub
from app.security.paths import PathPolicy
from app.security.redaction import redact_args, redact_text
from app.store.history import HistoryRepository
from app.store.settings import Settings, SettingsPatch, SettingsRepository
from app.tools.base import Risk, ToolContext, ToolRegistry, ToolResult

log = logging.getLogger(__name__)
T = TypeVar("T")
MAX_FAILED_STEPS = 3
MAX_QUESTIONS = 6  # questions Vico may ask in one task before it stops
# Answers that mean "stop" (any of the four languages and Pidgin).
NEVER_MIND = re.compile(r"(?:never ?mind|forget it|cancel|stop|abort|leave it|no ?need|nothing|"
                        r"make you leave am|forget am|no worry|fi s[ií]l[eẹ]̀?|bar shi|hapu ya)")
ASK_WHAT_NEXT = {
    "en": "What would you like me to do?", "pcm": "Wetin you wan make I do?",
    "yo": "Kí ni o fẹ́ kí n ṣe?", "ha": "Me kake so in yi?", "ig": "Gịnị ka ịchọrọ ka m mee?",
}
STUCK = {
    "en": "I tried a few ways and it didn't work. What should I do?",
    "pcm": "I don try am different ways but e no work. Wetin I go do?",
    "yo": "Mo gbìyànjú ní ọ̀nà mélòó kan, kò ṣiṣẹ́. Kí ni kí n ṣe?",
    "ha": "Na gwada hanyoyi da dama amma bai yi aiki ba. Me zan yi?",
    "ig": "Agbalịrị m ụzọ dị iche iche, ọ rụghị ọrụ. Gịnị ka m ga-eme?",
}
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
    # Where the step happens on screen (physical pixels), for the avatar; None if unknown.
    stage: dict[str, Any] | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id, "tool": self.tool, "arguments": redact_args(self.arguments),
            "explanation": self.explanation, "effect": self.effect, "targets": self.targets,
            "outcome": self.outcome, "reason": self.reason, "content_upload": self.content_upload,
            "approval": self.approval, "status": self.status, "message": self.message,
            "verification": self.verification, "verified": self.verified, "data": _safe_data(self.data),
            "stage": self.stage,
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
    control: dict[str, Any] | None = None  # the request was about Vico itself (stay, go, move, greet)
    timeline: list[dict[str, str]] = field(default_factory=list)
    clarifications: list[dict[str, str]] = field(default_factory=list)
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    decision_event: asyncio.Event = field(default_factory=asyncio.Event)
    decision: dict[str, Any] | None = None
    created: float = field(default_factory=time.monotonic)
    task: asyncio.Task | None = None
    version: int = 0
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    def touch(self) -> None:
        """Something the desktop app shows has changed: wake anyone waiting for it."""
        self.version += 1
        self.changed.set()
        self.changed = asyncio.Event()

    def set_state(self, state: RunState, note: str = "") -> None:
        self.state = state
        self.timeline.append({"state": state.value, "at": _now(), "note": note})
        self.touch()

    async def wait_change(self, after: int, timeout: float) -> None:
        if self.version != after:
            return
        try:
            await asyncio.wait_for(self.changed.wait(), timeout)
        except TimeoutError:
            pass

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
            "error": self.error, "cooldown_until": self.cooldown_until, "control": self.control,
            "timeline": self.timeline, "version": self.version,
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

    def stop_all(self) -> list[str]:
        """The stop button: every unfinished task stops now, including a step in the middle of
        running (a running command is killed). Returns the stopped tasks' ids."""
        stopped = []
        for run in self.runs.values():
            if run.state not in TERMINAL_STATES:
                run.cancel.set()
                stopped.append(run.id)
        return stopped

    def busy(self) -> bool:
        return any(r.state not in TERMINAL_STATES for r in self.runs.values())

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
                           summarizer=self.hub.summarize, vision=self.hub.see if self.hub.can_see() else None,
                           language=run.language, cancel=run.cancel)

    async def _drive(self, run: Run) -> None:
        try:
            asked = control.parse(run.text)
            if asked:  # recognised on the computer: instant, no AI call
                lang = control.greeting_language(run.text) or (
                    run.language if run.language != AUTO else guess_language(run.text) or "en")
                self._control(run, asked, lang)
                return
            settings = self.settings_repo.load()
            ctx = self._context(settings, run)
            fast = parse_fast(run.text)
            if fast is not None:
                run.mode = "local"
                await self._single(run, ctx, fast)
                return
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

    def _control(self, run: Run, asked: dict[str, Any], language: str) -> None:
        """A request about Vico itself: the desktop app acts on run.control; nothing runs."""
        run.control = asked
        if asked["action"] == "voice":
            self.settings_repo.update(SettingsPatch(voice_replies=asked.get("value") == "on"))
        if run.language == AUTO:
            run.language = language if language in {lang.value for lang in Language} else Language.EN.value
        run.canonical = run.canonical or run.text
        run.message = control.reply(asked, run.language)
        run.set_state(RunState.COMPLETED, asked["action"])

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

    async def _ask(self, run: Run, question: str) -> str:
        """Ask the user and wait for the answer (spoken or typed). "Never mind" stops the task;
        no answer at all stops it too, with nothing further done."""
        if len(run.clarifications) >= MAX_QUESTIONS:
            raise VicoError(ErrorCode.UNSUPPORTED, "Vico still isn't sure what to do, so it stopped. Try again "
                            "with different words.")
        run.question = question
        run.set_state(RunState.AWAITING_CLARIFICATION, question)
        decision = await self._wait_decision(run)
        run.question = None
        if decision is None:
            raise VicoError(ErrorCode.TIMEOUT, "No answer was given, so Vico stopped. Nothing further was done.")
        answer = decision["answer"]
        if NEVER_MIND.fullmatch(answer.strip().lower().strip(".!")):
            raise Cancelled
        run.clarifications.append({"question": question, "answer": answer})
        return answer

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
        await self._single(run, ctx, plan)

    async def _single(self, run: Run, ctx: ToolContext, plan: ToolCallPlan) -> None:
        """One step from the local parser, finished with the step's own result."""
        run.canonical = run.text
        if run.language == AUTO:
            run.language = Language.EN.value
        step = await self._step(run, ctx, plan)
        if run.state in TERMINAL_STATES:
            return
        if step.status in ("succeeded", "unverified"):
            run.message = step.message
            run.set_state(RunState.COMPLETED, "Done")
        elif step.status == "failed" and run.mode == "local" and self.hub.has_role("llm") and await self.hub.online():
            # e.g. the app has another name: the AI sees what happened and finds it, or asks.
            run.mode = "cloud"
            await self._cloud(run, ctx, self.settings_repo.load())
        else:
            self._fail(run, ErrorCode.POLICY_DENIED if step.status == "denied" else ErrorCode.INTERNAL,
                       step.message or step.reason)

    # --- cloud ---------------------------------------------------------------------------
    async def _cloud(self, run: Run, ctx: ToolContext, settings: Settings) -> None:
        run.canonical = run.text
        if run.language == AUTO and guess_language(run.text) == Language.EN:
            run.language = Language.EN.value
        # Otherwise the first planner reply names the language (and restores tone marks), so a
        # Yoruba, Hausa, Igbo or Pidgin request costs one AI call instead of two.

        failures = 0
        tool_steps = 0
        while True:
            if tool_steps >= settings.max_steps:
                self._fail(run, ErrorCode.CANCELLED, f"Stopped after {settings.max_steps} steps to stay safe.")
                return
            run.set_state(RunState.PLANNING)
            plan = await self._plan(run, ctx)
            ctx.language = run.language
            if isinstance(plan, DonePlan):
                run.message = plan.message  # already in the user's language
                run.set_state(RunState.COMPLETED, "Done")
                return
            if isinstance(plan, BatchPlan):
                failed = await self._batch(run, ctx, plan)
                if run.state in TERMINAL_STATES:
                    return
                tool_steps += len(plan.calls)
                failures = failures + 1 if failed else 0
                if failures >= MAX_FAILED_STEPS:
                    await self._ask(run, self._stuck_question(run))
                    failures = 0
                continue
            if isinstance(plan, ControlPlan):
                asked = control.clean(plan.model_dump(exclude_none=True))
                if asked and not run.steps:
                    self._control(run, asked, run.language)
                    return
                run.message = "Done."
                run.set_state(RunState.COMPLETED, "Done")
                return
            if isinstance(plan, UnsupportedPlan):
                if plan.never:  # payments, passwords, CAPTCHAs: Vico never does these
                    self._fail(run, ErrorCode.UNSUPPORTED, plan.reason)
                    return
                # Anything else: say what is in the way and let the user decide, instead of giving up.
                await self._ask(run, f"{plan.reason} {ASK_WHAT_NEXT.get(run.language, ASK_WHAT_NEXT['en'])}")
                continue
            if isinstance(plan, ClarifyPlan):
                await self._ask(run, plan.question)
                continue

            assert isinstance(plan, ToolCallPlan)
            step = await self._step(run, ctx, plan)
            if run.state in TERMINAL_STATES:
                return
            tool_steps += 1
            if plan.final and step.status == "succeeded":
                # The planner said this step completes the request and it was verified: no extra
                # round trip to be told so. A failure or an unverified result plans again.
                run.message = plan.message or step.message
                run.set_state(RunState.COMPLETED, "Done")
                return
            if step.status in ("failed", "denied"):
                failures += 1
                if failures >= MAX_FAILED_STEPS:
                    await self._ask(run, self._stuck_question(run))
                    failures = 0
            else:
                failures = 0

    @staticmethod
    def _stuck_question(run: Run) -> str:
        last = next((s for s in reversed(run.steps) if s.status in ("failed", "denied")), None)
        why = f" The last try said: {last.message}" if last and last.message else ""
        return STUCK.get(run.language, STUCK["en"]) + why

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
                raw, meta = split_meta(parse_json_text(completion.text))
                plan = parse_plan(raw)
            except (ValueError, VicoError) as exc:
                last_error = str(exc)[:300]
                continue
            self._learn_language(run, meta)
            return plan
        raise VicoError(ErrorCode.INVALID_PLAN, "The AI did not return a valid plan, so nothing was run.")

    def _learn_language(self, run: Run, meta: dict[str, Any]) -> None:
        if run.language != AUTO:
            return
        named = str(meta.get("language", "")).strip().lower()
        run.language = named if named in {lang.value for lang in Language} else Language.EN.value
        restored = meta.get("restored")
        if isinstance(restored, str):
            run.original = safe_restoration(run.text, restored) or run.original
        run.timeline.append({"state": "understood", "at": _now(), "note": run.language})

    async def _batch(self, run: Run, ctx: ToolContext, plan: BatchPlan) -> bool:
        """Several reading steps at once. Anything that is not a plain read (no approval needed)
        is refused, so approval and confirmation steps always stay one at a time."""
        checks = []
        for call in plan.calls:
            pf = await self._until(run, policy.preflight(self.registry, ctx, call.tool, call.arguments))
            checks.append((call, pf))
        if any(pf.decision.outcome is not policy.Outcome.ALLOWED or pf.spec is None or
               pf.spec.risk is not Risk.AUTO for _, pf in checks):
            step = Step(id=uuid.uuid4().hex[:8], tool="batch", arguments={}, explanation=plan.explanation,
                        status="denied", message="Only reading steps can run together.",
                        observation="Batch refused: only reading tools (list, read, find) can be batched. "
                                    "Propose one step at a time.")
            run.steps.append(step)
            return True
        steps = []
        for call, pf in checks:
            d = pf.decision
            step = Step(id=uuid.uuid4().hex[:8], tool=call.tool, arguments=call.arguments,
                        explanation=plan.explanation, effect=d.effect, targets=d.targets, outcome=d.outcome.value,
                        reason=d.reason, approval="auto", status="running")
            run.steps.append(step)
            steps.append((step, pf))
        run.set_state(RunState.EXECUTING, "batch")
        results = await asyncio.gather(*(self._execute(run, ctx, pf, step) for step, pf in steps))
        run.set_state(RunState.VERIFYING, "batch")
        failed = False
        for (step, _), result in zip(steps, results, strict=True):
            step.message, step.verification, step.verified = result.message, result.verification, result.verified
            step.data, step.observation = result.data, result.observation or result.message
            if "<untrusted_content" in step.observation:
                ctx.tainted = True
            step.status = "failed" if not result.ok else ("succeeded" if result.verified else "unverified")
            failed = failed or not result.ok
            self._record(run, step)
        run.touch()
        return failed

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
        # Found alongside the step, never before it, so the avatar never slows the task down.
        locating = asyncio.create_task(self._locate(run, ctx, step, pf.args))
        result = await self._execute(run, ctx, pf, step)
        if not locating.done():
            locating.cancel()
        run.set_state(RunState.VERIFYING, step.tool)
        step.message, step.verification, step.verified = result.message, result.verification, result.verified
        step.data, step.observation = result.data, result.observation or result.message
        if "<untrusted_content" in step.observation:
            ctx.tainted = True  # later deletes, sends and commands in this task are checked with the user
        if not result.ok:
            step.status = "failed"
        else:
            step.status = "succeeded" if result.verified else "unverified"
        self._record(run, step)
        return step

    async def _locate(self, run: Run, ctx: ToolContext, step: Step, args: Any) -> None:
        try:
            step.stage = await asyncio.wait_for(stage.locate(ctx, step.tool, args), 2.0)
        except Exception:  # noqa: S110 - an unknown position just means no stage
            step.stage = None
        run.touch()

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

