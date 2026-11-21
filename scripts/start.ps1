# Rubine AI starten (Windows). Aufruf: Rubine-Start.bat
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { Write-Host "Bitte zuerst Rubine-Setup.bat ausfuehren." -ForegroundColor Red; exit 1 }
if (-not (Test-Path (Join-Path $Root ".env"))) { Write-Host "Datei .env fehlt - bitte Rubine-Setup.bat ausfuehren." -ForegroundColor Red; exit 1 }
$env:PYTHONIOENCODING = "utf-8"
Set-Location (Join-Path $Root "backend")
Write-Host "Rubine startet. Zum Beenden dieses Fenster schliessen oder Strg+C druecken." -ForegroundColor Magenta
& $venvPy -m rubine
