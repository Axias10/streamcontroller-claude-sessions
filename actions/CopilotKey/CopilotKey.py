# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase


class CopilotKey(ActionBase):
    """Touche unique : activité récente de GitHub Copilot CLI.

    Pas de hooks côté Copilot CLI (contrairement à Claude Code) : l'état vient
    de la date de dernière écriture du fichier d'export OpenTelemetry, qui
    n'est mis à jour qu'une fois un échange terminé. C'est donc un indicateur
    "actif récemment", pas un vrai statut travail/attente en direct.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_signature = None

    def on_ready(self) -> None:
        if self not in self.plugin_base.live_copilot:
            self.plugin_base.live_copilot.append(self)
        self._last_signature = None
        self._render()

    def on_remove(self) -> None:
        try:
            self.plugin_base.live_copilot.remove(self)
        except ValueError:
            pass

    def on_tick(self) -> None:
        self._render()

    def _render(self, force: bool = False) -> None:
        active = self.plugin_base.get_copilot_active()
        if active == self._last_signature and not force:
            return
        self._last_signature = active

        self.set_background_color([24, 118, 52, 255] if active else [45, 45, 45, 255])
        self.set_top_label("Copilot", font_size=12)
        self.set_center_label("actif" if active else "", font_size=12)
