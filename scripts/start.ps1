# Rubine AI starten (Windows). Aufruf: Rubine-Start.bat
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { Write-Host "Bitte zuerst Rubine-Setup.bat ausfuehren." -ForegroundColor Red; exit 1 }
if (-not (Test-Path (Join-Path $Root ".env"))) { Write-Host "Datei .env fehlt - bitte Rubine-Setup.bat ausfuehren." -ForegroundColor Red; exit 1 }
# Windows-Konsole: "QuickEdit/Markieren" abschalten. Sonst haelt ein Mausklick ins Fenster den Server an,
# und die App bleibt beim Laden haengen, bis man Esc drueckt.
try {
    Add-Type -Namespace RubineConsole -Name Native -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern System.IntPtr GetStdHandle(int h);
[DllImport("kernel32.dll")] public static extern bool GetConsoleMode(System.IntPtr h, out uint m);
[DllImport("kernel32.dll")] public static extern bool SetConsoleMode(System.IntPtr h, uint m);
'@
    $h = [RubineConsole.Native]::GetStdHandle(-10)
    $mode = 0
    if ([RubineConsole.Native]::GetConsoleMode($h, [ref]$mode)) {
        [void][RubineConsole.Native]::SetConsoleMode($h, (($mode -band (-bnot 0x40)) -bor 0x80))
    }
} catch { }
$env:PYTHONIOENCODING = "utf-8"
Set-Location (Join-Path $Root "backend")
Write-Host "Rubine startet. Dieses Fenster offen lassen (minimieren ist ok). Beenden: Fenster schliessen." -ForegroundColor Magenta
& $venvPy -m rubine
