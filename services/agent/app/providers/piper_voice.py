"""Piper, if the user installed it themselves (it is GPL-3.0, so Vico does not ship it).

Vico runs the `piper` program like any other program on the computer, with a voice model the
user downloaded into Vico's models/piper folder or Piper's usual voices folder.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.config import data_dir

SEARCH = [lambda: data_dir() / "models" / "piper", lambda: Path.home() / ".local/share/piper-voices",
          lambda: Path.home() / "piper-voices"]


def find() -> tuple[str, Path] | None:
    exe = shutil.which("piper")
    if not exe:
        return None
    for where in SEARCH:
        folder = where()
        voices = sorted(folder.glob("en_*.onnx")) if folder.is_dir() else []
        if voices:
            return exe, voices[0]
    return None


def speak(text: str) -> bytes | None:
    found = find()
    if not found:
        return None
    exe, model = found
    try:
        out = subprocess.run([exe, "--model", str(model), "--output_file", "-"], input=text.encode("utf-8"),  # noqa: S603
                             capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 and out.stdout.startswith(b"RIFF") else None
