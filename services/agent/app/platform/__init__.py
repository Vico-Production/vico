from __future__ import annotations

import sys

from app.platform.base import PlatformAdapter


def get_platform() -> PlatformAdapter:
    if sys.platform == "win32":
        from app.platform.windows import WindowsAdapter

        return WindowsAdapter()
    if sys.platform == "darwin":
        from app.platform.darwin import MacAdapter

        return MacAdapter()
    from app.platform.linux import LinuxAdapter

    return LinuxAdapter()
