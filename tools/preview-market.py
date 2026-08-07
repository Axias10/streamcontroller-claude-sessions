"""Prévisualisation hors-app des rendus marché du plugin ClaudeSessions.

Lancé dans le flatpak StreamController (mêmes polices, même PIL) :
    flatpak run --command=python3 com.core447.StreamController \
        ~/.var/app/com.core447.StreamController/data/plugins/com_kiora_ClaudeSessions/tools/preview-market.py

Écrit ~/.claude/preview-{tiles,bandeau,details}.png sans toucher à l'app en cours.
"""
import importlib
import os
import sys
import types
from unittest.mock import MagicMock

PLUGINS = os.path.expanduser("~/.var/app/com.core447.StreamController/data/plugins")
sys.path.insert(0, PLUGINS)

# Stubs des modules StreamController (le plugin n'est pas chargé par l'app ici)
def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


_Base = type("_Base", (), {"__init__": lambda self, *a, **k: None})

for pkg in ("src", "src.backend", "src.backend.PluginManager", "src.backend.DeckManagement"):
    _stub(pkg)
_stub("src.backend.PluginManager.PluginBase", PluginBase=_Base)
_stub("src.backend.PluginManager.ActionBase", ActionBase=_Base)
_stub("src.backend.PluginManager.ActionHolder", ActionHolder=_Base)
_stub("src.backend.PluginManager.ActionInputSupport",
      ActionInputSupport=type("ActionInputSupport", (), {"UNTESTED": 1, "SUPPORTED": 2, "UNSUPPORTED": 0}))
_stub("src.backend.DeckManagement.InputIdentifier",
      Input=type("Input", (), {"Key": type("Key", (), {}), "Dial": type("Dial", (), {}),
                               "Touchscreen": type("Touchscreen", (), {})}))
_stub("globals", DATA_PATH="/tmp", deck_manager=MagicMock())

main = importlib.import_module("com_kiora_ClaudeSessions.main")
Plugin = main.ClaudeSessionsPlugin

# Instance sans __init__ (pas d'app, pas de deck)
p = Plugin.__new__(Plugin)
p._market_config = dict(Plugin._MARKET_DEFAULTS)
p._market_alert_state = {}
p._market_alert_last = {}
p._market = []
p._market_ts = 0.0

# Données réelles
p._refresh_market = types.MethodType(Plugin._refresh_market, p)
main.GLib = MagicMock()  # évite idle_add hors boucle GTK
p._refresh_market()

assets = p.get_market_assets()
print("Actifs récupérés :")
for a in assets:
    print(f"  {a['label']:<8} {p._fmt_price(a):>12}  {p._fmt_pct(a.get('pct')):>9}  alert={a.get('alert')}")

out = os.path.expanduser("~/.claude")

# 1. Tuile de la molette, pour chaque actif
from PIL import Image as PILImage
strip = PILImage.new("RGBA", (800, 100), (0, 0, 0, 255))
for i, asset in enumerate(assets):
    tile = p.render_market_tile(asset, i, len(assets))
    strip.paste(tile, (i * 200, 0), tile)
# 4e case : variante alerte (hausse forte simulée)
demo = dict(assets[0]) if assets else {"label": "BTC", "currency": "EUR", "price": 61000, "pct": 3.4}
demo.update({"pct": 3.42, "alert": "up"})
tile = p.render_market_tile(demo, 0, len(assets) or 3)
strip.paste(tile, (600, 0), tile)
strip.convert("RGB").save(f"{out}/preview-tiles.png")

# 2. Bandeau : les deux vues d'usage qui défilent + la tuile marché de la molette 4
import time as _time

p._usage = {
    "session_pct": 23, "session_reset": _time.time() + 6240,
    "week_pct": 8, "week_reset": _time.time() + 3 * 86400,
}
p._details_timer = None
p._strip_signature = None
p._refresh_strip = lambda: None
p._set_market_hidden = lambda hidden: None


class _FrozenClock:
    """Fige l'horloge pour choisir laquelle des deux vues est rendue."""

    def __init__(self, base):
        self._base = base

    def time(self):
        return self._base


real_time = main.time
cycle = p.market_cycle_seconds()
base = (int(_time.time() / cycle) // 2) * 2 * cycle  # début d'un cycle « session »
bandeau = None
for i, name in enumerate(("session", "semaine")):
    main.time = _FrozenClock(base + i * cycle)
    main.STRIP = f"{out}/preview-usage-{name}.png"
    p._strip_signature = None
    p._render_status_strip()
    view = PILImage.open(main.STRIP).convert("RGBA")
    if assets:
        tile = p.render_market_tile(assets[i % len(assets)], i % len(assets), len(assets))
        view.paste(tile, (600, 0), tile)
    if bandeau is None:
        bandeau = PILImage.new("RGBA", (800, 210), (0, 0, 0, 255))
    bandeau.paste(view, (0, i * 110), view)
main.time = real_time
bandeau.convert("RGB").save(f"{out}/preview-bandeau.png")

# 3. Détail plein bandeau (appui molette)
main.STRIP = f"{out}/preview-details.png"
p.show_market_details()
print("Images écrites dans ~/.claude/preview-*.png")
