#!/usr/bin/env bash
# À lancer une fois dans le terminal WSL2 Ubuntu (pas depuis Windows) :
#   bash /mnt/c/Users/Justin/Documents/GitHub/streamcontroller-claude-sessions/tools/wsl-setup.sh
set -euo pipefail

echo "== udev : autoriser l'accès au Stream Deck sans root =="
sudo tee /etc/udev/rules.d/70-streamdeck.rules > /dev/null <<'RULES'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", MODE="0666"
KERNEL=="hidraw*", ATTRS{idVendor}=="0fd9", MODE="0666"
RULES
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "== Flatpak + Flathub =="
sudo apt-get update -qq
sudo apt-get install -y -qq flatpak
# --user : pas de polkit (indisponible sous WSL) pour le remote et l'install système
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo

echo "== StreamController =="
flatpak install --user -y flathub com.core447.StreamController

echo "== Plugin Claude Sessions =="
PLUGDIR="$HOME/.var/app/com.core447.StreamController/data/plugins"
mkdir -p "$PLUGDIR"
if [ -d "$PLUGDIR/com_kiora_ClaudeSessions" ]; then
  echo "Le plugin existe déjà dans $PLUGDIR, je ne l'écrase pas."
else
  cp -r "/mnt/c/Users/Justin/Documents/GitHub/streamcontroller-claude-sessions" \
        "$PLUGDIR/com_kiora_ClaudeSessions"
fi

echo
echo "Terminé. Prochaine étape : redémarrer le hidraw0 (rebranche le Stream Deck ou refais"
echo "usbipd attach côté Windows), puis lance StreamController :"
echo "  flatpak run com.core447.StreamController"
