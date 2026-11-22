# Rubine AI - Setup fuer Windows (PowerShell 5.1 oder 7).
# Aufruf: Doppelklick auf Rubine-Setup.bat  (oder: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Befehl fehlgeschlagen ($LASTEXITCODE): $Exe $($Arguments -join ' ')" }
}

function Find-Python {
    foreach ($v in @("3.12", "3.13", "3.11")) {
        try {
            $exe = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
        } catch { }
    }
    try {
        $ver = & python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($ver -in @("3.11", "3.12", "3.13")) { return (& python -c "import sys; print(sys.executable)").Trim() }
    } catch { }
    return $null
}

Write-Host ""
Write-Host "  Rubine AI - Einrichtung" -ForegroundColor Magenta
Write-Host ""

# PyTorch (CUDA) enthaelt Dateien mit ~140 Zeichen relativem Pfad. Ohne "Long Paths" erlaubt Windows nur 260 Zeichen.
$longPaths = $false
try { $longPaths = ((Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -ErrorAction Stop).LongPathsEnabled -eq 1) } catch { }
if (-not $longPaths -and $Root.Length -gt 60) {
    Write-Host "Der Ordnerpfad ist zu lang fuer Windows ($($Root.Length) Zeichen):" -ForegroundColor Red
    Write-Host "  $Root"
    Write-Host "Die Installation von PyTorch wuerde mit 'No such file or directory' scheitern."
    Write-Host "Loesung: Rubine-Ordner nach C:\Rubine verschieben (dort einen ggf. vorhandenen Ordner backend\.venv loeschen)"
    Write-Host "und Rubine-Setup.bat erneut starten. Alternativ in Windows lange Pfade erlauben (siehe README)."
    exit 1
}

$py = Find-Python
if (-not $py) {
    Write-Host "Python 3.11 - 3.13 wurde nicht gefunden." -ForegroundColor Red
    Write-Host "Installiere Python 3.12 von https://www.python.org/downloads/ (Haken bei 'Add python.exe to PATH')."
    exit 1
}
Write-Host "==> Python: $py"

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Host "Node.js wurde nicht gefunden. Installiere die LTS-Version von https://nodejs.org/" -ForegroundColor Red
    exit 1
}
$nodeMajor = [int]((& node --version).TrimStart("v").Split(".")[0])
if ($nodeMajor -lt 20) { Write-Host "Node.js >= 20.9 wird benoetigt (gefunden: $(& node --version))." -ForegroundColor Red; exit 1 }
Write-Host "==> Node.js: $(& node --version)"

$venvPy = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "==> Erstelle virtuelle Umgebung ..."
    Invoke-Checked $py @("-m", "venv", (Join-Path $Root "backend\.venv"))
}
Invoke-Checked $venvPy @("-m", "pip", "install", "--upgrade", "pip", "-q")

$hasNvidia = [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
if ($hasNvidia) {
    Write-Host "==> NVIDIA-GPU erkannt: installiere PyTorch mit CUDA"
    $index = "https://download.pytorch.org/whl/cu132"
} else {
    Write-Host "==> Keine NVIDIA-GPU: installiere CPU-PyTorch (Training laeuft echt, aber langsam)"
    $index = "https://download.pytorch.org/whl/cpu"
}
Invoke-Checked $venvPy @("-m", "pip", "install", "torch==2.15.0", "--index-url", $index)
Invoke-Checked $venvPy @("-m", "pip", "install", "-r", (Join-Path $Root "backend\requirements-dev.txt"))

$envFile = Join-Path $Root ".env"
if (-not (Test-Path $envFile)) {
    $bytes = New-Object byte[] 12
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $pw = [Convert]::ToBase64String($bytes).Replace("+", "x").Replace("/", "y").Replace("=", "")
    $content = (Get-Content (Join-Path $Root ".env.example") -Raw) -replace "(?m)^RUBINE_ADMIN_PASSWORD=.*$", "RUBINE_ADMIN_PASSWORD=$pw"
    [System.IO.File]::WriteAllText($envFile, $content, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host ""
    Write-Host "==> .env erstellt. Dein Rubine-Passwort: $pw" -ForegroundColor Green
    Write-Host "    (steht auch in der Datei .env)"
    Write-Host ""
}

Write-Host "==> Lade Basismodell Qwen2.5-0.5B-Instruct (einmalig ca. 1 GB) ..."
Invoke-Checked $venvPy @("-c", "from huggingface_hub import snapshot_download as d; d('Qwen/Qwen2.5-0.5B-Instruct', revision='7ae557604adf67be50417f59c2c2f167def9a775')")

Write-Host "==> Baue die Web-App ..."
Push-Location (Join-Path $Root "frontend")
try {
    Invoke-Checked "npm.cmd" @("ci", "--no-audit", "--no-fund")
    Invoke-Checked "npm.cmd" @("run", "build")
} finally { Pop-Location }

Write-Host ""
Write-Host "Fertig! Starte Rubine mit Rubine-Start.bat" -ForegroundColor Green
Write-Host "Fuer das iPhone im WLAN einmalig (als Administrator): scripts\allow-firewall.ps1"
