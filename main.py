# Import StreamController modules
from src.backend.PluginManager.PluginBase import PluginBase
from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport

# Import python modules
import datetime
import json
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request

import gi
from gi.repository import Gio, GLib
from PIL import Image as PILImage

from src.backend.DeckManagement.InputIdentifier import Input

# Import actions
from .actions.CopilotKey.CopilotKey import CopilotKey
from .actions.Market.Market import MarketKey
from .actions.SessionSlot.SessionSlot import SessionSlot
from .actions.UsageKey.UsageKey import UsageKey

STATE_DIR = os.path.expanduser("~/.claude/session-state")
WINDOWS_STATE_DIR = "/mnt/c/Users/Justin/.claude/session-state"
if os.path.isdir(os.path.dirname(WINDOWS_STATE_DIR)):
    STATE_DIR = WINDOWS_STATE_DIR
ICONS_DIR = os.path.join(os.path.dirname(__file__), "assets", "icons")

COPILOT_OTEL_PATH = "/mnt/c/Users/Justin/.copilot/otel.jsonl"
COPILOT_ACTIVE_AFTER = 30  # secondes après le dernier échange écrit dans le fichier OTel


class ClaudeSessionsPlugin(PluginBase):
    def __init__(self):
        super().__init__()

        self._states_cache = []
        self._states_cache_ts = 0.0
        self.live_slots = []
        self._start_state_monitor()

        self.state_icons = {}
        for state in ("working", "needs_input", "waiting", "stale"):
            try:
                self.state_icons[state] = PILImage.open(
                    os.path.join(ICONS_DIR, f"{state}.png")
                ).convert("RGBA")
            except Exception:
                self.state_icons[state] = None

        self.session_slot_holder = ActionHolder(
            plugin_base=self,
            action_base=SessionSlot,
            action_id="com_kiora_ClaudeSessions::SessionSlot",
            action_name="Claude Session Slot",
        )
        self.add_action_holder(self.session_slot_holder)

        self.usage_holder = ActionHolder(
            plugin_base=self,
            action_base=UsageKey,
            action_id="com_kiora_ClaudeSessions::UsageKey",
            action_name="Claude Usage",
        )
        self.add_action_holder(self.usage_holder)

        self.market_holder = ActionHolder(
            plugin_base=self,
            action_base=MarketKey,
            action_id="com_kiora_ClaudeSessions::Market",
            action_name="Marché (touche fixe)",
            action_support={
                Input.Key: ActionInputSupport.SUPPORTED,
            },
        )
        self.add_action_holder(self.market_holder)

        self.copilot_holder = ActionHolder(
            plugin_base=self,
            action_base=CopilotKey,
            action_id="com_kiora_ClaudeSessions::CopilotKey",
            action_name="GitHub Copilot CLI (actif récemment)",
        )
        self.add_action_holder(self.copilot_holder)
        self.live_copilot = []

        self.register(
            plugin_name="Claude Sessions",
            github_repo="https://github.com/kiora-tech/streamcontroller-claude-sessions",
            plugin_version="1.0.0",
            app_version="1.5.0",
        )

        self._usage = None
        self._usage_tick = 0
        self.live_usage = []

        self._market = []
        self._market_ts = 0.0
        self._market_config = None
        self._market_alert_state = {}
        self._market_alert_last = {}
        self.live_market = []

        threading.Thread(target=self._refresh_usage, daemon=True).start()
        threading.Thread(target=self._refresh_market, daemon=True).start()
        GLib.timeout_add_seconds(60, self._on_usage_tick)
        GLib.timeout_add_seconds(5, self._render_copilot_keys)

    def remove_session(self, session_id: str) -> None:
        try:
            os.remove(os.path.join(STATE_DIR, f"{session_id}.json"))
        except OSError:
            pass

    # ------------------------------------------------------------------
    # GitHub Copilot CLI — pas de hooks, on regarde juste la fraîcheur du
    # fichier d'export OpenTelemetry (COPILOT_OTEL_FILE_EXPORTER_PATH).
    # ------------------------------------------------------------------

    def get_copilot_active(self) -> bool:
        try:
            age = time.time() - os.path.getmtime(COPILOT_OTEL_PATH)
        except OSError:
            return False
        return age < COPILOT_ACTIVE_AFTER

    def _render_copilot_keys(self) -> bool:
        for action in list(self.live_copilot):
            try:
                action._render()
            except Exception:
                pass
        return True

    # ------------------------------------------------------------------
    # Usage réel du compte (mêmes données que /usage dans Claude Code)
    # ------------------------------------------------------------------

    _USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
    _CREDENTIALS = (
        "/mnt/c/Users/Justin/.claude/.credentials.json"
        if os.path.isfile("/mnt/c/Users/Justin/.claude/.credentials.json")
        else os.path.expanduser("~/.claude/.credentials.json")
    )
    _JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]

    @staticmethod
    def _parse_iso(raw) -> float | None:
        try:
            return datetime.datetime.fromisoformat(str(raw)).timestamp()
        except (ValueError, TypeError):
            return None

    def _refresh_usage(self) -> None:
        try:
            with open(self._CREDENTIALS) as f:
                token = json.load(f)["claudeAiOauth"]["accessToken"]
            req = urllib.request.Request(
                self._USAGE_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "anthropic-beta": "oauth-2025-04-20",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.load(r)
            five_hour = data.get("five_hour") or {}
            seven_day = data.get("seven_day") or {}
            self._usage = {
                "session_pct": five_hour.get("utilization"),
                "session_reset": self._parse_iso(five_hour.get("resets_at")),
                "week_pct": seven_day.get("utilization"),
                "week_reset": self._parse_iso(seven_day.get("resets_at")),
            }
        except Exception:
            pass  # on garde les dernières valeurs connues
        GLib.idle_add(self._render_usage_keys)

    @staticmethod
    def _pct_color(pct, pace=None) -> list:
        if pct is None:
            return [45, 45, 45, 255]
        if pct >= 90:
            return [220, 60, 50, 255]
        if pct >= (70 if pace is None else min(pace, 90)):
            return [230, 150, 0, 255]
        return [24, 118, 52, 255]

    def _week_pace_pct(self) -> float | None:
        """Budget linéaire de la semaine : au jour N de la fenêtre, N × 100/7 %."""
        usage = self._usage or {}
        reset = usage.get("week_reset")
        if not reset:
            return None
        elapsed = 7 * 86400 - (reset - time.time())
        if elapsed <= 0:
            return None
        day = min(7, int(elapsed // 86400) + 1)
        return day * 100 / 7

    def usage_slides(self) -> list:
        """Les deux vues d'usage qui alternent sur la touche."""
        usage = self._usage or {}

        def reset_relative(ts):
            remaining = max(0, ts - time.time())
            h, m = int(remaining // 3600), int(remaining % 3600 // 60)
            return f"{h}h{m:02d}" if h else f"{m}min"

        def reset_absolute(ts):
            dt = datetime.datetime.fromtimestamp(ts)
            return f"{self._JOURS[dt.weekday()]} {dt.strftime('%H:%M')}"

        return [
            {
                "title": "Session",
                "pct": usage.get("session_pct"),
                "reset": reset_relative(usage["session_reset"]) if usage.get("session_reset") else "",
            },
            {
                "title": "Semaine",
                "pct": usage.get("week_pct"),
                "reset": reset_absolute(usage["week_reset"]) if usage.get("week_reset") else "",
                "pace": self._week_pace_pct(),
            },
        ]

    def _render_usage_keys(self) -> bool:
        """Callback GLib.idle_add : force le rendu après une nouvelle donnée."""
        for action in list(self.live_usage):
            try:
                action._render(force=True)
            except Exception:
                pass
        return False

    # ------------------------------------------------------------------
    # Marchés — une touche fixe par actif (XAUUSD, Nasdaq, CAC 40, FTSE,
    # S&P 500, BTC par défaut)
    # ------------------------------------------------------------------

    _MARKET_CONFIG = os.path.expanduser("~/.claude/market.json")
    _MARKET_DEFAULTS = {
        "alert_pct": 2.0,
        "poll_seconds": 120,
        "notify": False,
        "assets": [
            {"label": "XAUUSD", "source": "yahoo", "id": "GC=F", "currency": "USD"},
            {"label": "Nasdaq", "source": "yahoo", "id": "^IXIC", "currency": "PTS"},
            {"label": "CAC 40", "source": "yahoo", "id": "^FCHI", "currency": "PTS"},
            {"label": "FTSE 100", "source": "yahoo", "id": "^FTSE", "currency": "PTS"},
            {"label": "S&P 500", "source": "yahoo", "id": "^GSPC", "currency": "PTS"},
            {"label": "BTC", "source": "coingecko", "id": "bitcoin", "currency": "EUR"},
        ],
    }
    _MARKET_STALE_AFTER = 15 * 60
    _MARKET_ALERT_COOLDOWN = 3600
    _MARKET_UA = "Mozilla/5.0 (X11; Linux x86_64) StreamController-ClaudeSessions"
    _MARKET_UP = [70, 190, 100, 255]
    _MARKET_DOWN = [225, 75, 65, 255]
    _MARKET_FLAT = [45, 45, 45, 255]
    _MARKET_BG = {
        None: [30, 30, 30, 255],
        "up": [16, 90, 48, 255],
        "down": [110, 30, 28, 255],
    }

    def _load_market_config(self) -> dict:
        """Conf utilisateur, recréée avec les valeurs par défaut si absente."""
        cfg = dict(self._MARKET_DEFAULTS)
        try:
            with open(self._MARKET_CONFIG) as f:
                cfg.update(json.load(f))
        except FileNotFoundError:
            try:
                with open(self._MARKET_CONFIG, "w") as f:
                    json.dump(self._MARKET_DEFAULTS, f, indent=2, ensure_ascii=False)
            except OSError:
                pass
        except Exception:
            pass
        if not cfg.get("assets"):
            cfg["assets"] = self._MARKET_DEFAULTS["assets"]
        return cfg

    def _fetch_coingecko(self, assets: list) -> dict:
        ids = ",".join(sorted({a["id"] for a in assets}))
        currencies = ",".join(sorted({str(a.get("currency", "EUR")).lower() for a in assets}))
        url = (
            "https://api.coingecko.com/api/v3/simple/price"
            f"?ids={urllib.parse.quote(ids)}"
            f"&vs_currencies={urllib.parse.quote(currencies)}&include_24hr_change=true"
        )
        req = urllib.request.Request(url, headers={"User-Agent": self._MARKET_UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)

        out = {}
        for asset in assets:
            entry = data.get(asset["id"]) or {}
            currency = str(asset.get("currency", "EUR")).lower()
            price = entry.get(currency)
            if price is not None:
                out[asset["id"]] = (price, entry.get(f"{currency}_24h_change"))
        return out

    def _fetch_yahoo(self, asset: dict) -> tuple:
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{urllib.parse.quote(asset['id'])}?interval=1d&range=5d"
        )
        req = urllib.request.Request(url, headers={"User-Agent": self._MARKET_UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        meta = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        previous = meta.get("chartPreviousClose") or meta.get("previousClose")
        pct = (price / previous - 1) * 100 if price is not None and previous else None
        return price, pct

    def _refresh_market(self) -> None:
        cfg = self._load_market_config()
        self._market_config = cfg
        assets = cfg["assets"]
        previous = {item["label"]: item for item in self._market}

        crypto = [a for a in assets if a.get("source") == "coingecko"]
        quotes = {}
        if crypto:
            try:
                quotes = self._fetch_coingecko(crypto)
            except Exception:
                quotes = {}

        now = time.time()
        results = []
        for asset in assets:
            price = pct = None
            if asset.get("source") == "coingecko":
                got = quotes.get(asset["id"])
                if got:
                    price, pct = got
            else:
                try:
                    price, pct = self._fetch_yahoo(asset)
                except Exception:
                    price = pct = None

            label = asset.get("label", asset.get("id", "?"))
            if price is None:
                # échec réseau : on garde la dernière valeur connue, elle vieillira
                old = previous.get(label)
                if old is None:
                    continue
                results.append(dict(old))
                continue

            results.append({
                "label": label,
                "currency": str(asset.get("currency", "EUR")).upper(),
                "price": price,
                "pct": pct,
                "ts": now,
                "stale": False,
                "alert": self._market_alert_state.get(label),
            })

        alert_pct = float(cfg.get("alert_pct", 2.0) or 2.0)
        release = alert_pct * 0.75  # hystérésis : il faut retomber sous ce seuil pour réarmer
        for item in results:
            label = item["label"]
            pct = item.get("pct")
            state = self._market_alert_state.get(label)
            if pct is None:
                state = None
            elif pct >= alert_pct:
                state = "up"
            elif pct <= -alert_pct:
                state = "down"
            elif abs(pct) < release:
                state = None
            item["alert"] = state

            if state and state != self._market_alert_state.get(label):
                if now - self._market_alert_last.get(label, 0) > self._MARKET_ALERT_COOLDOWN:
                    self._market_alert_last[label] = now
                    if cfg.get("notify"):
                        threading.Thread(target=self._notify_market, args=(item,), daemon=True).start()
            self._market_alert_state[label] = state

        self._market = results
        self._market_ts = now
        GLib.idle_add(self._render_market_keys)

    def _notify_market(self, item: dict) -> None:
        body = f"{item['label']} {self._fmt_pct(item.get('pct'))}  ({self._fmt_price(item)})"
        try:
            subprocess.run(
                ["flatpak-spawn", "--host", "notify-send", "-a", "Stream Deck",
                 "Alerte marché", body],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass

    def get_market_assets(self) -> list:
        now = time.time()
        for item in self._market:
            item["stale"] = (now - item.get("ts", 0)) > self._MARKET_STALE_AFTER
        return self._market

    def refresh_market_now(self) -> None:
        threading.Thread(target=self._refresh_market, daemon=True).start()

    def _render_market_keys(self) -> bool:
        for action in list(self.live_market):
            try:
                action._render(force=True)
            except Exception:
                pass
        return False

    @staticmethod
    def _fmt_number(value) -> str:
        if value is None:
            return "—"
        if abs(value) >= 1000:
            return f"{value:,.0f}".replace(",", " ")
        if abs(value) >= 10:
            return f"{value:,.1f}".replace(",", " ").replace(".", ",")
        return f"{value:.3f}".replace(".", ",")

    def _fmt_price(self, item: dict) -> str:
        suffixes = {"EUR": " €", "USD": " $", "GBP": " £", "PTS": "", "": ""}
        currency = str(item.get("currency", "")).upper()
        return self._fmt_number(item.get("price")) + suffixes.get(currency, f" {currency}")

    @staticmethod
    def _fmt_pct(pct) -> str:
        if pct is None:
            return "—"
        return f"{pct:+.2f} %".replace(".", ",")

    def _market_color(self, pct) -> list:
        if pct is None:
            return self._MARKET_FLAT
        return self._MARKET_UP if pct >= 0 else self._MARKET_DOWN

    _PRUNE_AFTER = 24 * 3600  # sessions orphelines (SessionEnd jamais reçu, crash…)

    def _prune_sessions(self) -> None:
        """Ménage périodique des sessions mortes ou corrompues."""
        now = time.time()
        try:
            entries = os.listdir(STATE_DIR)
        except FileNotFoundError:
            return
        for fn in entries:
            if not fn.endswith(".json"):
                continue
            path = os.path.join(STATE_DIR, fn)
            try:
                with open(path) as f:
                    ts = json.load(f).get("ts", 0)
                if now - ts < self._PRUNE_AFTER:
                    continue
            except Exception:
                pass  # fichier corrompu : on le retire aussi
            try:
                os.remove(path)
            except OSError:
                pass

    def _on_usage_tick(self) -> bool:
        self._usage_tick += 1
        threading.Thread(target=self._prune_sessions, daemon=True).start()

        cfg = self._market_config or self._MARKET_DEFAULTS
        try:
            poll = max(60, int(cfg.get("poll_seconds", 120)))
        except (TypeError, ValueError):
            poll = 120
        if time.time() - self._market_ts >= poll - 5:
            threading.Thread(target=self._refresh_market, daemon=True).start()

        if self._usage_tick % 2 == 0:
            threading.Thread(target=self._refresh_usage, daemon=True).start()
        return True

    def _start_state_monitor(self) -> None:
        """Actualisation temps réel : inotify sur le dossier d'états des sessions."""
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            gfile = Gio.File.new_for_path(STATE_DIR)
            self._state_monitor = gfile.monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self._state_monitor.connect("changed", self._on_state_dir_changed)
        except Exception:
            self._state_monitor = None

    def _on_state_dir_changed(self, monitor, gfile, other_file, event_type) -> None:
        basename = gfile.get_basename() or ""
        if basename.endswith(".tmp"):
            return
        self._states_cache_ts = 0.0
        for slot in list(self.live_slots):
            try:
                slot._render()
            except Exception:
                pass

    def get_sessions(self) -> list:
        """Liste des sessions Claude Code triées par ancienneté (cache 1 s)."""
        now = time.time()
        if now - self._states_cache_ts < 1.0:
            return self._states_cache

        sessions = []
        try:
            for fn in os.listdir(STATE_DIR):
                if not fn.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(STATE_DIR, fn)) as f:
                        sessions.append(json.load(f))
                except Exception:
                    continue
        except FileNotFoundError:
            pass

        sessions.sort(key=lambda s: s.get("first_seen", 0))
        self._states_cache = sessions
        self._states_cache_ts = now
        return sessions
