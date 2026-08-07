# Claude Sessions — plugin StreamController

Plugin maison pour **Stream Deck +** (via [StreamController](https://github.com/StreamController/StreamController)) :
il affiche l'état des sessions Claude Code en cours, la supervision Uptime Kuma,
la consommation du compte Claude et les cours BTC / ETH / S&P 500.

## Ce que ça affiche

**Touches (4×2)**

| Touche | Contenu |
|---|---|
| 7 premières | une session Claude Code chacune : nom du projet, âge, icône Clawd selon l'état |
| dernière | Uptime Kuma : nombre de services en ligne, rouge dès qu'un service tombe |

États des sessions : vert = Claude travaille, orange = besoin de toi, bleu = tour
terminé, gris = session endormie (> 3 h). Un appui affiche le détail sur le
bandeau pendant 5 s ; un appui sur une session morte la retire.

**Bandeau tactile (800×100)**

- à gauche, la consommation du compte Claude qui alterne toutes les 4 s entre
  « session actuelle » (fenêtre de 5 h) et « semaine, tous modèles », avec jauge
  et heure de réinitialisation ;
- à droite, la zone de la **molette 4** : cours d'un actif (nom, prix, variation
  du jour) qui défile au même rythme.

**Molette 4**

| Geste | Effet |
|---|---|
| rotation | actif suivant / précédent (figé 30 s, puis reprise du défilement) |
| appui | les trois actifs en grand sur tout le bandeau |
| appui long | rafraîchissement immédiat des cours |

Une **alerte** se déclenche quand un actif franchit ±2 % sur la journée : la
tuile passe en vert ou rouge et le bandeau bascule 8 s sur le détail. Hystérésis
à 0,75× le seuil et cooldown d'une heure par actif pour éviter le harcèlement.

## Installation

```bash
git clone <ce dépôt> \
  ~/.var/app/com.core447.StreamController/data/plugins/com_kiora_ClaudeSessions
```

Puis, dans StreamController, poser les actions sur la page :

- « Claude Session Slot » sur les touches (le slot est déduit de la position) ;
- « Uptime Kuma » sur une touche ;
- « Marchés (BTC / ETH / S&P 500) » sur une molette.

Les états des sessions viennent des hooks Claude Code (`~/.claude/settings.json`)
qui appellent `~/.claude/hooks/streamdeck-state.py <event>` et écrivent un JSON
par session dans `~/.claude/session-state/`.

## Configuration

**`~/.claude/market.json`** — créé automatiquement au premier lancement, relu à
chaque cycle (pas besoin de redémarrer) :

```json
{
  "alert_pct": 2.0,        // seuil d'alerte, en % de variation sur la journée
  "poll_seconds": 120,     // fréquence d'interrogation des cours
  "cycle_seconds": 4,      // vitesse du défilement (cours et usage Claude)
  "notify": false,         // notification desktop en plus de l'alerte visuelle
  "assets": [
    {"label": "BTC",     "source": "coingecko", "id": "bitcoin",  "currency": "EUR"},
    {"label": "ETH",     "source": "coingecko", "id": "ethereum", "currency": "EUR"},
    {"label": "S&P 500", "source": "yahoo",     "id": "^GSPC",    "currency": "PTS"}
  ]
}
```

`source` vaut `coingecko` (crypto, en euros) ou `yahoo` (indices et actions :
`^FCHI` pour le CAC 40, `^IXIC` pour le Nasdaq…). Aucune clé d'API n'est requise.

**`~/.claude/uptime-kuma.json`** (chmod 600) :

```json
{"url": "https://uptime.example.org", "api_key": "…"}
```

La consommation du compte Claude est lue via l'API OAuth avec le jeton de
`~/.claude/.credentials.json`, celui que Claude Code entretient lui-même.

## Notes techniques

- Sur le Stream Deck +, **chaque molette possède sa propre zone de 200×100 px**
  dans le bandeau, composée par-dessus l'image de fond : une action sur molette
  peut donc afficher en permanence, pas seulement réagir aux appuis.
- Le bandeau est un **fichier unique** (`assets/strip.png`) redessiné sur place :
  `Page.set_background_image` réécrit le JSON de la page et un backup à chaque
  appel, ce qui est impensable à 4 s d'intervalle.
- Toute action posée à la main dans une page doit contenir `label-control-actions`,
  `image-control-action` et `background-control-action` dans son état, sinon
  `set_background_color` et `set_label` sont ignorés silencieusement.

`tools/preview-market.py` rend les tuiles, le bandeau et les détails dans
`~/.claude/preview-*.png` sans toucher à l'application :

```bash
flatpak run --command=python3 com.core447.StreamController \
  ~/.var/app/com.core447.StreamController/data/plugins/com_kiora_ClaudeSessions/tools/preview-market.py
```
