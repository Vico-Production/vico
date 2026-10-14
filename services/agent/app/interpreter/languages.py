"""Honest per-language capability labels.

Labels start as 'untested' and change only when measured results exist in
`language_results.json` (written by scripts/benchmark_languages.py).
"""

from __future__ import annotations

import json
from typing import Any

from app.config import data_dir
from app.contracts import LANGUAGE_NAMES, Language

DEFAULT_NOTES = {
    Language.EN: "",
    Language.YO: "",
    Language.HA: "",
    Language.IG: "Igbo is not in Whisper's language list; Groq speech uses auto-detect. Gemini may do better.",
    Language.PCM: "Experimental. Written forms vary.",
}


def _results() -> dict[str, Any]:
    path = data_dir() / "language_results.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def capabilities() -> list[dict[str, Any]]:
    measured = _results()
    out = []
    for lang in Language:
        m = measured.get(lang.value, {})
        text = m.get("text", {})
        speech = m.get("speech", {})
        out.append({
            "code": lang.value,
            "name": LANGUAGE_NAMES[lang],
            "text_label": "tested" if text.get("samples") else "untested",
            "text_accuracy": text.get("intent_accuracy"),
            "speech_label": _speech_label(speech),
            "speech_accuracy": speech.get("intent_accuracy"),
            "samples": {"text": text.get("samples", 0), "speech": speech.get("samples", 0)},
            "note": DEFAULT_NOTES.get(lang, ""),
            "experimental": lang is Language.PCM,
        })
    return out


def _speech_label(speech: dict[str, Any]) -> str:
    samples = speech.get("samples", 0)
    accuracy = speech.get("intent_accuracy")
    if not samples or accuracy is None:
        return "untested"
    if samples >= 5 and accuracy >= 0.8:
        return "beta"
    return "unreliable"
