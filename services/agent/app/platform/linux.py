"""Linux adapter: xdg-open, .desktop discovery, wmctrl/xdotool on X11.

Wayland does not allow one app to type into or focus another, so desktop input is
reported as unsupported there. Files, apps, shell and browser tools still work.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from app.contracts import ErrorCode, VicoError
from app.platform.base import AppEntry, PlatformAdapter, WindowInfo, detached_kwargs, unsupported

WAYLAND_HELP = ("On Ubuntu's Wayland desktop, apps may not type or press keys in other apps. Either choose "
                "'Ubuntu on Xorg' on the login screen (gear icon), or install ydotool: sudo apt install ydotool")
# Linux input event codes for ydotool ("29:1 46:1 46:0 29:0" is ctrl+c).
_EVDEV = {"ctrl": 29, "control": 29, "shift": 42, "alt": 56, "super": 125, "win": 125, "enter": 28, "return": 28,
          "tab": 15, "esc": 1, "escape": 1, "backspace": 14, "delete": 111, "space": 57, "up": 103, "down": 108,
          "left": 105, "right": 106, "home": 102, "end": 107, "pageup": 104, "pagedown": 109,
          **{c: n for c, n in zip("1234567890", range(2, 12), strict=True)},
          **dict(zip("qwertyuiop", range(16, 26), strict=True)), **dict(zip("asdfghjkl", range(30, 39), strict=True)),
          **dict(zip("zxcvbnm", range(44, 51), strict=True)),
          **{f"f{i}": 58 + i for i in range(1, 11)}, "f11": 87, "f12": 88}


def ydotool_keys(keys: str) -> list[str]:
    parts = [p.strip().lower() for p in keys.replace(" ", "+").split("+") if p.strip()]
    codes = []
    for p in parts:
        if p not in _EVDEV:
            raise VicoError(ErrorCode.VALIDATION_ERROR, f"Unknown key: {p}")
        codes.append(_EVDEV[p])
    return [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]


_FIELD_CODES = {"%f", "%F", "%u", "%U", "%d", "%D", "%n", "%N", "%i", "%c", "%k", "%v", "%m"}


def parse_desktop_file(path: Path) -> AppEntry | None:
    name = exec_line = None
    in_entry = hidden = False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if line.startswith("["):
            in_entry = line == "[Desktop Entry]"
            continue
        if not in_entry or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == "Name" and name is None:
            name = value
        elif key == "Exec":
            exec_line = value
        elif key in ("NoDisplay", "Hidden") and value.lower() == "true":
            hidden = True
        elif key == "Type" and value != "Application":
            return None
    if not name or not exec_line or hidden:
        return None
    return AppEntry(name=name, target=exec_line)


def exec_argv(exec_line: str) -> list[str]:
    return [a for a in shlex.split(exec_line) if a not in _FIELD_CODES]


class LinuxAdapter(PlatformAdapter):
    name = "linux"

    @property
    def x11(self) -> bool:
        return bool(os.environ.get("DISPLAY")) and os.environ.get("XDG_SESSION_TYPE") != "wayland"

    def _run(self, argv: list[str], timeout: float = 10) -> str:
        if not shutil.which(argv[0]):
            raise VicoError(ErrorCode.UNSUPPORTED, f"{argv[0]} is not installed. Install it to use this.")
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
        if out.returncode != 0:
            raise VicoError(ErrorCode.INTERNAL, out.stderr.strip() or f"{argv[0]} failed")
        return out.stdout

    def open_path(self, path: Path) -> None:
        subprocess.Popen(["xdg-open", str(path)], **detached_kwargs())  # noqa: S603 S607

    def builtin_apps(self) -> dict[str, list[str]]:
        apps: dict[str, list[str]] = {}
        for name, candidates in {
            "text editor": ["gnome-text-editor", "gedit", "kate", "mousepad", "xed"],
            "calculator": ["gnome-calculator", "kcalc", "galculator"],
            "file manager": ["nautilus", "dolphin", "thunar", "nemo"],
            "terminal": ["gnome-terminal", "konsole", "xfce4-terminal", "x-terminal-emulator"],
            "vs code": ["code"],
            "settings": ["gnome-control-center", "systemsettings", "xfce4-settings-manager", "cinnamon-settings"],
        }.items():
            found = next((c for c in candidates if shutil.which(c)), None)
            if found:
                apps[name] = [found]
        if "text editor" in apps:
            apps["notepad"] = apps["text editor"]
        return apps

    def discover_apps(self) -> list[AppEntry]:
        """Every app with a launcher: system and user .desktop files, snaps and flatpaks."""
        data_dirs = [Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))]
        data_dirs += [Path(p) for p in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if p]
        data_dirs += [Path("/var/lib/snapd/desktop"), Path("/var/lib/flatpak/exports/share"),
                      Path.home() / ".local/share/flatpak/exports/share"]
        entries, seen = [], set()
        for base in data_dirs:
            d = base / "applications"
            if not d.is_dir() or d in seen:
                continue
            seen.add(d)
            for f in d.rglob("*.desktop"):
                entry = parse_desktop_file(f)
                if entry:
                    entries.append(AppEntry(name=entry.name, target=entry.target, desktop_id=f.name))
        return entries

    def launch_app(self, entry: AppEntry) -> int | None:
        builtin = self.builtin_apps().get(entry.name.lower())
        if not builtin and entry.desktop_id and shutil.which("gtk-launch"):
            # Exactly as the app menu starts it (snaps, flatpaks and wrappers included).
            return subprocess.Popen(["gtk-launch", entry.desktop_id.removesuffix(".desktop")],  # noqa: S603 S607
                                    **detached_kwargs()).pid
        argv = builtin or exec_argv(entry.target)
        if not argv or not (shutil.which(argv[0]) or Path(argv[0]).exists()):
            raise VicoError(ErrorCode.NOT_FOUND, f"{entry.name} is not installed.", status=404)
        return subprocess.Popen(argv, **detached_kwargs()).pid  # noqa: S603 - argv from .desktop entry

    def list_windows(self) -> list[WindowInfo]:
        if not self.x11:
            raise unsupported("Listing windows on Wayland")
        windows = []
        for line in self._run(["wmctrl", "-lp"]).splitlines():
            parts = line.split(None, 4)
            if len(parts) == 5:
                windows.append(WindowInfo(title=parts[4], pid=int(parts[2]) if parts[2].isdigit() else None))
        return windows

    def focus_window(self, title: str) -> WindowInfo:
        match = next((w for w in self.list_windows() if title.lower() in w.title.lower()), None)
        if not match:
            raise VicoError(ErrorCode.NOT_FOUND, f"No open window matches '{title}'.", status=404)
        self._run(["wmctrl", "-a", match.title])
        return match

    def _geometry(self, args: list[str]):
        if not self.x11 or not shutil.which("xdotool"):
            return None
        try:
            text = self._run(["xdotool", *args, "getwindowgeometry", "--shell"], timeout=2)
        except Exception:
            return None
        values = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
        try:
            rect = (int(values["X"]), int(values["Y"]), int(values["WIDTH"]), int(values["HEIGHT"]))
        except (KeyError, ValueError):
            return None
        return rect if rect[2] > 0 and rect[3] > 0 else None

    def window_rect(self, title: str):
        return self._geometry(["search", "--onlyvisible", "--limit", "1", "--name", title])

    def focus_rect(self):
        return self._geometry(["getactivewindow"])

    def type_text(self, text: str) -> None:
        if not self.x11:
            if shutil.which("ydotool"):
                self._run(["ydotool", "type", "--", text], timeout=60)
                return
            raise VicoError(ErrorCode.UNSUPPORTED, WAYLAND_HELP)
        self._run(["xdotool", "type", "--delay", "15", "--", text], timeout=60)

    def press_keys(self, keys: str) -> None:
        if not self.x11:
            if shutil.which("ydotool"):
                self._run(["ydotool", "key", *ydotool_keys(keys)])
                return
            raise VicoError(ErrorCode.UNSUPPORTED, WAYLAND_HELP)
        chord = "+".join(p.strip() for p in keys.replace(" ", "+").split("+") if p.strip())
        chord = chord.replace("enter", "Return").replace("esc", "Escape")
        self._run(["xdotool", "key", "--", chord])
