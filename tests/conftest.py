"""Shared fixtures for the Python test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "agent"))

from app.platform.base import AppEntry, PlatformAdapter, WindowInfo  # noqa: E402
from app.security.paths import PathPolicy  # noqa: E402
from app.store.settings import Settings  # noqa: E402
from app.tools.base import ToolContext  # noqa: E402

TOKEN = "test-token-0123456789abcdef"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    data = tmp_path / "appdata"
    data.mkdir()
    monkeypatch.setenv("VICO_DATA_DIR", str(data))
    for name in ("GROQ", "GEMINI"):
        monkeypatch.delenv(f"VICO_{name}_API_KEY", raising=False)
    # Offline voices are never downloaded or run in tests (tests that want them patch them in).
    import app.providers.kokoro as kokoro
    import app.providers.piper_voice as piper_voice

    monkeypatch.setattr(kokoro, "speak", lambda text: None)
    monkeypatch.setattr(kokoro, "prepare_in_background", lambda: None)
    monkeypatch.setattr(piper_voice, "speak", lambda text: None)
    return data


class FakePlatform(PlatformAdapter):
    name = "fake"

    def __init__(self) -> None:
        self.opened: list[Path] = []
        self.urls: list[str] = []
        self.launched: list[str] = []
        self.typed: list[str] = []
        self.keys: list[str] = []
        self.windows = [WindowInfo("Existing window", 1)]
        self.secret_focus = False

    def open_path(self, path: Path) -> None:
        self.opened.append(path)
        self.windows.append(WindowInfo(f"{path.stem} - Viewer", 99))

    def open_url(self, url: str) -> None:
        self.urls.append(url)

    def builtin_apps(self) -> dict[str, list[str]]:
        return {"notepad": ["notepad.exe"], "calculator": ["calc.exe"]}

    def launch_app(self, entry: AppEntry) -> int | None:
        self.launched.append(entry.name)
        self.windows.append(WindowInfo(f"Untitled - {entry.name.title()}", 42))
        return 42

    def list_windows(self) -> list[WindowInfo]:
        return list(self.windows)

    def wait_for_window(self, needle: str, before: set[str], timeout: float = 0.1) -> str | None:
        return super().wait_for_window(needle, before, timeout=0.1)

    def focus_window(self, title: str) -> WindowInfo:
        return next(w for w in self.windows if title.lower() in w.title.lower())

    def type_text(self, text: str) -> None:
        self.typed.append(text)

    def press_keys(self, keys: str) -> None:
        self.keys.append(keys)

    def focused_is_secret(self) -> bool:
        return self.secret_focus

    def process_alive(self, pid: int) -> bool:
        return True


@pytest.fixture
def platform() -> FakePlatform:
    return FakePlatform()


@pytest.fixture
def roots(tmp_path) -> tuple[Path, Path]:
    root = tmp_path / "home"
    workspace = root / "VicoDemo"
    workspace.mkdir(parents=True)
    return root, workspace


@pytest.fixture
def settings(roots) -> Settings:
    root, workspace = roots
    return Settings(workspace=str(workspace), allowed_roots=[str(root)], cloud_consent=True)


@pytest.fixture
def ctx(settings, platform, roots) -> ToolContext:
    root, workspace = roots
    return ToolContext(settings=settings, paths=PathPolicy(workspace, [root]), platform=platform)
