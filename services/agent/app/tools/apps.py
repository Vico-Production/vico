"""Launch installed applications by name."""

from __future__ import annotations

import asyncio

from app.agent.schemas import ListAppsArgs, OpenAppArgs
from app.contracts import ErrorCode, VicoError
from app.platform.base import AppEntry
from app.tools.base import Inspection, Risk, ToolContext, ToolResult, ToolSpec


def _resolve_app(ctx: ToolContext, name: str) -> AppEntry:
    matches = ctx.platform.find_apps(name)
    if not matches:
        raise VicoError(ErrorCode.NOT_FOUND, f"No installed app matches '{name}'.", status=404)
    return matches[0]


async def inspect_open_app(ctx: ToolContext, a: OpenAppArgs) -> Inspection:
    entry = await asyncio.to_thread(_resolve_app, ctx, a.name)
    return Inspection(effect=f"Start the app {entry.name}", targets=[entry.target], label=entry.name)


async def open_app(ctx: ToolContext, a: OpenAppArgs) -> ToolResult:
    entry = await asyncio.to_thread(_resolve_app, ctx, a.name)
    try:
        before = {w.title for w in ctx.platform.list_windows()}
    except VicoError:
        before = None
    pid = await asyncio.to_thread(ctx.platform.launch_app, entry)
    title = None
    if before is not None:
        needle = entry.name.split()[0]
        title = await asyncio.to_thread(ctx.platform.wait_for_window, needle, before)
    if title:
        return ToolResult(ok=True, message=f"Opened {entry.name}.", verified=True,
                          verification=f"Window appeared: {title}", data={"app": entry.name, "window": title},
                          observation=f"{entry.name} is open in window '{title}'")
    if pid and ctx.platform.process_alive(pid):
        return ToolResult(ok=True, message=f"Started {entry.name}.", verified=True,
                          verification=f"Process {pid} is running.", data={"app": entry.name, "pid": pid},
                          observation=f"{entry.name} started (process {pid})")
    return ToolResult(ok=True, message=f"Asked the system to start {entry.name}.", verified=False,
                      verification="No window or running process was confirmed.", data={"app": entry.name},
                      observation=f"Requested start of {entry.name}; not confirmed")


async def inspect_list_apps(ctx: ToolContext, a: ListAppsArgs) -> Inspection:
    return Inspection(effect=f"List installed apps{' matching ' + repr(a.query) if a.query else ''}")


async def list_apps(ctx: ToolContext, a: ListAppsArgs) -> ToolResult:
    entries = await asyncio.to_thread(ctx.platform.find_apps, a.query)
    names = [e.name for e in entries[:60]]
    return ToolResult(ok=True, message=f"{len(entries)} app(s) found.", verified=True,
                      verification="Read from the installed app list.", data={"apps": names},
                      observation="\n".join(names) or "(none)")


def specs() -> list[ToolSpec]:
    return [
        ToolSpec("open_app", "Start an installed application by its name, e.g. 'notepad', 'calculator', "
                 "'Microsoft Edge', 'Spotify'.", OpenAppArgs, Risk.STANDARD, open_app, inspect_open_app, "apps"),
        ToolSpec("list_apps", "List installed applications, optionally filtered by name.", ListAppsArgs,
                 Risk.AUTO, list_apps, inspect_list_apps, "apps"),
    ]
