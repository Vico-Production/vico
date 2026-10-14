"""Process-level paths and constants."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Vico"
VERSION = "0.1.0"

MAX_RECORDING_SECONDS = 15
MAX_TEXT_INPUT_CHARS = 2000
READ_TEXT_MAX_BYTES = 100_000
SUMMARY_MAX_CHARS = 12_000
APPROVAL_TIMEOUT_S = 300
TOOL_TIMEOUT_S = 30
COMMAND_TIMEOUT_S = 60
DEFAULT_MAX_STEPS = 12
MAX_CLARIFICATIONS = 3


def data_dir() -> Path:
    override = os.environ.get("VICO_DATA_DIR")
    if override:
        path = Path(override)
    elif sys.platform == "win32":
        path = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "vico"
    path.mkdir(parents=True, exist_ok=True)
    return path


def temp_audio_dir() -> Path:
    path = data_dir() / "tmp_audio"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_workspace() -> Path:
    return Path.home() / "Documents" / "VicoDemo"
