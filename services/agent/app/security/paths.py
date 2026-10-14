"""Canonical path resolution and root-bound guards.

Every filesystem tool resolves user or model supplied paths through `PathPolicy` so
traversal, symlink escapes, device paths and writes into system folders are rejected
in one place.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from app.contracts import ErrorCode, VicoError

MAX_PATH_CHARS = 400

WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".log", ".xml", ".html", ".htm",
    ".yaml", ".yml", ".ini", ".toml", ".py", ".js", ".ts", ".css", ".rst",
}

EXECUTABLE_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".com", ".msi", ".msp", ".ps1", ".psm1", ".vbs", ".vbe",
    ".jse", ".wsf", ".wsh", ".scr", ".lnk", ".reg", ".sh", ".bash", ".appimage", ".jar",
    ".dll", ".cpl", ".hta", ".msc", ".pif", ".run", ".bin", ".deb", ".rpm", ".desktop",
}

NOTE_EXTENSIONS = {".txt", ".md"}

_URL_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]+://")
_DRIVE = re.compile(r"^[a-zA-Z]:")


def _deny(message: str) -> VicoError:
    return VicoError(ErrorCode.POLICY_DENIED, message, status=403)


def check_raw_path(raw: str) -> str:
    """Reject path strings that are dangerous before they touch the filesystem."""
    if not isinstance(raw, str) or not raw.strip():
        raise _deny("A path is required.")
    if len(raw) > MAX_PATH_CHARS:
        raise _deny("That path is too long.")
    if "\x00" in raw or any(ord(c) < 32 for c in raw):
        raise _deny("That path contains control characters.")
    if _URL_SCHEME.match(raw) or raw.lower().startswith(("file:", "http:", "https:")):
        raise _deny("URLs are not file paths. Use a browser tool for web addresses.")
    normalized = raw.replace("\\", "/")
    if normalized.startswith("//") or normalized.startswith("/?/") or normalized.startswith("/./"):
        raise _deny("Network and device paths are not allowed.")
    rest = normalized[2:] if _DRIVE.match(normalized) else normalized
    if ":" in rest:
        raise _deny("Alternate data streams and drive-relative paths are not allowed.")
    for part in normalized.split("/"):
        if not part or part in (".", "..", "~"):
            continue
        stem = part.split(".")[0].strip().lower()
        if stem in WINDOWS_RESERVED:
            raise _deny(f"'{part}' is a reserved Windows device name.")
        if part != part.rstrip(" ."):
            raise _deny(f"'{part}' ends with a space or dot, which Windows cannot store safely.")
    return normalized


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def protected_roots() -> list[Path]:
    roots: list[Path] = []
    if sys.platform == "win32":
        for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
            value = os.environ.get(var)
            if value:
                roots.append(Path(value))
    else:
        for value in ("/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/proc", "/sbin",
                      "/sys", "/usr", "/var", "/opt", "/System", "/Library"):
            roots.append(Path(value))
    return [_safe_resolve(r) for r in roots]


def _safe_resolve(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return Path(os.path.abspath(path))


class PathPolicy:
    def __init__(self, workspace: Path, allowed_roots: Iterable[Path], extra_protected: Iterable[Path] = ()):
        self.workspace = _safe_resolve(Path(workspace).expanduser())
        roots = [_safe_resolve(Path(r).expanduser()) for r in allowed_roots]
        if not any(_is_within(self.workspace, r) for r in roots):
            roots.append(self.workspace)
        self.allowed_roots = roots
        self.protected = protected_roots() + [_safe_resolve(Path(p)) for p in extra_protected]

    def resolve(self, raw: str) -> Path:
        """Resolve a user/model path to a canonical path inside an allowed root."""
        normalized = check_raw_path(raw)
        if normalized == "~" or normalized.startswith("~/"):
            candidate = Path.home() / normalized[2:]
        elif Path(normalized).is_absolute() or _DRIVE.match(normalized):
            candidate = Path(normalized)
        else:
            candidate = self.workspace / normalized
        resolved = _safe_resolve(candidate)
        if not any(_is_within(resolved, root) for root in self.allowed_roots):
            raise _deny(
                f"'{raw}' is outside the folders Vico may use. Allowed: "
                + ", ".join(str(r) for r in self.allowed_roots)
            )
        return resolved

    def resolve_for_write(self, raw: str) -> Path:
        path = self.resolve(raw)
        for root in self.protected:
            if _is_within(path, root):
                raise _deny(f"Vico will not change files inside the protected folder {root}.")
        if path in self.allowed_roots:
            raise _deny("Vico will not replace or remove an allowed root folder itself.")
        return path

    def display(self, path: Path) -> str:
        home = _safe_resolve(Path.home())
        if _is_within(path, home):
            rel = path.relative_to(home)
            return "~" if str(rel) == "." else f"~{os.sep}{rel}"
        return str(path)


_FILENAME_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Make a safe single filename component, preserving Unicode letters and diacritics."""
    cleaned = _FILENAME_BAD.sub("_", name).strip().rstrip(". ")
    cleaned = re.sub(r"\s+", " ", cleaned)[:max_len].rstrip(". ")
    if not cleaned:
        cleaned = "note"
    if cleaned.split(".")[0].lower() in WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned


def is_executable(path: Path) -> bool:
    return path.suffix.lower() in EXECUTABLE_EXTENSIONS


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS
