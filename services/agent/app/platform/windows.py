"""Windows adapter: Start Menu discovery, Win32 window enumeration, pywinauto input."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
from ctypes import wintypes
from pathlib import Path

from app.contracts import ErrorCode, VicoError
from app.platform.base import AppEntry, PlatformAdapter, WindowInfo, detached_kwargs

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
        }
        code = shutil.which("code")
        if code:
            apps["vs code"] = [code]
            apps["visual studio code"] = [code]
        return apps

    def discover_apps(self) -> list[AppEntry]:
        roots = [
            Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        ]
        entries: list[AppEntry] = []
        for root in roots:
            if not root.is_dir():
                continue
            for lnk in root.rglob("*.lnk"):
                name = lnk.stem
                if any(w in name.lower() for w in ("uninstall", "readme", "help", "website")):
                    continue
                entries.append(AppEntry(name=name, target=str(lnk)))
        return entries

    def launch_app(self, entry: AppEntry) -> int | None:
        builtin = self.builtin_apps().get(entry.name.lower())
        if builtin:
            proc = subprocess.Popen(builtin, **detached_kwargs())  # noqa: S603 - fixed argv
            return proc.pid
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

    def click_element(self, window: str, name: str) -> str:
        win = self._find_window(window)
        needle = name.lower()
        for ctrl in win.descendants():
            try:
                text = ctrl.window_text()
            except Exception:  # noqa: S112 - controls can vanish mid-enumeration
                continue
            if text and needle in text.lower() and ctrl.is_visible() and ctrl.is_enabled():
                ctrl.click_input()
                return text
        raise VicoError(ErrorCode.NOT_FOUND, f"No control named '{name}' in '{window}'.", status=404)

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
