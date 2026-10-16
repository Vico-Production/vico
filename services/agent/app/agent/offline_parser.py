"""Deterministic English command parser used when the cloud is unavailable.

Supports: create/make folder X [on desktop|in documents], find/search X, open <app or file>,
show/list files [in X], save note X: content. Anything else returns None.
"""

from __future__ import annotations

import re

from app.agent.schemas import ToolCallPlan

_LOCATIONS = {
    "desktop": "~/Desktop", "my desktop": "~/Desktop", "the desktop": "~/Desktop",
    "documents": "~/Documents", "my documents": "~/Documents",
    "downloads": "~/Downloads", "my downloads": "~/Downloads",
}
_KNOWN_APPS = {"notepad", "calculator", "settings", "windows settings", "control panel", "calc", "paint", "file explorer", "explorer", "vs code", "vscode",
               "visual studio code", "task manager", "powershell", "command prompt", "terminal", "text editor"}
_APP_ALIASES = {"calc": "calculator", "explorer": "file explorer", "vscode": "vs code"}


def _clean(value: str) -> str:
    value = value.strip().strip(".!?").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'“”‘’":
        value = value[1:-1]
    return value.strip("\"'“”‘’ ").strip()


def _location(phrase: str | None) -> str | None:
    if not phrase:
        return None
    return _LOCATIONS.get(phrase.strip().lower())


def _call(tool: str, explanation: str, **arguments: object) -> ToolCallPlan:
    return ToolCallPlan(kind="tool_call", tool=tool, arguments=arguments, explanation=explanation)


_CREATE = re.compile(
    r"^(?:please\s+)?(?:create|make|new)\s+(?:a\s+)?(?:new\s+)?folder\s+(?:called\s+|named\s+)?(?P<name>.+?)"
    r"(?:\s+(?:on|in)\s+(?P<loc>(?:my\s+|the\s+)?(?:desktop|documents|downloads)))?\s*$",
    re.IGNORECASE,
)
_FIND = re.compile(r"^(?:please\s+)?(?:find|search(?:\s+for)?|look\s+for)\s+(?:my\s+|the\s+)?(?P<q>.+?)\s*$",
                   re.IGNORECASE)
_LIST = re.compile(
    r"^(?:please\s+)?(?:show|list)\s+(?:me\s+)?(?:my\s+|the\s+)?(?:files|folders|contents)"
    r"(?:\s+(?:in|on)\s+(?P<loc>.+?))?\s*$",
    re.IGNORECASE,
)
_OPEN = re.compile(r"^(?:please\s+)?(?:open|launch|start|run)\s+(?:the\s+|my\s+)?(?P<target>.+?)\s*$", re.IGNORECASE)
_NOTE = re.compile(
    r"^(?:please\s+)?(?:save|write|create|make)\s+(?:a\s+)?note\s+(?:called\s+|named\s+|titled\s+)?"
    r"(?P<title>[^:]+?)\s*(?::|saying|that\s+says|with)\s*(?P<content>.+)$",
    re.IGNORECASE | re.DOTALL,
)


def parse_offline(text: str) -> ToolCallPlan | None:
    command = text.strip()
    if not command or len(command) > 500:
        return None

    if m := _NOTE.match(command):
        return _call("save_note", "Save a note", title=_clean(m["title"]), content=m["content"].strip())

    if m := _CREATE.match(command):
        name = _clean(m["name"])
        base = _location(m["loc"])
        if not name:
            return None
        return _call("create_folder", f"Create folder {name}", path=f"{base}/{name}" if base else name)

    if m := _LIST.match(command):
        loc = m["loc"]
        path = _location(loc) or (_clean(loc) if loc else ".")
        return _call("list_folder", "List files", path=path)

    if m := _FIND.match(command):
        query = _clean(m["q"])
        return _call("find_files", f"Find {query}", query=query) if query else None

    if m := _OPEN.match(command):
        target = _clean(m["target"])
        lowered = target.lower()
        if lowered in _KNOWN_APPS:
            return _call("open_app", f"Open {target}", name=_APP_ALIASES.get(lowered, lowered))
        if re.search(r"\.[A-Za-z0-9]{1,5}$", target):
            return _call("open_file", f"Open {target}", path=target)
        loc = _location(lowered)
        if loc:
            return _call("open_file", f"Open {target}", path=loc)
        return _call("open_app", f"Open {target}", name=target)

    return None


OFFLINE_HELP = ("Cloud is unavailable, so only simple typed English commands work: "
                "'create folder Demo', 'find notes', 'open notepad', 'show files', 'save note Ideas: text'.")


# --- the fast path ---------------------------------------------------------------------
# Online, a request that is exactly one of these simple commands runs without asking the AI.
# Much stricter than the offline parser: anything with more than one action, a connector or
# an unknown app goes to the AI, so speed never changes what Vico does.
_COMPOUND = re.compile(r"\b(?:and|then|after|before|with|but|if|so|also|while|until)\b|[,;:&]", re.IGNORECASE)


def parse_fast(text: str) -> ToolCallPlan | None:
    command = text.strip().rstrip(".!")
    if not command or len(command) > 80 or "\n" in command:
        return None
    if m := _OPEN.match(command):
        target = _clean(m["target"]).lower()
        if target in _KNOWN_APPS:
            return _call("open_app", f"Open {target}", name=_APP_ALIASES.get(target, target))
        return None
    if _COMPOUND.search(command):
        return None
    if m := _CREATE.match(command):
        name = _clean(m["name"])
        if name and len(name.split()) <= 4 and not re.search(r"[\\/]", name):
            base = _location(m["loc"])
            return _call("create_folder", f"Create folder {name}", path=f"{base}/{name}" if base else name)
        return None
    if m := _LIST.match(command):
        loc = m["loc"]
        if loc is None:
            return _call("list_folder", "List files", path=".")
        path = _location(loc)
        return _call("list_folder", "List files", path=path) if path else None
    return None
