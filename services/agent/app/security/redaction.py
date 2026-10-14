"""Redaction for logs, history and error messages."""

from __future__ import annotations

import re
from typing import Any

_SECRET_PATTERNS = [
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),           # Groq
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),         # Google
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),          # generic OpenAI-style
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[=:]\s*)\S+"),
]
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")

SENSITIVE_ARG_KEYS = {"content", "text", "command"}
MAX_ARG_PREVIEW = 80


def redact_text(text: str) -> str:
    out = text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            out = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", out)
        else:
            out = pattern.sub("[redacted]", out)
    return _CARD.sub("[redacted-number]", out)


def redact_args(args: dict[str, Any]) -> dict[str, Any]:
    """Summarize arguments for logs/history: long or sensitive values are truncated."""
    result: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            value = redact_text(value)
            if key in SENSITIVE_ARG_KEYS and len(value) > MAX_ARG_PREVIEW:
                value = value[:MAX_ARG_PREVIEW] + f"... ({len(value)} chars)"
        result[key] = value
    return result
