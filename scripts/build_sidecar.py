"""Package the Python engine as one executable for Tauri's externalBin.

Output: apps/desktop/src-tauri/binaries/vico-agent-<rust target triple>[.exe]

Run from the repo root with the agent's environment:
    cd services/agent && uv run python ../../scripts/build_sidecar.py
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "services" / "agent"
BINARIES = ROOT / "apps" / "desktop" / "src-tauri" / "binaries"


def target_triple() -> str:
    out = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit("could not read the Rust host triple from `rustc -vV`")


def main() -> None:
    triple = target_triple()
    ext = ".exe" if sys.platform == "win32" else ""
    work = AGENT / "build"
    dist = AGENT / "dist"
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile",
        "--name", "vico-agent",
        "--distpath", str(dist), "--workpath", str(work), "--specpath", str(work),
        "--paths", str(AGENT),
        "--collect-submodules", "app",
        "--collect-submodules", "uvicorn",
        "--collect-submodules", "keyring.backends",
        "--hidden-import", "send2trash",
        "--exclude-module", "tkinter",
        "--exclude-module", "pytest",
    ]
    if sys.platform == "win32":
        args += ["--noconsole", "--collect-submodules", "pywinauto", "--collect-submodules", "comtypes",
                 "--hidden-import", "win32timezone"]
    if importlib.util.find_spec("_sounddevice_data"):
        args += ["--collect-data", "_sounddevice_data"]
    args.append(str(AGENT / "vico_agent_entry.py"))
    print("running:", " ".join(args))
    subprocess.run(args, check=True, cwd=AGENT)

    built = dist / f"vico-agent{ext}"
    BINARIES.mkdir(parents=True, exist_ok=True)
    target = BINARIES / f"vico-agent-{triple}{ext}"
    shutil.copy2(built, target)
    print(f"engine packaged: {target} ({target.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
