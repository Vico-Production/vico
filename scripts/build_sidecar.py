"""Package the Python engine as a folder (PyInstaller one-dir) for the Tauri bundle.

Output: apps/desktop/src-tauri/engine/  (vico-agent[.exe] plus its _internal folder)
The release config ships this folder as an app resource. One-dir starts in seconds;
one-file unpacks ~60 MB to a temp folder on every launch, which took minutes on a
slow laptop.

Run from the repo root with the agent's environment:
    cd services/agent && uv run python ../../scripts/build_sidecar.py
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "services" / "agent"
ENGINE = ROOT / "apps" / "desktop" / "src-tauri" / "engine"


def wake_model() -> Path:
    """The "Vico" wake-word model, downloaded once from its publisher and checksum-verified,
    so it ships inside the installer and works the moment Vico is installed."""
    sys.path.insert(0, str(AGENT))
    from app.audio.wake import MODEL_NAME, download_model

    target = AGENT / "build" / "models" / MODEL_NAME
    if not (target / "conf" / "model.conf").exists():
        print("downloading the wake-word model")
        download_model(target)
    return target


def main() -> None:
    ext = ".exe" if sys.platform == "win32" else ""
    work = AGENT / "build"
    dist = AGENT / "dist"
    model = wake_model()
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onedir",
        "--name", "vico-agent",
        "--distpath", str(dist), "--workpath", str(work), "--specpath", str(work),
        "--paths", str(AGENT),
        "--collect-submodules", "app",
        "--collect-submodules", "uvicorn",
        "--collect-submodules", "keyring.backends",
        "--hidden-import", "send2trash",
        "--collect-all", "vosk",  # loaded lazily by the wake phrase listener, with its native library
        "--collect-submodules", "ddgs",  # its search engines are loaded by name at run time
        "--hidden-import", "lxml.html",
        "--hidden-import", "PIL.ImageGrab",
        "--collect-data", "misaki",  # Kokoro's pronunciation dictionaries
        "--collect-binaries", "onnxruntime",
        "--add-data", f"{model}{os.pathsep}models/{model.name}",
        "--exclude-module", "tkinter",
        "--exclude-module", "pytest",
    ]
    if sys.platform == "win32":
        args += ["--noconsole", "--collect-submodules", "pywinauto", "--collect-submodules", "comtypes",
                 "--hidden-import", "win32timezone", "--hidden-import", "win32clipboard",
                 "--collect-submodules", "pycaw"]
    if importlib.util.find_spec("_sounddevice_data"):
        args += ["--collect-data", "_sounddevice_data"]
    args.append(str(AGENT / "vico_agent_entry.py"))
    print("running:", " ".join(args))
    subprocess.run(args, check=True, cwd=AGENT)

    built = dist / "vico-agent"
    if ENGINE.exists():
        shutil.rmtree(ENGINE)
    shutil.copytree(built, ENGINE)
    size = sum(f.stat().st_size for f in ENGINE.rglob("*") if f.is_file())
    print(f"engine packaged: {ENGINE / ('vico-agent' + ext)} ({size / 1e6:.1f} MB folder)")


if __name__ == "__main__":
    main()
