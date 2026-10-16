"""Hard-limit guards: payments, passwords/card details, and outward sends.

These are best-effort content checks applied regardless of the approval switch. They
are a backstop to the approval step, not a guarantee.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

_PAYMENT_WORDS = re.compile(
    r"\b(pay|pay now|payment|purchase|buy now|buy|place order|complete order|checkout|check out|"
    r"confirm payment|confirm order|donate|add card|add payment|transfer|send money|"
    r"top up|withdraw|start (?:free )?trial|start (?:my |your )?subscription|upgrade (?:now|to)|"
    r"subscribe (?:now|for|to (?:premium|plus|pro|a plan))|join (?:premium|plus|membership))\b"
    # A plain "Subscribe" (YouTube, newsletters) is free; one with a price on it is a payment.
    r"|\bsubscribe\b.*(?:[$€£₦]|\d+(?:[.,]\d+)?\s*(?:/|per|a)\s*(?:mo|month|year|yr|week))",
    re.IGNORECASE,
)
_SEND_WORDS = re.compile(
    r"\b(send|post|submit|publish|tweet|reply|share|comment|upload|email|message|sign up|register|"
    r"apply|book|reserve)\b",
    re.IGNORECASE,
)
_SECRET_FIELD_HINTS = re.compile(
    r"(passw|passwd|pwd|\bpin\b|\botp\b|one[-_ ]?time|cvv|cvc|csc|card|cc[-_]?num|security[-_ ]?code|"
    r"expir|iban|routing|account[-_ ]?number|ssn|bvn|nin\b)",
    re.IGNORECASE,
)
_SECRET_AUTOCOMPLETE = {
    "current-password", "new-password", "one-time-code", "cc-number", "cc-csc", "cc-exp",
    "cc-exp-month", "cc-exp-year", "cc-name", "cc-type", "transaction-amount",
}
_DIGITS = re.compile(r"(?:\d[ -]?){12,19}\d")


def luhn_valid(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def contains_card_number(text: str) -> bool:
    return any(luhn_valid(m.group(0)) for m in _DIGITS.finditer(text))


def is_payment_action(label: str) -> bool:
    return bool(label and _PAYMENT_WORDS.search(label))


def is_send_action(label: str) -> bool:
    return bool(label and _SEND_WORDS.search(label))


def is_secret_field(attrs: Mapping[str, str | None]) -> bool:
    """True when a form field looks like a password, PIN or payment-card field."""
    field_type = (attrs.get("type") or "").lower()
    if field_type == "password":
        return True
    autocomplete = (attrs.get("autocomplete") or "").lower().split()
    if any(token in _SECRET_AUTOCOMPLETE for token in autocomplete):
        return True
    hints = " ".join(
        attrs.get(k) or "" for k in ("name", "id", "placeholder", "aria-label", "label")
    )
    return bool(_SECRET_FIELD_HINTS.search(hints))


def payment_or_secret_reason(text: str) -> str | None:
    """Reason to block typing `text`, or None."""
    if contains_card_number(text):
        return "This looks like a payment card number. Vico never types card details."
    return None
