# Erlaubt eingehende Verbindungen auf Port 8000 NUR im privaten Netzwerk (Heim-WLAN).
# Als Administrator ausfuehren: Rechtsklick auf PowerShell > "Als Administrator ausfuehren", dann:
#   powershell -ExecutionPolicy Bypass -File scripts\allow-firewall.ps1
$ErrorActionPreference = "Stop"
$port = 8000
$name = "Rubine AI (TCP $port, privat)"
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Bitte als Administrator ausfuehren." -ForegroundColor Red; exit 1
}
Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow -Profile Private | Out-Null
Write-Host "Firewall-Regel '$name' angelegt." -ForegroundColor Green
$profiles = Get-NetConnectionProfile
foreach ($p in $profiles) {
    Write-Host ("Netzwerk '{0}': Profil {1}" -f $p.Name, $p.NetworkCategory)
    if ($p.NetworkCategory -ne "Private") {
        Write-Host "  Hinweis: Dieses Netzwerk ist nicht 'Privat'. Fuer dein Heim-WLAN unter Einstellungen > Netzwerk > WLAN > Eigenschaften auf 'Privat' stellen." -ForegroundColor Yellow
    }
}
