# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.InputIdentifier import Input

# Import python modules
import time

# Durée pendant laquelle la molette fige l'actif choisi avant de reprendre le défilement
MANUAL_TIMEOUT = 30


class Market(ActionBase):
    """Tuile marché sur une molette du SD+ : cours + variation du jour.

    Rotation = actif suivant/précédent, appui = détail des trois actifs sur le
    bandeau, appui long = rafraîchissement immédiat.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._index = 0
        self._manual_until = 0.0
        self._last_signature = None
        self._hidden = False

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

    def event_callback(self, event, data: dict = None) -> None:
        if event in (Input.Dial.Events.TURN_CW, Input.Dial.Events.TURN_CCW):
            assets = self.plugin_base.get_market_assets()
            if not assets:
                return
            step = 1 if event == Input.Dial.Events.TURN_CW else -1
            self._index = (self._current_index(len(assets)) + step) % len(assets)
            self._manual_until = time.time() + MANUAL_TIMEOUT
            self._render(force=True)
        elif event in (
            Input.Dial.Events.SHORT_UP,
            Input.Dial.Events.SHORT_TOUCH_PRESS,
            Input.Key.Events.SHORT_UP,
        ):
            self.plugin_base.show_market_details()
        elif event == Input.Dial.Events.HOLD_START:
            self.plugin_base.refresh_market_now()

    def set_hidden(self, hidden: bool) -> None:
        """Masque la tuile pendant qu'un détail occupe tout le bandeau."""
        if hidden == self._hidden:
            return
        self._hidden = hidden
        self._render(force=True)

    def _current_index(self, count: int) -> int:
        if time.time() < self._manual_until:
            return self._index % count
        cycle = max(1, self.plugin_base.market_cycle_seconds())
        return int(time.time() / cycle) % count

    def _render(self, force: bool = False) -> None:
        if self._hidden:
            if self._last_signature != "hidden" or force:
                self._last_signature = "hidden"
                self.set_background_color([0, 0, 0, 0], update=False)
                self.set_media(image=None)
            return

        assets = self.plugin_base.get_market_assets()
        if not assets:
            signature = ("empty",)
            if signature == self._last_signature and not force:
                return
            self._last_signature = signature
            self.set_background_color([0, 0, 0, 0], update=False)
            self.set_media(image=self.plugin_base.render_market_tile(None, 0, 0), size=1.0)
            return

        index = self._current_index(len(assets))
        asset = assets[index]
        signature = (
            index,
            asset.get("price"),
            asset.get("pct"),
            asset.get("alert"),
            asset.get("stale"),
        )
        if signature == self._last_signature and not force:
            return
        self._last_signature = signature

        self.set_background_color([0, 0, 0, 0], update=False)
        self.set_media(
            image=self.plugin_base.render_market_tile(asset, index, len(assets)),
            size=1.0,
        )
