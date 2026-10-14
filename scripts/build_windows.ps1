# Build the Windows installers (.exe NSIS and .msi) with the engine bundled.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location "$root\services\agent"
uv sync
uv run python ..\..\scripts\build_sidecar.py
Pop-Location

Push-Location "$root\apps\desktop"
npm ci
npx tauri build --config src-tauri/tauri.release.conf.json
Pop-Location

Write-Host "`nInstallers:"
Get-ChildItem "$root\apps\desktop\src-tauri\target\release\bundle" -Recurse -Include *.exe, *.msi | ForEach-Object {
    "{0}  ({1:N1} MB)" -f $_.FullName, ($_.Length / 1MB)
}
