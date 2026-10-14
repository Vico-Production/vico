"""Browser control through Playwright, using the Edge or Chrome already on the computer.

Vico drives its own browser profile (stored in Vico's data folder), separate from the
user's everyday profile, so it never sees saved passwords or existing sessions unless
the user signs in inside that window themselves.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from app.agent.schemas import (
    BrowserClickArgs,
    BrowserReadArgs,
    BrowserScrollArgs,
    BrowserTypeArgs,
    KeyArgs,
    NoArgs,
    UrlArgs,
)
from app.contracts import ErrorCode, VicoError
from app.security.guards import is_payment_action, is_secret_field, is_send_action, payment_or_secret_reason
from app.tools.base import Inspection, Risk, ToolContext, ToolResult, ToolSpec, fail

log = logging.getLogger(__name__)

_FACTS_JS = """
(el) => {
  const label = (() => {
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return l.innerText; }
    const p = el.closest('label'); return p ? p.innerText : '';
  })();
  return {
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute('type') || '',
    name: el.getAttribute('name') || '',
    id: el.id || '',
    placeholder: el.getAttribute('placeholder') || '',
    autocomplete: el.getAttribute('autocomplete') || '',
    'aria-label': el.getAttribute('aria-label') || '',
    role: el.getAttribute('role') || '',
    label: (label || '').trim().slice(0, 120),
    text: ((el.innerText || el.value || '') + '').trim().slice(0, 120),
  };
}
"""

_INTERACTIVE_JS = """
() => {
  const out = [];
  const els = document.querySelectorAll('a[href], button, input, textarea, select, [role=button], [role=link], [role=searchbox], [role=textbox]');
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const name = (el.getAttribute('aria-label') || el.innerText || el.value || el.getAttribute('placeholder') || el.getAttribute('name') || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
    if (!name) continue;
    const tag = el.tagName.toLowerCase();
    const kind = tag === 'a' ? 'link' : (tag === 'input' || tag === 'textarea' || tag === 'select') ? `field:${el.type || tag}` : 'button';
    out.push(`[${kind}] ${name}`);
    if (out.length >= 60) break;
  }
  return out;
}
"""


def _is_search_field(facts: dict[str, Any]) -> bool:
    hints = " ".join(str(facts.get(k, "")) for k in ("type", "name", "id", "placeholder", "aria-label", "role", "label"))
    hints = hints.lower()
    return facts.get("type") == "search" or "search" in hints or facts.get("name") in ("q", "query", "search_query")


class BrowserController:
    def __init__(self, profile_dir: Path, channel: str = "auto"):
        self.profile_dir = profile_dir
        self.channel = channel
        self._pw: Any = None
        self._context: Any = None
        self._lock = asyncio.Lock()

    @property
    def is_open(self) -> bool:
        return self._context is not None

    def _channels(self) -> list[str | None]:
        if self.channel != "auto":
            return [None if self.channel == "chromium" else self.channel]
        if sys.platform == "win32":
            return ["msedge", "chrome", None]
        return ["chrome", "msedge", None]

    async def _ensure(self) -> Any:
        async with self._lock:
            if self._context is not None:
                return self._context
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise VicoError(ErrorCode.UNSUPPORTED, "Browser control is not installed.") from exc
            self._pw = await async_playwright().start()
            errors = []
            for channel in self._channels():
                try:
                    kwargs: dict[str, Any] = {"headless": False, "no_viewport": True}
                    if channel:
                        kwargs["channel"] = channel
                    self._context = await self._pw.chromium.launch_persistent_context(str(self.profile_dir), **kwargs)
                    self._context.on("close", lambda *_: self._reset())
                    return self._context
                except Exception as exc:  # try the next installed browser
                    errors.append(f"{channel or 'chromium'}: {type(exc).__name__}")
            await self._pw.stop()
            self._pw = None
            raise VicoError(
                ErrorCode.UNSUPPORTED,
                "No supported browser was found (tried " + ", ".join(errors) + "). Install Microsoft Edge or "
                "Google Chrome.",
            )

    def _reset(self) -> None:
        self._context = None

    async def page(self, create: bool = True) -> Any:
        if not create and self._context is None:
            raise VicoError(ErrorCode.CONFLICT, "No browser page is open. Open a web page first.")
        context = await self._ensure()
        pages = [p for p in context.pages if not p.is_closed()]
        return pages[-1] if pages else await context.new_page()

    async def locate(self, target: str, kind: str) -> Any:
        page = await self.page(create=False)
        if target.startswith("css="):
            candidates = [page.locator(target[4:])]
        elif kind == "fill":
            candidates = [
                page.get_by_label(target), page.get_by_placeholder(target),
                page.get_by_role("textbox", name=target), page.get_by_role("searchbox", name=target),
                page.get_by_role("combobox", name=target),
            ]
        else:
            candidates = [
                page.get_by_role("button", name=target), page.get_by_role("link", name=target),
                page.get_by_label(target), page.get_by_text(target, exact=False),
            ]
        for loc in candidates:
            try:
                count = min(await loc.count(), 5)
            except Exception:  # noqa: S112 - invalid selector for this strategy
                continue
            for i in range(count):
                item = loc.nth(i)
                if await item.is_visible():
                    return item
        raise VicoError(ErrorCode.NOT_FOUND, f"Nothing on the page matches '{target}'.", status=404)

    async def facts(self, locator: Any) -> dict[str, Any]:
        return await locator.evaluate(_FACTS_JS)

    async def snapshot(self, max_chars: int) -> dict[str, Any]:
        page = await self.page(create=False)
        text = await page.locator("body").inner_text(timeout=5000)
        controls = await page.evaluate(_INTERACTIVE_JS)
        return {"url": page.url, "title": await page.title(), "text": text[:max_chars],
                "truncated": len(text) > max_chars, "controls": controls}

    async def close(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                log.info("browser already closed")
        if self._pw is not None:
            await self._pw.stop()
        self._context = None
        self._pw = None


def _browser(ctx: ToolContext) -> BrowserController:
    if ctx.browser is None:
        raise VicoError(ErrorCode.UNSUPPORTED, "Browser control is not available.")
    return ctx.browser


async def _page_result(b: BrowserController, message: str) -> ToolResult:
    page = await b.page(create=False)
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        log.info("page still loading")
    title = await page.title()
    return ToolResult(ok=True, message=message, verified=True, verification=f"Page is now {page.url}",
                      data={"url": page.url, "title": title},
                      observation=f"{message} Current page: '{title}' at {page.url}")


async def _guard(fn, *args) -> ToolResult:
    try:
        return await fn(*args)
    except VicoError:
        raise
    except Exception as exc:
        name = type(exc).__name__
        return fail(f"The browser action failed ({name}): {str(exc).splitlines()[0][:200]}")


# --- tools -------------------------------------------------------------------------------
async def inspect_open_url(ctx: ToolContext, a: UrlArgs) -> Inspection:
    return Inspection(effect=f"Open {a.url} in your default web browser", targets=[a.url])


async def open_url(ctx: ToolContext, a: UrlArgs) -> ToolResult:
    await asyncio.to_thread(ctx.platform.open_url, a.url)
    return ToolResult(ok=True, message=f"Opened {a.url} in your browser.", verified=False,
                      verification="The system accepted the request; Vico cannot see your own browser.",
                      observation=f"Opened {a.url} in the default browser (not controllable)")


async def inspect_browse(ctx: ToolContext, a: UrlArgs) -> Inspection:
    return Inspection(effect=f"Open {a.url} in Vico's browser window", targets=[a.url])


async def browser_open(ctx: ToolContext, a: UrlArgs) -> ToolResult:
    b = _browser(ctx)

    async def go() -> ToolResult:
        page = await b.page()
        await page.goto(a.url, wait_until="domcontentloaded", timeout=30000)
        return await _page_result(b, f"Opened {a.url}.")

    return await _guard(go)


async def inspect_click(ctx: ToolContext, a: BrowserClickArgs) -> Inspection:
    b = _browser(ctx)
    loc = await b.locate(a.target, "click")
    facts = await b.facts(loc)
    label = facts.get("text") or facts.get("aria-label") or facts.get("label") or a.target
    deny = None
    if is_payment_action(label) or is_payment_action(a.target):
        deny = f"'{label}' looks like a payment or purchase button. Vico never makes payments."
    page = await b.page(create=False)
    return Inspection(effect=f"Click '{label}' on {page.url}", targets=[page.url], label=label,
                      deny_reason=deny, send_like=is_send_action(label) or facts.get("type") == "submit")


async def browser_click(ctx: ToolContext, a: BrowserClickArgs) -> ToolResult:
    b = _browser(ctx)

    async def go() -> ToolResult:
        loc = await b.locate(a.target, "click")
        facts = await b.facts(loc)
        label = facts.get("text") or facts.get("aria-label") or a.target
        if is_payment_action(label):
            return fail(f"Stopped: '{label}' looks like a payment button.")
        await loc.click(timeout=10000)
        return await _page_result(b, f"Clicked '{label}'.")

    return await _guard(go)


async def inspect_type(ctx: ToolContext, a: BrowserTypeArgs) -> Inspection:
    b = _browser(ctx)
    loc = await b.locate(a.target, "fill")
    facts = await b.facts(loc)
    deny = payment_or_secret_reason(a.text)
    if is_secret_field(facts):
        deny = "That field is for a password, PIN or card details. Vico never types those; please type it yourself."
    label = facts.get("label") or facts.get("aria-label") or facts.get("placeholder") or a.target
    preview = a.text[:120] + ("..." if len(a.text) > 120 else "")
    page = await b.page(create=False)
    effect = f"Type \"{preview}\" into '{label}' on {page.url}" + (" and submit" if a.submit else "")
    return Inspection(effect=effect, targets=[page.url], label=label, deny_reason=deny,
                      send_like=a.submit and not _is_search_field(facts))


async def browser_type(ctx: ToolContext, a: BrowserTypeArgs) -> ToolResult:
    b = _browser(ctx)

    async def go() -> ToolResult:
        loc = await b.locate(a.target, "fill")
        facts = await b.facts(loc)
        if is_secret_field(facts) or payment_or_secret_reason(a.text):
            return fail("Stopped: Vico never types passwords, PINs or card details.")
        await loc.fill(a.text, timeout=10000)
        if a.submit:
            await loc.press("Enter")
        return await _page_result(b, f"Typed into '{a.target}'" + (" and submitted." if a.submit else "."))

    return await _guard(go)


async def inspect_press(ctx: ToolContext, a: KeyArgs) -> Inspection:
    b = _browser(ctx)
    page = await b.page(create=False)
    send_like = False
    if a.key.lower() in ("enter", "return"):
        facts = await page.evaluate(
            "() => { const e = document.activeElement; return e ? {type: e.getAttribute('type')||'', "
            "name: e.getAttribute('name')||'', role: e.getAttribute('role')||'', "
            "placeholder: e.getAttribute('placeholder')||'', 'aria-label': e.getAttribute('aria-label')||''} : {} }"
        )
        send_like = not _is_search_field(facts)
    return Inspection(effect=f"Press {a.key} on {page.url}", targets=[page.url], label=a.key, send_like=send_like)


async def browser_press(ctx: ToolContext, a: KeyArgs) -> ToolResult:
    b = _browser(ctx)

    async def go() -> ToolResult:
        page = await b.page(create=False)
        key = "+".join(k[:1].upper() + k[1:] if len(k) > 1 else k for k in a.key.replace(" ", "+").split("+"))
        key = key.replace("Ctrl", "Control")
        await page.keyboard.press(key)
        return await _page_result(b, f"Pressed {a.key}.")

    return await _guard(go)


async def inspect_read(ctx: ToolContext, a: BrowserReadArgs) -> Inspection:
    page = await _browser(ctx).page(create=False)
    return Inspection(effect=f"Read the text of {page.url} so Vico can use it in this task", targets=[page.url])


async def browser_read(ctx: ToolContext, a: BrowserReadArgs) -> ToolResult:
    b = _browser(ctx)

    async def go() -> ToolResult:
        snap = await b.snapshot(a.max_chars)
        controls = "\n".join(snap["controls"])
        return ToolResult(
            ok=True, message=f"Read '{snap['title']}'.", verified=True, verification=f"Read from {snap['url']}",
            data={"url": snap["url"], "title": snap["title"], "truncated": snap["truncated"]},
            observation=(f"Page '{snap['title']}' at {snap['url']}\n<untrusted_content source=\"web page\">\n"
                         f"{snap['text']}\n</untrusted_content>\nClickable/typeable controls:\n{controls}"),
        )

    return await _guard(go)


async def inspect_scroll(ctx: ToolContext, a: BrowserScrollArgs) -> Inspection:
    page = await _browser(ctx).page(create=False)
    return Inspection(effect=f"Scroll {a.direction} on {page.url}", targets=[page.url])


async def browser_scroll(ctx: ToolContext, a: BrowserScrollArgs) -> ToolResult:
    b = _browser(ctx)

    async def go() -> ToolResult:
        page = await b.page(create=False)
        await page.mouse.wheel(0, 700 if a.direction == "down" else -700)
        return await _page_result(b, f"Scrolled {a.direction}.")

    return await _guard(go)


async def inspect_back(ctx: ToolContext, a: NoArgs) -> Inspection:
    page = await _browser(ctx).page(create=False)
    return Inspection(effect=f"Go back from {page.url}", targets=[page.url])


async def browser_back(ctx: ToolContext, a: NoArgs) -> ToolResult:
    b = _browser(ctx)

    async def go() -> ToolResult:
        page = await b.page(create=False)
        await page.go_back(timeout=15000)
        return await _page_result(b, "Went back.")

    return await _guard(go)


def specs() -> list[ToolSpec]:
    web = "web"
    return [
        ToolSpec("open_url", "Open a web address in the user's own default browser (Vico cannot control it "
                 "afterwards).", UrlArgs, Risk.STANDARD, open_url, inspect_open_url, web),
        ToolSpec("browser_open", "Open a web address in Vico's controllable browser window.", UrlArgs,
                 Risk.STANDARD, browser_open, inspect_browse, web),
        ToolSpec("browser_read", "Read the current page's text and list its clickable controls.",
                 BrowserReadArgs, Risk.STANDARD, browser_read, inspect_read, web),
        ToolSpec("browser_click", "Click a link or button by its visible text or label (or 'css=<selector>').",
                 BrowserClickArgs, Risk.STANDARD, browser_click, inspect_click, web),
        ToolSpec("browser_type", "Type into a field found by its label or placeholder; submit presses Enter. "
                 "Never for passwords or card details.", BrowserTypeArgs, Risk.STANDARD, browser_type,
                 inspect_type, web),
        ToolSpec("browser_press", "Press a key in the browser page, e.g. Enter, Tab, PageDown.", KeyArgs,
                 Risk.STANDARD, browser_press, inspect_press, web),
        ToolSpec("browser_scroll", "Scroll the page up or down.", BrowserScrollArgs, Risk.STANDARD,
                 browser_scroll, inspect_scroll, web),
        ToolSpec("browser_back", "Go back to the previous page.", NoArgs, Risk.STANDARD, browser_back,
                 inspect_back, web),
    ]
