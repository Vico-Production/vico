# Check that this Windows machine can build and run Vico, and report memory.
$root = Split-Path -Parent $PSScriptRoot
$ok = $true

function Check($name, $test, $hint) {
    if (& $test) { Write-Host "[ok]   $name" -ForegroundColor Green }
    else { Write-Host "[miss] $name - $hint" -ForegroundColor Yellow; $script:ok = $false }
}

Check "Node.js"  { Get-Command node -ErrorAction SilentlyContinue } "install Node.js LTS"
Check "Rust"     { Get-Command cargo -ErrorAction SilentlyContinue } "install rustup (MSVC toolchain)"
Check "uv"       { Get-Command uv -ErrorAction SilentlyContinue } "install uv"
Check "WebView2" {
    (Test-Path "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}") -or
    (Test-Path "HKCU:\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}")
} "the installer downloads it automatically"
Check "Microsoft Edge (for browser control)" {
    (Test-Path "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe") -or (Test-Path "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe")
} "install Edge or Chrome"
Check "Python engine environment" { Test-Path "$root\services\agent\.venv" } "run scripts\bootstrap_windows.ps1"
Check "Desktop dependencies" { Test-Path "$root\apps\desktop\node_modules" } "run scripts\bootstrap_windows.ps1"
Check "Microphone" {
    (Get-PnpDevice -Class AudioEndpoint -Status OK -ErrorAction SilentlyContinue | Where-Object FriendlyName -match "Microphone|Mic|Input").Count -gt 0
} "plug in a microphone, or type instead"

$mem = Get-CimInstance Win32_ComputerSystem
$gb = [math]::Round($mem.TotalPhysicalMemory / 1GB, 1)
Write-Host "Installed memory: $gb GB" -ForegroundColor Cyan
if ($gb -lt 4) { Write-Host "Below the 4 GB target; Vico may be slow." -ForegroundColor Yellow }

$vico = Get-Process -Name "vico", "vico-agent" -ErrorAction SilentlyContinue
if ($vico) {
    $mb = [math]::Round(($vico | Measure-Object WorkingSet64 -Sum).Sum / 1MB)
    Write-Host "Vico is running and using $mb MB (app + engine, working set)." -ForegroundColor Cyan
}

if ($ok) { Write-Host "`nAll checks passed." -ForegroundColor Green } else { Write-Host "`nSome checks need attention." -ForegroundColor Yellow }
