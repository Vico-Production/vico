# Install Vico's development dependencies on Windows 10/11.
# Prerequisites you install yourself: Git, Node.js LTS, Rust (rustup, MSVC toolchain),
# Visual Studio C++ Build Tools, and uv (https://docs.astral.sh/uv/). WebView2 ships with Windows 11.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

foreach ($tool in "node", "npm", "cargo", "rustc", "uv") {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Error "$tool is not installed or not on PATH. See README.md > Prerequisites."
    }
}

Write-Host "Installing the Python engine (Python 3.12 via uv)..."
Push-Location "$root\services\agent"
uv sync
Pop-Location

Write-Host "Installing the desktop app..."
Push-Location "$root\apps\desktop"
npm ci
Pop-Location

Write-Host "Creating the demo workspace..."
& uv run --project "$root\services\agent" python "$root\scripts\seed_demo.py"

Write-Host "`nDone. Start Vico in development with:  npm run dev   (from the repo root)"
