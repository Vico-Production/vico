"""Minimal macOS adapter. Full macOS support is planned after Windows and Linux."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.platform.base import AppEntry, PlatformAdapter, detached_kwargs


class MacAdapter(PlatformAdapter):
    name = "macos"

    def open_path(self, path: Path) -> None:
        subprocess.Popen(["open", str(path)], **detached_kwargs())  # noqa: S603 S607

    def discover_apps(self) -> list[AppEntry]:
        entries = []
        for root in (Path("/Applications"), Path.home() / "Applications"):
            if root.is_dir():
                entries += [AppEntry(name=p.stem, target=str(p)) for p in root.glob("*.app")]
        return entries

    def launch_app(self, entry: AppEntry) -> int | None:
        return subprocess.Popen(["open", "-a", entry.target], **detached_kwargs()).pid  # noqa: S603 S607
