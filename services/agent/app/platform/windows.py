"""Windows adapter: Start Menu discovery, Win32 window enumeration, pywinauto input."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
from ctypes import wintypes
from pathlib import Path

from app.contracts import ErrorCode, VicoError
from app.platform.base import AppEntry, PlatformAdapter, ScreenRect, WindowInfo, detached_kwargs

APPS_FOLDER = "shell:AppsFolder\\"
CONSOLE_APPS = {"powershell.exe", "cmd.exe", "pwsh.exe"}
_PYWINAUTO_SPECIAL = set("+^%~(){}[]")
_KEY_NAMES = {
    "enter": "{ENTER}", "return": "{ENTER}", "tab": "{TAB}", "esc": "{ESC}", "escape": "{ESC}",
    "backspace": "{BACKSPACE}", "delete": "{DELETE}", "del": "{DELETE}", "space": "{SPACE}",
    "up": "{UP}", "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}", "home": "{HOME}",
    "end": "{END}", "pageup": "{PGUP}", "pagedown": "{PGDN}", "win": "{VK_LWIN}",
    **{f"f{i}": f"{{F{i}}}" for i in range(1, 13)},
}
_MODIFIERS = {"ctrl": "^", "control": "^", "shift": "+", "alt": "%"}


def to_pywinauto_keys(keys: str) -> str:
    """Convert 'ctrl+shift+s' style chords into pywinauto send_keys syntax."""
    parts = [p.strip().lower() for p in keys.replace(" ", "+").split("+") if p.strip()]
    if not parts:
        raise VicoError(ErrorCode.VALIDATION_ERROR, "No keys given.")
    mods = "".join(_MODIFIERS[p] for p in parts[:-1] if p in _MODIFIERS)
    unknown = [p for p in parts[:-1] if p not in _MODIFIERS]
    if unknown:
        raise VicoError(ErrorCode.VALIDATION_ERROR, f"Unknown modifier: {unknown[0]}")
    last = parts[-1]
    if last in _KEY_NAMES:
        key = _KEY_NAMES[last]
    elif len(last) == 1:
        key = "{" + last + "}" if last in _PYWINAUTO_SPECIAL else last
    else:
        raise VicoError(ErrorCode.VALIDATION_ERROR, f"Unknown key: {last}")
    return mods + key


def escape_for_send_keys(text: str) -> str:
    return "".join("{" + c + "}" if c in _PYWINAUTO_SPECIAL else c for c in text)


class WindowsAdapter(PlatformAdapter):
    name = "windows"

    def open_path(self, path: Path) -> None:
        os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606 - opens with the default app

    def builtin_apps(self) -> dict[str, list[str]]:
        apps = {
            "notepad": ["notepad.exe"],
            "calculator": ["calc.exe"],
            "paint": ["mspaint.exe"],
            "file explorer": ["explorer.exe"],
            "command prompt": ["cmd.exe"],
            "powershell": ["powershell.exe"],
            "task manager": ["taskmgr.exe"],
            "wordpad": ["write.exe"],
            "snipping tool": ["SnippingTool.exe"],
            "settings": ["explorer.exe", "ms-settings:"],
            "windows settings": ["explorer.exe", "ms-settings:"],
            "control panel": ["control.exe"],
        }
        code = shutil.which("code")
        if code:
            apps["vs code"] = [code]
            apps["visual studio code"] = [code]
        return apps

    def discover_apps(self) -> list[AppEntry]:
        """Every app the Start menu lists (Store/MSIX apps such as Claude and WhatsApp included),
        plus shortcut files, which also cover older installers."""
        entries = self._start_apps()
        roots = [
            Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        ]
        for root in roots:
            if not root.is_dir():
                continue
            for lnk in root.rglob("*.lnk"):
                name = lnk.stem
                if any(w in name.lower() for w in ("uninstall", "readme", "help", "website")):
                    continue
                entries.append(AppEntry(name=name, target=str(lnk)))
        return entries

    @staticmethod
    def _start_apps() -> list[AppEntry]:
        """Windows' own list of installed apps (Get-StartApps): name and AppUserModelID."""
        script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                  "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress")
        try:
            out = subprocess.run(  # noqa: S603 - fixed command
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],  # noqa: S607
                capture_output=True, timeout=20, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            data = json.loads(out.stdout.decode("utf-8", errors="replace") or "[]")
        except (OSError, subprocess.SubprocessError, ValueError):
            return []
        if isinstance(data, dict):
            data = [data]
        apps = []
        for item in data if isinstance(data, list) else []:
            name, app_id = item.get("Name"), item.get("AppID")
            if not name or not app_id or any(w in name.lower() for w in ("uninstall", "readme", "help")):
                continue
            apps.append(AppEntry(name=name, target=f"{APPS_FOLDER}{app_id}"))
        return apps

    def launch_app(self, entry: AppEntry) -> int | None:
        builtin = self.builtin_apps().get(entry.name.lower())
        if builtin:
            if Path(builtin[0]).name.lower() in CONSOLE_APPS:
                # The user asked to open PowerShell or Command Prompt: give it its own window.
                proc = subprocess.Popen(builtin, creationflags=subprocess.CREATE_NEW_CONSOLE,  # type: ignore[attr-defined]  # noqa: S603
                                        close_fds=True)
            else:
                proc = subprocess.Popen(builtin, **detached_kwargs())  # noqa: S603 - fixed argv
            return proc.pid
        if entry.target.startswith(APPS_FOLDER):
            # Store and desktop apps alike start through the shell by their app ID.
            subprocess.Popen(["explorer.exe", entry.target], **detached_kwargs())  # noqa: S603 S607
            return None
        target = Path(entry.target)
        if target.suffix.lower() == ".lnk" and target.exists():
            os.startfile(str(target))  # type: ignore[attr-defined]  # noqa: S606 - Start Menu shortcut
            return None
        raise VicoError(ErrorCode.NOT_FOUND, f"{entry.name} is not installed.", status=404)

    # --- windows ----------------------------------------------------------------------
    def list_windows(self) -> list[WindowInfo]:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        results: list[WindowInfo] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)  # type: ignore[attr-defined]
        def callback(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    title = buf.value.strip()
                    if title and title not in ("Program Manager",):
                        results.append(WindowInfo(title=title, pid=pid.value))
            return True

        user32.EnumWindows(callback, 0)
        return results

    def _find_window(self, title: str):
        from pywinauto import Desktop

        needle = title.lower()
        for win in Desktop(backend="uia").windows():
            text = win.window_text()
            if text and needle in text.lower():
                return win
        raise VicoError(ErrorCode.NOT_FOUND, f"No open window matches '{title}'.", status=404)

    def focus_window(self, title: str) -> WindowInfo:
        win = self._find_window(title)
        if win.is_minimized():
            win.restore()
        win.set_focus()
        return WindowInfo(title=win.window_text(), pid=win.process_id())

    def type_text(self, text: str) -> None:
        from pywinauto.keyboard import send_keys

        send_keys(escape_for_send_keys(text), with_spaces=True, with_newlines=True, pause=0.01)

    def press_keys(self, keys: str) -> None:
        from pywinauto.keyboard import send_keys

        send_keys(to_pywinauto_keys(keys))

    def _find_control(self, window: str, name: str):
        win = self._find_window(window)
        needle = name.lower()
        for ctrl in win.descendants():
            try:
                text = ctrl.window_text()
            except Exception:  # noqa: S112 - controls can vanish mid-enumeration
                continue
            if text and needle in text.lower() and ctrl.is_visible() and ctrl.is_enabled():
                return ctrl, text
        raise VicoError(ErrorCode.NOT_FOUND, f"No control named '{name}' in '{window}'.", status=404)

    def click_element(self, window: str, name: str) -> str:
        ctrl, text = self._find_control(window, name)
        ctrl.click_input()
        return text

    @staticmethod
    def _rect(r) -> ScreenRect | None:
        width, height = int(r.right - r.left), int(r.bottom - r.top)
        return (int(r.left), int(r.top), width, height) if width > 0 and height > 0 else None

    def window_rect(self, title: str) -> ScreenRect | None:
        try:
            return self._rect(self._find_window(title).rectangle())
        except Exception:
            return None

    def element_rect(self, window: str, name: str) -> ScreenRect | None:
        try:
            ctrl, _ = self._find_control(window, name)
            return self._rect(ctrl.rectangle())
        except Exception:
            return None

    def focus_rect(self) -> ScreenRect | None:
        try:
            from pywinauto.uia_defines import IUIA

            rect = self._rect(IUIA().iuia.GetFocusedElement().CurrentBoundingRectangle)
            if rect:
                return rect
        except Exception:  # noqa: S110 - fall back to the active window
            pass
        try:
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            box = wintypes.RECT()
            if user32.GetWindowRect(user32.GetForegroundWindow(), ctypes.byref(box)):
                return self._rect(box)
        except Exception:  # noqa: S110 - unknown is a valid answer
            pass
        return None

    def focused_is_secret(self) -> bool:
        try:
            from pywinauto.uia_defines import IUIA

            focused = IUIA().iuia.GetFocusedElement()
            return bool(focused.CurrentIsPassword)
        except Exception:
            return False

    # --- shell ------------------------------------------------------------------------
    def shell_argv(self, command: str, shell: str) -> list[str]:
        if shell in ("auto", "powershell"):
            return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
        if shell == "cmd":
            return ["cmd.exe", "/d", "/s", "/c", command]
        bash = shutil.which("bash")
        if bash:
            return [bash, "-c", command]
        raise VicoError(ErrorCode.UNSUPPORTED, "bash is not installed on this computer.")

    def process_alive(self, pid: int) -> bool:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
