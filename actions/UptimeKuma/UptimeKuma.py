# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase

COLOR_UP = [24, 118, 52, 255]
COLOR_DOWN = [200, 40, 35, 255]
COLOR_UNKNOWN = [45, 45, 45, 255]


class UptimeKuma(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def on_ready(self) -> None:
        if self not in self.plugin_base.live_kuma:
            self.plugin_base.live_kuma.append(self)
        self._render()

    def on_remove(self) -> None:
        try:
            self.plugin_base.live_kuma.remove(self)
        except ValueError:
            pass

    def on_tick(self) -> None:
        self._render()

    def on_key_down(self) -> None:
        self.plugin_base.show_kuma_details()

    def _render(self) -> None:
        kuma = self.plugin_base._kuma
        self.set_media(image=self.plugin_base.kuma_icon, size=0.5)
        if kuma is None:
            self.set_background_color(COLOR_UNKNOWN)
            self.set_top_label("uptime", font_size=12)
            self.set_bottom_label("…", font_size=12)
            return
        down = kuma["down"]
        total = kuma["up"] + down
        if down:
            self.set_background_color(COLOR_DOWN)
            self.set_top_label("uptime", font_size=12)
            self.set_bottom_label(f"{down} HS !", font_size=14)
        else:
            self.set_background_color(COLOR_UP)
            self.set_top_label("uptime", font_size=12)
            self.set_bottom_label(f"{total} OK", font_size=12)
