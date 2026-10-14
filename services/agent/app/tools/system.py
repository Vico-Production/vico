"""Run a shell command. Always needs explicit confirmation, even with the approval switch off."""

from __future__ import annotations

import asyncio
import subprocess

from app.agent.schemas import RunCommandArgs
from app.config import COMMAND_TIMEOUT_S
from app.security.guards import payment_or_secret_reason
from app.security.redaction import redact_text
from app.tools.base import Inspection, Risk, ToolContext, ToolResult, ToolSpec, fail

MAX_OUTPUT = 4000


async def inspect_command(ctx: ToolContext, a: RunCommandArgs) -> Inspection:
    cwd = ctx.paths.resolve(a.cwd)
    argv = ctx.platform.shell_argv(a.command, a.shell)
    return Inspection(
        effect=f"Run this command in {ctx.paths.display(cwd)} using {argv[0]}:\n{a.command}",
        targets=[str(cwd)],
        label=a.command,
        deny_reason=payment_or_secret_reason(a.command),
    )


async def run_command(ctx: ToolContext, a: RunCommandArgs) -> ToolResult:
    cwd = ctx.paths.resolve(a.cwd)
    if not cwd.is_dir():
        return fail(f"{ctx.paths.display(cwd)} is not a folder.")
    argv = ctx.platform.shell_argv(a.command, a.shell)

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - user-approved command, argv form
            argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=COMMAND_TIMEOUT_S, check=False, stdin=subprocess.DEVNULL,
        )

    try:
        proc = await asyncio.to_thread(run)
    except subprocess.TimeoutExpired:
        return fail(f"The command did not finish within {COMMAND_TIMEOUT_S} seconds and was stopped.")
    out = redact_text((proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else ""))
    cut = len(out) > MAX_OUTPUT
    out = out[:MAX_OUTPUT]
    ok = proc.returncode == 0
    return ToolResult(
        ok=ok,
        message=f"Command {'finished' if ok else 'failed'} with exit code {proc.returncode}.",
        verified=ok,
        verification=f"Exit code {proc.returncode}.",
        data={"exit_code": proc.returncode, "output": out, "truncated": cut},
        observation=f"exit code {proc.returncode}\n<untrusted_content source=\"command output\">\n{out}\n"
                    "</untrusted_content>",
    )


def specs() -> list[ToolSpec]:
    return [
        ToolSpec("run_command", "Run a shell command (PowerShell on Windows, bash on Linux). Use only when no "
                 "other tool fits. Always shown to the user for confirmation.", RunCommandArgs, Risk.CONFIRM,
                 run_command, inspect_command, "system"),
    ]
