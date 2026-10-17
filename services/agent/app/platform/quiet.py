"""No flashing windows: every helper program Vico runs in the background on Windows (PowerShell
for the app list, volume, brightness, voice; commands the user asked for) runs without a
visible console window, so whatever the user is doing is never interrupted.

Programs the user asks to *open* (Notepad, PowerShell, Command Prompt) still appear normally:
they are started with their own window on purpose (CREATE_NEW_CONSOLE / DETACHED_PROCESS).
"""

from __future__ import annotations

import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_CONSOLE = 0x00000010
_installed = False


def hidden_flags(flags: int) -> int:
    """Add "no window" unless the program was deliberately given its own window."""
    if flags & (CREATE_NEW_CONSOLE | DETACHED_PROCESS):
        return flags
    return flags | CREATE_NO_WINDOW


def install() -> None:
    global _installed
    if sys.platform != "win32" or _installed:
        return
    original = subprocess.Popen.__init__

    def quiet_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if len(args) < 13:  # creationflags given by name (Vico always does)
            kwargs["creationflags"] = hidden_flags(int(kwargs.get("creationflags", 0) or 0))
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = quiet_init  # type: ignore[method-assign]
    _installed = True
