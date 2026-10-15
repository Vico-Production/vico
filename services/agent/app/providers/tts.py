"""Spoken replies, in the user's language, from free sources. Audio stays in memory.

- Gemini 3.8 TTS with the user's own Gemini key (free tier): English, Hausa and Igbo are on
  its language list (Flash-Lite TTS has no Igbo, so Igbo uses Flash TTS). Nigerian Pidgin is
  not listed: it is spoken with an English voice.
- Yorùbá is not on Gemini's TTS list: it needs YarnGPT on the user's own speech server.
- Offline English: the computer's own voice (Windows SAPI, or espeak-ng on Linux).
Source: https://ai.google.dev/gemini-api/docs/speech-generation (checked 2026-10-15).
"""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
import sys

GEMINI_TTS_MODEL = {
    "en": "gemini-3.8-flash-lite-tts",
    "pcm": "gemini-3.8-flash-lite-tts",
    "ha": "gemini-3.8-flash-lite-tts",
    "ig": "gemini-3.8-flash-tts",
}
GEMINI_VOICE = "Kore"
MAX_SPOKEN_CHARS = 220  # long answers: speak the first sentences; the rest stays on screen

_SAPI = (
    "[Console]::InputEncoding=[Text.Encoding]::UTF8;"
    "Add-Type -AssemblyName System.Speech;"
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "$m=New-Object System.IO.MemoryStream;"
    "$s.SetOutputToWaveStream($m);"
    "$s.Speak([Console]::In.ReadToEnd());"
    "[Console]::Out.Write([Convert]::ToBase64String($m.ToArray()))"
)


def spoken_part(text: str) -> str:
    """The first sentences of a reply, up to about MAX_SPOKEN_CHARS, cut at a sentence end."""
    text = " ".join(text.split())
    if len(text) <= MAX_SPOKEN_CHARS:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for sentence in sentences:
        if out and len(out) + len(sentence) + 1 > MAX_SPOKEN_CHARS:
            break
        out = f"{out} {sentence}".strip()
    return out if out else text[:MAX_SPOKEN_CHARS].rsplit(" ", 1)[0]


def system_voice(text: str) -> bytes | None:
    """English from the computer's own voice, as WAV bytes, or None if there is none.
    The text goes in on stdin and the audio comes back on stdout: nothing touches disk."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(  # noqa: S603 - fixed command, text passed on stdin
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SAPI],  # noqa: S607
                input=text.encode("utf-8"), capture_output=True, timeout=20, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return base64.b64decode(out.stdout) if out.returncode == 0 and out.stdout else None
        engine = shutil.which("espeak-ng") or shutil.which("espeak")
        if engine:
            out = subprocess.run([engine, "--stdin", "--stdout"], input=text.encode("utf-8"),  # noqa: S603
                                 capture_output=True, timeout=20, check=False)
            return out.stdout if out.returncode == 0 and out.stdout else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return None


def gemini_tts_body(text: str) -> dict:
    return {
        "model": "",  # filled in by the caller
        "input": [{"type": "user_input", "content": [{"type": "text", "text": text}]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": GEMINI_VOICE}]},
    }


def gemini_tts_audio(data: dict) -> bytes | None:
    """The WAV bytes from an Interactions API reply (steps[].content[] of type audio)."""
    audio = None
    for step in data.get("steps", []) if isinstance(data, dict) else []:
        if step.get("type") != "model_output":
            continue
        for part in step.get("content", []):
            if part.get("type") == "audio" and part.get("data"):
                audio = part["data"]
    return base64.b64decode(audio) if audio else None
