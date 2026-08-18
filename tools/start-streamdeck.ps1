# Relance StreamController (WSL2) avec le Stream Deck après un redémarrage/veille.
# Usage : double-clic sur start-streamdeck.bat (qui appelle ce script).

$ErrorActionPreference = "Stop"

# Ré-exécute en admin si besoin (usbipd attach l'exige).
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`""
    exit
}

$env:Path += ";C:\Program Files\usbipd-win"

Write-Host "Rattachement USB du Stream Deck (VID:PID 0fd9:0080) a WSL, avec re-attache auto..."
# Fenêtre séparée et minimisée : --auto-attach ne rend jamais la main, elle
# réattache automatiquement le Stream Deck si on le débranche/rebranche.
Start-Process usbipd -ArgumentList "attach --wsl Ubuntu --hardware-id 0fd9:0080 --auto-attach" -WindowStyle Minimized

Start-Sleep -Seconds 3

Write-Host "Lancement de StreamController dans WSL (laisse cette fenetre ouverte)..."
wsl -d Ubuntu -- bash -lc "env XDG_RUNTIME_DIR=/mnt/wslg/runtime-dir flatpak run com.core447.StreamController"
