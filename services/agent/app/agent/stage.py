"""Where on screen each step happens, so Vico's avatar can act it out at the real spot.

The lookup runs alongside the step, never before it, so it never slows a task down. When
the exact control is unknown the window is used; when nothing is known there is no stage and
the avatar acts the step out beside itself rather than at a guessed position.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.tools.base import ToolContext

BROWSER_TOOLBAR = {"browser_open", "browser_back", "browser_press", "browser_scroll", "browser_read"}


def _stage(rect: Any, kind: str) -> dict[str, Any] | None:
    """A stage in physical screen pixels, or None for an unknown or empty rectangle."""
    if not rect:
        return None
    if isinstance(rect, dict):
        x, y, w, h = rect.get("x"), rect.get("y"), rect.get("width"), rect.get("height")
    else:
        x, y, w, h = rect
    try:
        values = [round(float(v)) for v in (x, y, w, h)]  # type: ignore[arg-type]
        box = dict(zip(("x", "y", "width", "height"), values, strict=True))
    except (TypeError, ValueError):
        return None
    if box["width"] <= 0 or box["height"] <= 0:
        return None
    return {"rect": box, "kind": kind}


async def locate(ctx: ToolContext, tool: str, args: Any) -> dict[str, Any] | None:
    """kind: element (a control to tap), field (where typing goes), window, titlebar (the window,
    when the control itself could not be found) or toolbar (the browser's tabs and address bar)."""
    platform = ctx.platform
    if tool == "click_element":
        rect = await asyncio.to_thread(platform.element_rect, args.window, args.name)
        if rect:
            return _stage(rect, "element")
        return _stage(await asyncio.to_thread(platform.window_rect, args.window), "titlebar")
    if tool == "focus_window":
        return _stage(await asyncio.to_thread(platform.window_rect, args.title), "window")
    if tool in ("type_text", "press_keys"):
        return _stage(await asyncio.to_thread(platform.focus_rect), "field")
    browser = ctx.browser
    if browser is None or not tool.startswith("browser_"):
        return None
    if tool == "browser_click":
        found = _stage(await browser.screen_rect(args.target, "click"), "element")
        return found or _stage(await browser.screen_rect(None), "toolbar")
    if tool == "browser_type":
        found = _stage(await browser.screen_rect(args.target, "fill"), "field")
        return found or _stage(await browser.screen_rect(None), "toolbar")
    if tool in BROWSER_TOOLBAR:
        return _stage(await browser.screen_rect(None), "toolbar")
    return None
