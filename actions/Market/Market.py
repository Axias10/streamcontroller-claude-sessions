# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase


class MarketKey(ActionBase):
    """Touche fixe : un actif par touche (ordre = celui de market.json).

    Appui = rafraîchissement immédiat des cours. Couleur de fond = alerte
    (vert/rouge) au franchissement du seuil, sinon neutre.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_signature = None

    def on_ready(self) -> None:
        if self not in self.plugin_base.live_market:
            self.plugin_base.live_market.append(self)
        self._last_signature = None
        self._render()

    def on_remove(self) -> None:
        try:
            self.plugin_base.live_market.remove(self)
        except ValueError:
            pass

    def on_tick(self) -> None:
        self._render()

    def on_key_down(self) -> None:
        self.plugin_base.refresh_market_now()

    def _get_index(self) -> int:
        """Déduit l'actif de la position de la touche (grille 5×3, touches 9 à 14)."""
        try:
            ident = self.input_ident.json_identifier
            x, y = ident.split("x")
            return int(x) + int(y) * 5 - 9
        except Exception:
            return int(self.get_settings().get("index", 0))

    def _render(self, force: bool = False) -> None:
        assets = self.plugin_base.get_market_assets()
        index = self._get_index()

        if index < 0 or index >= len(assets):
            signature = ("empty", index)
            if signature == self._last_signature and not force:
                return
            self._last_signature = signature
            self.set_background_color([20, 20, 20, 255])
            self.set_top_label("")
            self.set_center_label("…")
            self.set_bottom_label("")
            return

        asset = assets[index]
        signature = (index, asset.get("price"), asset.get("pct"), asset.get("alert"), asset.get("stale"))
        if signature == self._last_signature and not force:
            return
        self._last_signature = signature

        pct = asset.get("pct")
        stale = asset.get("stale")
        alert = asset.get("alert")
        color = self.plugin_base._MARKET_BG.get(alert, self.plugin_base._MARKET_BG[None])

        self.set_background_color(color if not stale else self.plugin_base._MARKET_FLAT)
        self.set_top_label(str(asset.get("label", "?"))[:10], font_size=12)
        self.set_center_label(self.plugin_base._fmt_price(asset), font_size=13)
        arrow = "▲" if (pct or 0) > 0 else ("▼" if (pct or 0) < 0 else "•")
        self.set_bottom_label(f"{arrow} {self.plugin_base._fmt_pct(pct)}", font_size=11)
