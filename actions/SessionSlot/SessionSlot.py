# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase

# Import python modules
import time

# Couleurs de fond par état [r, g, b, a]
COLORS = {
    "working": [24, 118, 52, 255],      # vert : Claude travaille
    "needs_input": [230, 126, 0, 255],  # orange : attend ta réponse
    "waiting": [46, 82, 130, 255],      # bleu : tour terminé, à toi
    "stale": [45, 45, 45, 255],         # gris : session probablement morte
    "empty": [0, 0, 0, 255],
}

STALE_AFTER = 3 * 3600


class SessionSlot(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def on_ready(self) -> None:
        if self not in self.plugin_base.live_slots:
            self.plugin_base.live_slots.append(self)
        self._render()

    def on_remove(self) -> None:
        try:
            self.plugin_base.live_slots.remove(self)
        except ValueError:
            pass

    def on_key_down(self) -> None:
        sessions = self.plugin_base.get_sessions()
        slot = self._get_slot()
        if slot >= len(sessions):
            return
        session = sessions[slot]
        age = time.time() - session.get("ts", 0)
        if age > STALE_AFTER:
            # Appui sur une session morte : on la retire de l'affichage
            self.plugin_base.remove_session(session.get("session_id", ""))

    def on_tick(self) -> None:
        self._render()

    def _get_slot(self) -> int:
        """Déduit le slot de la position de la touche ("XxY" -> x + y*5, grille 5×3)."""
        try:
            ident = self.input_ident.json_identifier
            x, y = ident.split("x")
            return int(x) + int(y) * 5
        except Exception:
            return int(self.get_settings().get("slot", 0))

    def _render(self) -> None:
        sessions = self.plugin_base.get_sessions()
        slot = self._get_slot()

        if slot >= len(sessions):
            self.set_background_color(COLORS["empty"])
            self.set_media(image=None)
            self.set_top_label("")
            self.set_center_label("")
            self.set_bottom_label("")
            return

        session = sessions[slot]
        state = session.get("state", "waiting")
        age = time.time() - session.get("ts", 0)
        if age > STALE_AFTER:
            state = "stale"

        color = COLORS.get(state, COLORS["empty"])

        project = session.get("project", "?")[:16]

        if age < 90:
            age_txt = f"{int(age)}s"
        elif age < 3600:
            age_txt = f"{int(age / 60)}m"
        else:
            age_txt = f"{int(age / 3600)}h"

        self.set_background_color(color)
        self.set_media(image=self.plugin_base.state_icons.get(state), size=0.4)
        self.set_top_label(project, font_size=10)
        self.set_center_label("")
        self.set_bottom_label(age_txt, font_size=10)
