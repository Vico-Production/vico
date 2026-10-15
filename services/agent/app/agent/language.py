"""Cheap local language guess, so plain English requests never spend a cloud call on detection.

Returns a language code when the evidence is clear, or None to let the cloud decide.
"""

from __future__ import annotations

import re
import unicodedata

_HAUSA = set("ɓɗƙƴƁƊƘƳ")
_YORUBA_ONLY = set("ẹẸṣṢ")
_IGBO_ONLY = set("ịỊụỤṅṄ")

_ENGLISH = set("""
a about after all also an and any app apps are as ask at back be bring browser but by can cancel change check
chrome click close code computer copy create delete desktop do document documents does download downloads drive
edge email file files find first folder folders for from get go google help how i in into is it its last let list
make me media menu move music my name named new next not note notes notepad now of off on open or page photos
play please put read rename run save say screen search see send set settings show site so start stop tab terminal
text that the then this to type up use video volume what when where which window windows with word write you
youtube your called inside top new turn calculator paint explorer vs studio claude prompt tell it's them those
""".split())
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def guess_language(text: str) -> str | None:
    letters = set(unicodedata.normalize("NFC", text))
    if letters & _HAUSA:
        return "ha"
    if letters & _YORUBA_ONLY:
        return "yo"
    if letters & _IGBO_ONLY:
        return "ig"
    words = [w.lower() for w in _WORD.findall(text)]
    if not words:
        return "en"
    if any(ord(c) > 127 for w in words for c in w):
        return None  # tone marks or other non-English letters: let the cloud decide
    known = sum(w in _ENGLISH for w in words)
    return "en" if known / len(words) >= 0.6 else None
