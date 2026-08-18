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
# réattache automatiquement le Stream Deck si on le débranche/rebranche
# (utile si la connexion USB est instable).
Start-Process usbipd -ArgumentList "attach --wsl Ubuntu --hardware-id 0fd9:0080 --auto-attach" -WindowStyle Minimized

# Attend que le device soit stable côté WSL (présent 3 fois de suite à 1s
# d'intervalle) avant de lancer StreamController, sinon l'appli démarre sur
# un faux appareil de secours et ne revient jamais chercher le vrai Stream
# Deck une fois la connexion stabilisée.
Write-Host "Attente d'une connexion USB stable..."
$stableCount = 0
$attempts = 0
while ($stableCount -lt 3 -and $attempts -lt 30) {
    $attempts++
    $present = (wsl -d Ubuntu -- bash -lc "test -e /dev/hidraw0 && echo yes || echo no").Trim()
    if ($present -eq "yes") {
        $stableCount++
    } else {
        $stableCount = 0
        Write-Host "  Pas encore stable (tentative $attempts) - verifie le cable/port USB si ca persiste."
    }
    Start-Sleep -Seconds 1
}
if ($stableCount -lt 3) {
    Write-Host "Le Stream Deck n'est toujours pas stable apres 30s. Debranche/rebranche le cable, puis relance ce script."
    Read-Host "Appuie sur Entree pour fermer"
    exit 1
}

Write-Host "Connexion stable. Lancement de StreamController dans WSL (laisse cette fenetre ouverte)..."
wsl -d Ubuntu -- bash -lc "env XDG_RUNTIME_DIR=/mnt/wslg/runtime-dir flatpak run com.core447.StreamController"
