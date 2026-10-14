"""OS adapter interface. Tools call this instead of OS APIs so Windows, Linux and macOS
differ only here."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from app.contracts import ErrorCode, VicoError


@dataclass
class AppEntry:
    name: str
    target: str  # executable, shortcut, .desktop id or app bundle


@dataclass
class WindowInfo:
    title: str
    pid: int | None = None


def unsupported(what: str) -> VicoError:
    return VicoError(ErrorCode.UNSUPPORTED, f"{what} is not supported on this computer yet.", status=501)


class PlatformAdapter:
    name = "generic"

    # --- launching ---------------------------------------------------------------------
    def open_path(self, path: Path) -> None:
        raise unsupported("Opening files")

    def open_url(self, url: str) -> None:
        import webbrowser

        if not webbrowser.open(url):
            raise VicoError(ErrorCode.UNSUPPORTED, "No default web browser was found.")

    def builtin_apps(self) -> dict[str, list[str]]:
        return {}

    def discover_apps(self) -> list[AppEntry]:
        return []

    def find_apps(self, query: str) -> list[AppEntry]:
        q = query.strip().lower()
        entries = [AppEntry(name, cmd[0]) for name, cmd in self.builtin_apps().items()]
        entries += self.discover_apps()
        seen: set[str] = set()
        unique = []
        for e in entries:
            if e.name.lower() not in seen:
                seen.add(e.name.lower())
                unique.append(e)
        if not q:
            return sorted(unique, key=lambda e: e.name.lower())
        exact = [e for e in unique if e.name.lower() == q]
        starts = [e for e in unique if e.name.lower().startswith(q) and e not in exact]
        contains = [e for e in unique if q in e.name.lower() and e not in exact and e not in starts]
        return exact + starts + contains

    def launch_app(self, entry: AppEntry) -> int | None:
        builtin = self.builtin_apps().get(entry.name.lower())
        argv = builtin or [entry.target]
        if not shutil.which(argv[0]) and not Path(argv[0]).exists():
            raise VicoError(ErrorCode.NOT_FOUND, f"{entry.name} is not installed.", status=404)
        proc = subprocess.Popen(argv, **detached_kwargs())  # noqa: S603 - fixed argv, no shell
        return proc.pid

    # --- windows and input -------------------------------------------------------------
    def list_windows(self) -> list[WindowInfo]:
        raise unsupported("Listing windows")

    def focus_window(self, title: str) -> WindowInfo:
        raise unsupported("Switching windows")

    def type_text(self, text: str) -> None:
        raise unsupported("Typing into other apps")

    def press_keys(self, keys: str) -> None:
        raise unsupported("Pressing keys in other apps")

    def click_element(self, window: str, name: str) -> str:
        raise unsupported("Clicking buttons in other apps")

    def focused_is_secret(self) -> bool:
        return False

    # --- shell -------------------------------------------------------------------------
    def shell_argv(self, command: str, shell: str) -> list[str]:
        sh = shell if shell != "auto" else ("bash" if shutil.which("bash") else "sh")
        if sh not in ("bash", "sh"):
            raise unsupported(f"The {sh} shell")
        return [sh, "-c", command]

    def process_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def wait_for_window(self, needle: str, before: set[str], timeout: float = 6.0) -> str | None:
        """Wait for a new window whose title contains `needle`; returns the title or None."""
        deadline = time.monotonic() + timeout
        needle = needle.lower()
        while time.monotonic() < deadline:
            try:
                titles = [w.title for w in self.list_windows()]
            except VicoError:
                return None
            for title in titles:
                if title not in before and (needle in title.lower() or not needle):
                    return title
            for title in titles:
                if needle and needle in title.lower():
                    return title
            time.sleep(0.4)
        return None


def detached_kwargs() -> dict:
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0)
        return {"creationflags": flags, "close_fds": True,
                "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    return {"start_new_session": True, "close_fds": True,
            "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
