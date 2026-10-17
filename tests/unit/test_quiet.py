import subprocess
import sys

import pytest

from app.platform.quiet import CREATE_NEW_CONSOLE, CREATE_NO_WINDOW, DETACHED_PROCESS, hidden_flags, install


def test_background_helpers_get_no_window_but_opened_apps_keep_theirs():
    assert hidden_flags(0) & CREATE_NO_WINDOW
    assert hidden_flags(0x200) & CREATE_NO_WINDOW  # a new process group still hides
    assert hidden_flags(CREATE_NEW_CONSOLE) == CREATE_NEW_CONSOLE  # "open PowerShell": visible
    assert hidden_flags(DETACHED_PROCESS) == DETACHED_PROCESS


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_powershell_runs_without_a_window():
    install()
    out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", "Write-Output ok"], capture_output=True,
                         text=True, check=False)
    assert out.stdout.strip() == "ok"
