"""Requests about Vico itself rather than a task: stay, go, move somewhere, or just a greeting.

Recognised on the computer first (common English, Pidgin, Yorùbá, Hausa and Igbo phrasings),
so the reply is instant and needs no AI call. Anything else is classified by the same AI call
that already reads the request (understand or the planner), never by an extra round trip.
These are never sent to the planner as tasks.
"""

from __future__ import annotations

import re
from typing import Any

ACTIONS = ("stay", "go", "move", "greet")
PLACES = ("left", "right", "top", "bottom", "top-left", "top-right", "bottom-left", "bottom-right", "away")
MAX_WORDS = 8  # longer requests are tasks ("wait for the page to load, then ...")

_LEAD = re.compile(r"^\W*(?:(?:hey|hi|okay|ok|oya|abeg|please|so|yo)\W+)*vico\b\W*", re.I)
_TRAIL = re.compile(r"(?:\W+(?:vico|please|abeg|o|oh|now|yet|for now|for me|small|biko|don allah|jor|abi))*\W*$", re.I)
# Each pattern must match the whole request (after the name and filler words), so a task that
# merely starts with "wait" or "move" is never mistaken for one of these.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("go", re.compile(
        r"(?:you can go|go away|bye(?: bye)?|goodbye|leave|you can leave|that'?s all|thanks?,? that'?s all|"
        r"thank you,? that'?s all|i'?m done|we'?re done|comot|you fit go|you fit comot|o d[aà]b[oọ]|odabo|"
        r"sai anjima|ka [oọ] d[iị])", re.I)),
    ("stay", re.compile(
        r"(?:stay|stay here|stay with me|stay around|don'?t go|do not go|don'?t leave|do not leave|wait|wait for me|"
        r"hold on|i still need you|don'?t go,? i still need you|no go|no comot|make you no go|wait small|d[uú]r[oó]|"
        r"jira|tsaya|n[oọ]r[oọ])", re.I)),
    ("move", re.compile(
        r"(?:(?:move|go|shift|walk)(?: yourself)?(?: over)?(?: to)?(?: the)? (?:top |bottom |upper |lower )?"
        r"(?:left|right|top|bottom|up|down|corner|side|aside|away)(?: (?:side|corner|edge))?|get out of my way|"
        r"move out of (?:my|the) way|shift comot|put your (?:label|pill|name) (?:at|on|to) the (?:top|bottom))", re.I)),
    ("greet", re.compile(
        r"(?:hello|hi|hey|hey there|wassup|whats? ?up|what'?s up|sup|how far|how body|how you dey|good (?:morning|"
        r"afternoon|evening)|how are you|how are you doing|b[aá]wo ni|bawo|e k[uú] (?:[aà]ar[oọ]|ir[oọ]l[eẹ]|"
        r"[aá]s[aá]n)|sannu|ina kwana|ndewo|kedu|kedụ|you dey|are you there)", re.I)),
]
_GREETING_LANGUAGE = {"bawo": "yo", "báwo": "yo", "e ku": "yo", "e kú": "yo", "sannu": "ha", "ina kwana": "ha",
                      "ndewo": "ig", "kedu": "ig", "kedụ": "ig", "how far": "pcm", "how body": "pcm",
                      "how you dey": "pcm"}
GREETINGS = {"yo": "Báwo ni!", "ha": "Sannu!", "ig": "Ndewo!", "pcm": "How far!", "en": "Hello!"}


def _where(text: str) -> str:
    t = text.lower()
    if "out of" in t or "aside" in t or "comot" in t:
        return "away"
    vertical = "top" if re.search(r"\b(top|up)\b", t) else "bottom" if re.search(r"\b(bottom|down)\b", t) else ""
    side = "left" if "left" in t else "right" if "right" in t else ""
    if vertical and side:
        return f"{vertical}-{side}"
    return vertical or side or "away"


def greeting_language(text: str) -> str | None:
    t = text.lower()
    return next((lang for word, lang in _GREETING_LANGUAGE.items() if word in t), None)


def parse(text: str) -> dict[str, Any] | None:
    """{action, where?} when the whole request is about Vico itself, else None."""
    rest = _TRAIL.sub("", _LEAD.sub("", text.strip())).strip(" .!?,")
    if not rest:
        return {"action": "greet"}  # just its name: "Vico!"
    if len(rest.split()) > MAX_WORDS:
        return None
    for action, pattern in _PATTERNS:
        if pattern.fullmatch(rest):
            if action == "move":
                return {"action": "move", "where": _where(rest)}
            return {"action": action}
    return None


def clean(raw: Any) -> dict[str, Any] | None:
    """Validate a control object coming from the AI; anything odd is ignored."""
    if not isinstance(raw, dict) or raw.get("action") not in ACTIONS:
        return None
    out: dict[str, Any] = {"action": raw["action"]}
    if raw["action"] == "move":
        out["where"] = raw.get("where") if raw.get("where") in PLACES else "away"
    return out


def reply(control: dict[str, Any], language: str) -> str:
    action = control["action"]
    if action == "greet":
        return f"{GREETINGS.get(language, GREETINGS['en'])} What can I do for you?"
    if action == "stay":
        return "Okay, I'll stay until you say."
    if action == "go":
        return "Bye for now."
    where = control.get("where", "away")
    return "Okay, moving out of your way." if where == "away" else f"Okay, moving to the {where.replace('-', ' ')}."
