# Claude Sessions — plugin StreamController

Plugin maison pour **Stream Deck (grille 5×3, sans molette ni bandeau tactile)**
via [StreamController](https://github.com/StreamController/StreamController) :
il affiche l'état des sessions Claude Code en cours, la consommation du compte
Claude et les cours de quelques actifs (or, indices, BTC).

Setup de référence (celui documenté ici) : Claude Code tourne **sous Windows**,
StreamController tourne **sous WSL2 (Ubuntu)** puisqu'il n'existe pas de build
Windows/macOS. Le plugin lit les fichiers d'état côté Windows via `/mnt/c`.

## Ce que ça affiche (15 touches)

| Touches | Contenu |
|---|---|
| 1 à 7 | une session Claude Code chacune : nom du projet, âge, icône selon l'état |
| 8 | activité récente de GitHub Copilot CLI (voir plus bas — pas un vrai statut temps réel) |
| 9 | consommation du compte Claude — « session actuelle » (fenêtre de 5 h) par défaut, un appui bascule sur « semaine, tous modèles » et inversement |
| 10 à 15 | un actif chacun (XAUUSD, Nasdaq, CAC 40, FTSE 100, S&P 500, BTC par défaut) : nom, prix, variation du jour |

États des sessions Claude : vert = Claude travaille, orange = besoin de toi,
bleu = tour terminé, gris = session endormie (> 3 h). Un appui sur une
session morte la retire de l'affichage.

Chaque touche marché change de couleur de fond (vert/rouge) quand l'actif
franchit ±2 % sur la journée (`alert_pct` dans `market.json`) — hystérésis à
0,75× le seuil et cooldown d'une heure par actif pour éviter le harcèlement.
Un appui sur une touche marché force un rafraîchissement immédiat des cours ;
un appui sur la touche usage bascule entre les deux vues (session / semaine).

**GitHub Copilot CLI** n'a pas de système de hooks comme Claude Code, ni de
commande pour récupérer sa consommation en JSON — impossible d'avoir un vrai
statut travail/attente ou un pourcentage de quota. La touche s'appuie donc
sur l'export OpenTelemetry de Copilot CLI (`COPILOT_OTEL_FILE_EXPORTER_PATH`) :
elle passe au vert dans les ~30 s qui suivent un échange terminé, puis
retombe en gris — un indicateur « actif récemment », pas un statut en direct
(les spans OTel ne sont écrits qu'une fois l'échange fini, pas à son début).
Variables d'environnement Windows à définir une fois (persistantes) :

```powershell
[Environment]::SetEnvironmentVariable("COPILOT_OTEL_ENABLED", "true", "User")
[Environment]::SetEnvironmentVariable("COPILOT_OTEL_FILE_EXPORTER_PATH", "C:\Users\<toi>\.copilot\otel.jsonl", "User")
```

Et l'accès Flatpak correspondant (même logique que pour `.claude`, voir plus bas) :

```bash
flatpak override --user --filesystem=/mnt/c/Users/<toi>/.copilot/otel.jsonl:ro com.core447.StreamController
```

Le placement (quelle touche physique affiche quelle session / quel actif) se
déduit de la position de la touche sur la grille (lignes 1-2, dans l'ordre) :
les 7 premières positions pour les sessions Claude, la 8e pour Copilot, la 9e
pour l'usage, les 6 suivantes pour les actifs, dans l'ordre de `market.json`.

## Environnement : StreamController (Linux) + Claude Code (Windows) via WSL2

StreamController n'a pas de build Windows ni macOS : c'est une application
GTK4 pensée pour Linux (Flatpak).

1. **WSL2 + Ubuntu**, avec WSLg (inclus sur Windows 11) pour l'affichage.
2. **[usbipd-win](https://github.com/dorssel/usbipd-win)** côté Windows pour
   partager le Stream Deck en USB vers WSL2 :
   ```powershell
   usbipd bind --busid <BUSID>      # une fois pour toutes, en admin
   usbipd attach --wsl --busid <BUSID>   # à refaire à chaque redémarrage/veille
   ```
   Trouve le `<BUSID>` avec `usbipd list` (Elgato = vendor ID `0fd9`).
3. Un udev rule pour que le Stream Deck soit accessible sans root dans WSL2 :
   ```
   # /etc/udev/rules.d/70-streamdeck.rules
   SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", MODE="0666"
   KERNEL=="hidraw*", ATTRS{idVendor}=="0fd9", MODE="0666"
   ```
4. **Flatpak en mode utilisateur** (pas de polkit dans WSL2) :
   ```bash
   sudo apt-get install -y flatpak
   flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
   flatpak install --user -y flathub com.core447.StreamController
   ```
5. **Lancement** — `XDG_RUNTIME_DIR` doit pointer sur le socket Wayland de
   WSLg, pas sur celui que systemd définit par défaut dans WSL2 :
   ```bash
   env XDG_RUNTIME_DIR=/mnt/wslg/runtime-dir flatpak run com.core447.StreamController
   ```
   Le processus doit rester rattaché à une session WSL2 vivante (ne pas
   `disown` depuis une commande qui se termine tout de suite, sinon
   systemd-logind tue le processus avec la session).

`tools/start-streamdeck.bat` automatise le ré-attachement USB (avec
ré-attache auto si tu débranches/rebranches) et le lancement de
StreamController — à double-cliquer après chaque redémarrage/veille.

### Accès Windows ↔ WSL2

Les sessions Claude Code et le jeton OAuth vivent côté Windows
(`C:\Users\<toi>\.claude\`) ; StreamController tourne côté WSL2 mais lit ces
fichiers via `/mnt/c`. Le sandbox Flatpak bloque `/mnt/c` par défaut, il faut
l'autoriser explicitement (accès minimal, pas tout `C:\`) :

```bash
flatpak override --user --filesystem=/mnt/c/Users/<toi>/.claude/session-state com.core447.StreamController
flatpak override --user --filesystem=/mnt/c/Users/<toi>/.claude/.credentials.json:ro com.core447.StreamController
```

## Installation du plugin

```bash
git clone <ce dépôt> \
  ~/.var/app/com.core447.StreamController/data/plugins/com_kiora_ClaudeSessions
```

Puis, dans StreamController, poser les actions sur la page :

- « Claude Session Slot » sur les 7 premières touches ;
- « GitHub Copilot CLI (actif récemment) » sur la 8e touche ;
- « Claude Usage » sur la 9e touche ;
- « Marché (touche fixe) » sur les 6 touches suivantes.

### Hooks Claude Code (côté Windows)

Le fichier `~/.claude/hooks/streamdeck-state.py` (voir ce repo pour un modèle)
écrit un JSON par session dans `~/.claude/session-state/` à chaque événement
de cycle de vie. Il est déclenché via des hooks dans
`C:\Users\<toi>\.claude\settings.json` :

```json
{
  "hooks": {
    "SessionStart":     [{ "hooks": [{ "type": "command", "command": "python \"C:\\Users\\<toi>\\.claude\\hooks\\streamdeck-state.py\" SessionStart" }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "python \"C:\\Users\\<toi>\\.claude\\hooks\\streamdeck-state.py\" UserPromptSubmit" }] }],
    "Notification":     [{ "hooks": [{ "type": "command", "command": "python \"C:\\Users\\<toi>\\.claude\\hooks\\streamdeck-state.py\" Notification" }] }],
    "Stop":              [{ "hooks": [{ "type": "command", "command": "python \"C:\\Users\\<toi>\\.claude\\hooks\\streamdeck-state.py\" Stop" }] }],
    "SessionEnd":        [{ "hooks": [{ "type": "command", "command": "python \"C:\\Users\\<toi>\\.claude\\hooks\\streamdeck-state.py\" SessionEnd" }] }]
  }
}
```

Mapping événement → état : `SessionStart`/`Stop` → *waiting* (bleu, ton
tour), `UserPromptSubmit` → *working* (vert), `Notification` → *needs_input*
(orange), `SessionEnd` → suppression du fichier d'état.

## Configuration

**`~/.claude/market.json`** — créé automatiquement au premier lancement, relu à
chaque cycle (pas besoin de redémarrer) :

```json
{
  "alert_pct": 2.0,        // seuil d'alerte, en % de variation sur la journée
  "poll_seconds": 120,     // fréquence d'interrogation des cours
  "notify": false,         // notification desktop en plus du changement de couleur
  "assets": [
    {"label": "XAUUSD",   "source": "yahoo",     "id": "GC=F",     "currency": "USD"},
    {"label": "Nasdaq",   "source": "yahoo",     "id": "^IXIC",    "currency": "PTS"},
    {"label": "CAC 40",   "source": "yahoo",     "id": "^FCHI",    "currency": "PTS"},
    {"label": "FTSE 100", "source": "yahoo",     "id": "^FTSE",    "currency": "PTS"},
    {"label": "S&P 500",  "source": "yahoo",     "id": "^GSPC",    "currency": "PTS"},
    {"label": "BTC",      "source": "coingecko", "id": "bitcoin",  "currency": "EUR"}
  ]
}
```

`source` vaut `coingecko` (crypto) ou `yahoo` (indices, forex, actions).
L'ordre des `assets` correspond à l'ordre des touches marché (10 à 15).
Aucune clé d'API n'est requise.

La consommation du compte Claude est lue via l'API OAuth avec le jeton de
`~/.claude/.credentials.json`, celui que Claude Code entretient lui-même.


# Pour réinstaller 

Après extinction/redémarrage complet, il faut à chaque fois :

1. Double-clique sur tools\start-streamdeck.bat (dans le dossier du repo). Accepte la demande d'autorisation admin qui apparaît — c'est nécessaire pour attacher le Stream Deck en USB à WSL.
2. Le script réattache le Stream Deck puis relance StreamController dans une fenêtre WSL — laisse cette fenêtre ouverte, la fermer coupe tout.
3. Attends quelques secondes que la fenêtre pingouin StreamController s'ouvre et que les touches s'allument.

Si ça bloque (message "Failed to attach device" en boucle, comme on a eu une fois) : c'est que Windows croit le Stream Deck déjà attaché alors qu'il ne l'est plus vraiment. Dans ce cas :
- ouvre une invite de commande PowerShell en administrateur,
- tape usbipd list pour voir l'état,
- si besoin usbipd detach --busid <celui du Stream Deck> puis relance le .bat.