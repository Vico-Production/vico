"""Control other desktop windows: focus, type, press keys, click named controls."""

from __future__ import annotations

import asyncio

from app.agent.schemas import ClickElementArgs, FocusWindowArgs, NoArgs, PressKeysArgs, TypeTextArgs
from app.security.guards import is_payment_action, is_send_action, payment_or_secret_reason
from app.tools.base import Inspection, Risk, ToolContext, ToolResult, ToolSpec, fail


async def inspect_list_windows(ctx: ToolContext, a: NoArgs) -> Inspection:
    return Inspection(effect="List open windows")


async def list_windows(ctx: ToolContext, a: NoArgs) -> ToolResult:
    windows = await asyncio.to_thread(ctx.platform.list_windows)
    titles = [w.title for w in windows]
    return ToolResult(ok=True, message=f"{len(titles)} open window(s).", verified=True,
                      verification="Read from the window manager.", data={"windows": titles},
                      observation="\n".join(titles) or "(none)")


async def inspect_focus(ctx: ToolContext, a: FocusWindowArgs) -> Inspection:
    return Inspection(effect=f"Bring the window '{a.title}' to the front", label=a.title)


async def focus_window(ctx: ToolContext, a: FocusWindowArgs) -> ToolResult:
    info = await asyncio.to_thread(ctx.platform.focus_window, a.title)
    return ToolResult(ok=True, message=f"Switched to '{info.title}'.", verified=True,
                      verification="The window manager focused the window.", data={"window": info.title},
                      observation=f"Focused window '{info.title}'")


async def inspect_type(ctx: ToolContext, a: TypeTextArgs) -> Inspection:
    preview = a.text[:120] + ("..." if len(a.text) > 120 else "")
    return Inspection(effect=f"Type \"{preview}\" into the active window",
                      deny_reason=payment_or_secret_reason(a.text))


async def type_text(ctx: ToolContext, a: TypeTextArgs) -> ToolResult:
    reason = payment_or_secret_reason(a.text)
    if reason:
        return fail(reason)
    if await asyncio.to_thread(ctx.platform.focused_is_secret):
        return fail("The active field is a password field. Vico never types passwords.")
    await asyncio.to_thread(ctx.platform.type_text, a.text)
    return ToolResult(ok=True, message=f"Typed {len(a.text)} characters.", verified=False,
                      verification="Keystrokes were sent; Vico cannot read them back from other apps.",
                      observation=f"Typed {len(a.text)} characters into the active window")


async def inspect_keys(ctx: ToolContext, a: PressKeysArgs) -> Inspection:
    return Inspection(effect=f"Press {a.keys} in the active window", label=a.keys)


async def press_keys(ctx: ToolContext, a: PressKeysArgs) -> ToolResult:
    await asyncio.to_thread(ctx.platform.press_keys, a.keys)
    return ToolResult(ok=True, message=f"Pressed {a.keys}.", verified=False,
                      verification="Key press sent; the effect depends on the active app.",
                      observation=f"Pressed {a.keys}")


async def inspect_click(ctx: ToolContext, a: ClickElementArgs) -> Inspection:
    deny = None
    if is_payment_action(a.name):
        deny = f"'{a.name}' looks like a payment button. Vico never makes payments."
    return Inspection(effect=f"Click '{a.name}' in the window '{a.window}'", label=a.name, deny_reason=deny,
                      send_like=is_send_action(a.name))


async def click_element(ctx: ToolContext, a: ClickElementArgs) -> ToolResult:
    if is_payment_action(a.name):
        return fail(f"'{a.name}' looks like a payment button. Vico never makes payments.")
    clicked = await asyncio.to_thread(ctx.platform.click_element, a.window, a.name)
    if is_payment_action(clicked):
        return fail(f"Stopped: the matched control '{clicked}' looks like a payment button.")
    return ToolResult(ok=True, message=f"Clicked '{clicked}'.", verified=True,
                      verification="The control accepted the click.", data={"control": clicked},
                      observation=f"Clicked '{clicked}' in '{a.window}'")


def specs() -> list[ToolSpec]:
    return [
        ToolSpec("list_windows", "List titles of open windows.", NoArgs, Risk.AUTO, list_windows,
                 inspect_list_windows, "desktop"),
        ToolSpec("focus_window", "Bring a window to the front by part of its title.", FocusWindowArgs,
                 Risk.STANDARD, focus_window, inspect_focus, "desktop"),
        ToolSpec("type_text", "Type text into the active window (never passwords or card numbers).",
                 TypeTextArgs, Risk.STANDARD, type_text, inspect_type, "desktop"),
        ToolSpec("press_keys", "Press a key or shortcut in the active window, e.g. 'enter', 'ctrl+s'.",
                 PressKeysArgs, Risk.STANDARD, press_keys, inspect_keys, "desktop"),
        ToolSpec("click_element", "Click a button or control by its visible name inside a window "
                 "(Windows only).", ClickElementArgs, Risk.STANDARD, click_element, inspect_click, "desktop",
                 platforms=("win32",)),
    ]
