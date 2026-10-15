# Set up a Windows 10/11 machine to develop Vico.
# (People who only want to USE Vico never need this: they install the .exe from the
#  GitHub Releases page, which is built on GitHub's machines.)
#
# Building the desktop shell on Windows needs Rust's MSVC toolchain plus Microsoft's C++
# build tools. A machine that defaults to Rust's GNU toolchain, or has no C++ build
# tools, cannot compile Tauri. This script detects both problems and fixes them.
#
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap_windows.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Install-WithWinget($id, $name, $extra = @()) {
    if (-not (Have "winget")) {
        throw "$name is missing and winget is not available. Install $name manually, then run this script again."
    }
    Write-Host "Installing $name with winget..." -ForegroundColor Cyan
    winget install --id $id -e --accept-package-agreements --accept-source-agreements @extra
}

# 1. Basic tools -------------------------------------------------------------------------
if (-not (Have "git"))  { Install-WithWinget "Git.Git" "Git" }
if (-not (Have "node")) { Install-WithWinget "OpenJS.NodeJS.LTS" "Node.js LTS" }
if (-not (Have "uv"))   { Install-WithWinget "astral-sh.uv" "uv" }
if (-not (Have "rustup")) { Install-WithWinget "Rustlang.Rustup" "Rust (rustup)" }

# 2. Microsoft C++ build tools (provides link.exe and the Windows SDK) ---------------------
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
$hasCpp = $false
if (Test-Path $vswhere) {
    $hasCpp = [bool](& $vswhere -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath)
}
if (-not $hasCpp) {
    Write-Host "Microsoft C++ build tools are missing (needed to compile the desktop shell)." -ForegroundColor Yellow
    Install-WithWinget "Microsoft.VisualStudio.2022.BuildTools" "Visual Studio C++ Build Tools" @(
        "--override", "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
    )
}

# 3. Rust must use the MSVC toolchain on Windows -----------------------------------------
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
rustup toolchain install stable-x86_64-pc-windows-msvc --profile minimal | Out-Null
$active = (rustup show active-toolchain) -join " "
if ($active -notmatch "msvc") {
    Write-Host "Rust was using '$active'. Switching to the MSVC toolchain, which Tauri needs on Windows." -ForegroundColor Yellow
}
# Pin it for this repository only, so other Rust projects on the machine are untouched.
rustup override set stable-x86_64-pc-windows-msvc --path "$root\apps\desktop\src-tauri" | Out-Null

# 4. Project dependencies ----------------------------------------------------------------
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

Write-Host "`nDone. Start Vico in development with:  npm run dev   (from the repo root)" -ForegroundColor Green
Write-Host "If this is the first install of the C++ build tools, open a new terminal first."
