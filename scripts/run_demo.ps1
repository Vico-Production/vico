# Reset the demo workspace and start Vico for a rehearsal.
# Usage:  scripts\run_demo.ps1            (development build)
#         scripts\run_demo.ps1 -Installed (installed app)
param([switch]$Installed)
$root = Split-Path -Parent $PSScriptRoot

& uv run --project "$root\services\agent" python "$root\scripts\seed_demo.py" --reset

Write-Host @"

Demo script (about 2.5 minutes) - see docs/DEMO.md for details:
 1. Typed English: "Create a folder called Hackathon"  -> approve -> folder appears.
 2. Spoken English: "Open my attendance notes"         -> approve -> file opens.
 3. Spoken Yoruba or Hausa: ask to save a note          -> check transcript -> approve.
 4. Interpreter: English -> Yoruba, then swap.
 5. Turn Wi-Fi off: "create folder Demo" still works offline (typed).
"@

if ($Installed) {
    $exe = Join-Path $env:LOCALAPPDATA "Vico\vico.exe"
    if (-not (Test-Path $exe)) { $exe = Join-Path $env:ProgramFiles "Vico\vico.exe" }
    Start-Process $exe
} else {
    Push-Location "$root\apps\desktop"
    npm run tauri dev
    Pop-Location
}
