# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase


class UsageKey(ActionBase):
    """Touche unique : consommation du compte Claude. Appui = bascule session/semaine."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_signature = None
        self._index = 0

    def on_ready(self) -> None:
        if self not in self.plugin_base.live_usage:
            self.plugin_base.live_usage.append(self)
        self._last_signature = None
        self._render()

    def on_remove(self) -> None:
        try:
            self.plugin_base.live_usage.remove(self)
        except ValueError:
            pass

    def on_tick(self) -> None:
        self._render()

    def on_key_down(self) -> None:
        slides = self.plugin_base.usage_slides()
        self._index = (self._index + 1) % len(slides)
        self._render(force=True)

    def _current_slide(self) -> dict:
        slides = self.plugin_base.usage_slides()
        return slides[self._index % len(slides)]

    def _render(self, force: bool = False) -> None:
        slide = self._current_slide()
        pct = slide.get("pct")
        signature = (slide["title"], pct, slide.get("reset"))
        if signature == self._last_signature and not force:
            return
        self._last_signature = signature

        color = self.plugin_base._pct_color(pct, slide.get("pace"))
        self.set_background_color(color)
        self.set_top_label(slide["title"], font_size=12)
        self.set_center_label(f"{round(pct)} %" if pct is not None else "?", font_size=18)
        self.set_bottom_label(slide.get("reset", ""), font_size=10)
