# Import StreamController modules
from src.backend.PluginManager.PluginBase import PluginBase
from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport

# Import python modules
import datetime
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request

import gi
from gi.repository import Gio, GLib
from PIL import Image as PILImage
from PIL import ImageDraw, ImageFont

from src.backend.DeckManagement.InputIdentifier import Input
import globals as gl

# Import actions
from .actions.Market.Market import Market
from .actions.SessionSlot.SessionSlot import SessionSlot
from .actions.UptimeKuma.UptimeKuma import UptimeKuma

STATE_DIR = os.path.expanduser("~/.claude/session-state")
ICONS_DIR = os.path.join(os.path.dirname(__file__), "assets", "icons")
# Un seul fichier de bandeau : son chemin ne change jamais dans la page, donc on
# peut le redessiner aussi souvent qu'on veut sans réécrire le JSON de la page
# (set_background_image sauvegarde le fichier + un backup à chaque appel).
STRIP = os.path.join(os.path.dirname(__file__), "assets", "strip.png")
TRANSCRIPTS_DIR = os.path.expanduser("~/.claude/projects")
BLOCK_SECONDS = 5 * 3600
FONT_BOLD = "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/dejavu/DejaVuSans.ttf"

STATE_FR = {
    "working": "Claude travaille",
    "needs_input": "Besoin de toi !",
    "waiting": "Tour terminé",
    "stale": "Session endormie",
}
STATE_ACCENT = {
    "working": (24, 118, 52, 255),
    "needs_input": (230, 126, 0, 255),
    "waiting": (46, 82, 130, 255),
    "stale": (90, 90, 90, 255),
}


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

        self._details_timer = None
        self._reset_strip_in_page_file()

        self.session_slot_holder = ActionHolder(
            plugin_base=self,
            action_base=SessionSlot,
            action_id="com_kiora_ClaudeSessions::SessionSlot",
            action_name="Claude Session Slot",
        )
        self.add_action_holder(self.session_slot_holder)

        self.kuma_holder = ActionHolder(
            plugin_base=self,
            action_base=UptimeKuma,
            action_id="com_kiora_ClaudeSessions::UptimeKuma",
            action_name="Uptime Kuma",
        )
        self.add_action_holder(self.kuma_holder)

        self.market_holder = ActionHolder(
            plugin_base=self,
            action_base=Market,
            action_id="com_kiora_ClaudeSessions::Market",
            action_name="Marchés (BTC / ETH / S&P 500)",
            action_support={
                Input.Key: ActionInputSupport.UNTESTED,
                Input.Dial: ActionInputSupport.SUPPORTED,
                Input.Touchscreen: ActionInputSupport.UNSUPPORTED,
            },
        )
        self.add_action_holder(self.market_holder)

        self.register(
            plugin_name="Claude Sessions",
            github_repo="https://github.com/kiora-tech/streamcontroller-claude-sessions",
            plugin_version="1.0.0",
            app_version="1.5.0",
        )

        self._usage = None
        self._usage_tick = 0
        self._kuma = None
        self.live_kuma = []
        try:
            self.kuma_icon = PILImage.open(os.path.join(ICONS_DIR, "kuma.png")).convert("RGBA")
        except Exception:
            self.kuma_icon = None
        self._market = []
        self._market_ts = 0.0
        self._market_config = None
        self._market_alert_state = {}
        self._market_alert_last = {}
        self.live_market = []

        self._strip_signature = None

        threading.Thread(target=self._refresh_usage, daemon=True).start()
        threading.Thread(target=self._refresh_kuma, daemon=True).start()
        threading.Thread(target=self._refresh_market, daemon=True).start()
        GLib.timeout_add_seconds(60, self._on_usage_tick)
        GLib.timeout_add_seconds(1, self._on_strip_tick)

    def _reset_strip_in_page_file(self) -> None:
        """Au démarrage, pointe le fond du bandeau sur notre fichier unique."""
        try:
            if not os.path.isfile(STRIP):
                PILImage.new("RGBA", (800, 100), (0, 0, 0, 0)).save(STRIP)
            path = os.path.join(gl.DATA_PATH, "pages", "home.json")
            with open(path) as f:
                page = json.load(f)
            bg = (
                page.setdefault("touchscreens", {})
                .setdefault("sd-plus", {})
                .setdefault("states", {})
                .setdefault("0", {})
                .setdefault("background", {})
            )
            if bg.get("image") != STRIP:
                bg["image"] = STRIP
                with open(path, "w") as f:
                    json.dump(page, f, indent=4)
        except Exception:
            pass

    def _refresh_strip(self) -> None:
        """Réaffiche le bandeau depuis STRIP, sans réécrire le JSON de la page."""
        try:
            identifier = Input.Touchscreen("sd-plus")
            for controller in gl.deck_manager.deck_controller:
                page = controller.active_page
                if page is None:
                    continue
                if page.get_background_image(identifier, 0) != STRIP:
                    page.set_background_image(identifier, 0, STRIP)
                    continue
                c_input = controller.get_input(identifier)
                if c_input is not None:
                    c_input.update()
        except Exception:
            pass

    def _flash_strip(self, img, duration: int = 5) -> None:
        """Occupe tout le bandeau avec une image pendant N secondes."""
        img.save(STRIP)
        self._set_market_hidden(True)
        self._strip_signature = None
        self._refresh_strip()
        if self._details_timer is not None:
            GLib.source_remove(self._details_timer)
        self._details_timer = GLib.timeout_add_seconds(duration, self._restore_strip)

    def _format_age(self, age: float) -> str:
        if age < 90:
            return f"{int(age)} s"
        if age < 3600:
            return f"{int(age / 60)} min"
        return f"{int(age / 3600)} h"

    def show_session_details(self, session: dict) -> None:
        """Affiche les détails d'une session sur le bandeau tactile pendant 5 s."""
        state = session.get("state", "waiting")
        age = time.time() - session.get("ts", 0)
        if age > 3 * 3600:
            state = "stale"

        img = PILImage.new("RGBA", (800, 100), (16, 16, 16, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 10, 100], fill=STATE_ACCENT.get(state, (90, 90, 90, 255)))
        try:
            font_big = ImageFont.truetype(FONT_BOLD, 36)
            font_small = ImageFont.truetype(FONT_REGULAR, 22)
        except OSError:
            font_big = font_small = ImageFont.load_default()

        draw.text((34, 10), session.get("project", "?"), font=font_big, fill=(255, 255, 255, 255))
        sub = f"{STATE_FR.get(state, state)}  ·  depuis {self._format_age(age)}  ·  {session.get('cwd', '')}"
        draw.text((34, 62), sub[:90], font=font_small, fill=(200, 200, 200, 255))
        self._flash_strip(img)

    def _restore_strip(self) -> bool:
        self._details_timer = None
        self._set_market_hidden(False)
        self._strip_signature = None
        self._render_status_strip()
        return False

    def remove_session(self, session_id: str) -> None:
        try:
            os.remove(os.path.join(STATE_DIR, f"{session_id}.json"))
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Usage réel du compte (mêmes données que /usage dans Claude Code)
    # ------------------------------------------------------------------

    _USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
    _CREDENTIALS = os.path.expanduser("~/.claude/.credentials.json")
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
        GLib.idle_add(self._render_status_strip)

    # ------------------------------------------------------------------
    # Uptime Kuma
    # ------------------------------------------------------------------

    _KUMA_CONFIG = os.path.expanduser("~/.claude/uptime-kuma.json")
    _KUMA_RE = re.compile(r'^monitor_status\{[^}]*monitor_name="([^"]+)"[^}]*\}\s+(\d+)', re.M)

    def _refresh_kuma(self) -> None:
        try:
            with open(self._KUMA_CONFIG) as f:
                cfg = json.load(f)
            import base64

            auth = base64.b64encode(f":{cfg['api_key']}".encode()).decode()
            req = urllib.request.Request(
                f"{cfg['url'].rstrip('/')}/metrics",
                headers={"Authorization": f"Basic {auth}"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                text = r.read().decode(errors="replace")
            up, down, down_names = 0, 0, []
            for name, value in self._KUMA_RE.findall(text):
                if value == "1":
                    up += 1
                elif value == "0":
                    down += 1
                    down_names.append(name)
            host = urllib.parse.urlsplit(cfg["url"]).netloc.rsplit("@", 1)[-1]
            self._kuma = {"up": up, "down": down, "down_names": down_names,
                          "host": host, "ts": time.time()}
        except Exception:
            self._kuma = None  # affichage « inconnu » plutôt que des données périmées
        GLib.idle_add(self._render_kuma_keys)

    def _render_kuma_keys(self) -> bool:
        for action in list(self.live_kuma):
            try:
                action._render()
            except Exception:
                pass
        return False

    def show_kuma_details(self) -> None:
        """Affiche le détail Uptime Kuma sur le bandeau pendant 5 s."""
        kuma = self._kuma
        img = PILImage.new("RGBA", (800, 100), (16, 16, 16, 255))
        draw = ImageDraw.Draw(img)
        try:
            font_big = ImageFont.truetype(FONT_BOLD, 30)
            font_small = ImageFont.truetype(FONT_REGULAR, 20)
        except OSError:
            font_big = font_small = ImageFont.load_default()

        if kuma is None:
            draw.rectangle([0, 0, 10, 100], fill=(120, 120, 120, 255))
            draw.text((34, 32), "Uptime Kuma injoignable", font=font_big, fill=(255, 255, 255, 255))
        elif kuma["down"] == 0:
            draw.rectangle([0, 0, 10, 100], fill=(24, 118, 52, 255))
            draw.text((34, 14), "Tout est en ligne ✓", font=font_big, fill=(120, 220, 140, 255))
            draw.text((34, 58), f"{kuma['up']} services surveillés — {kuma['host']}",
                      font=font_small, fill=(190, 190, 190, 255))
        else:
            draw.rectangle([0, 0, 10, 100], fill=(200, 40, 35, 255))
            draw.text((34, 10), f"{kuma['down']} service(s) HS !", font=font_big,
                      fill=(255, 120, 110, 255))
            names = "  ·  ".join(kuma["down_names"][:4])
            if len(kuma["down_names"]) > 4:
                names += f"  (+{len(kuma['down_names']) - 4})"
            draw.text((34, 58), names[:88], font=font_small, fill=(230, 230, 230, 255))

        self._flash_strip(img)

    # ------------------------------------------------------------------
    # Marchés (BTC / ETH / S&P 500) — tuile sur la molette 4 du bandeau
    # ------------------------------------------------------------------

    _MARKET_CONFIG = os.path.expanduser("~/.claude/market.json")
    _MARKET_DEFAULTS = {
        "alert_pct": 2.0,
        "poll_seconds": 120,
        "cycle_seconds": 4,
        "notify": False,
        "assets": [
            {"label": "BTC", "source": "coingecko", "id": "bitcoin", "currency": "EUR"},
            {"label": "ETH", "source": "coingecko", "id": "ethereum", "currency": "EUR"},
            {"label": "S&P 500", "source": "yahoo", "id": "^GSPC", "currency": "PTS"},
        ],
    }
    _MARKET_STALE_AFTER = 15 * 60
    _MARKET_ALERT_COOLDOWN = 3600
    _MARKET_UA = "Mozilla/5.0 (X11; Linux x86_64) StreamController-ClaudeSessions"
    _MARKET_UP = (70, 190, 100, 255)
    _MARKET_DOWN = (225, 75, 65, 255)
    _MARKET_FLAT = (185, 185, 185, 255)
    _MARKET_BG = {
        None: (26, 26, 28, 255),
        "up": (16, 66, 38, 255),
        "down": (86, 26, 24, 255),
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
        triggered = []
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
                    triggered.append(item)
            self._market_alert_state[label] = state

        self._market = results
        self._market_ts = now
        GLib.idle_add(self._render_market_tiles)
        if triggered:
            GLib.idle_add(self._on_market_alert, triggered)

    def _render_market_tiles(self) -> bool:
        for action in list(self.live_market):
            try:
                action._render(force=True)
            except Exception:
                pass
        return False

    def _on_market_alert(self, triggered: list) -> bool:
        self.show_market_details(highlight=[item["label"] for item in triggered], duration=8)
        if (self._market_config or {}).get("notify"):
            threading.Thread(target=self._notify_market, args=(triggered,), daemon=True).start()
        return False

    def _notify_market(self, triggered: list) -> None:
        body = "\n".join(
            f"{item['label']} {self._fmt_pct(item.get('pct'))}  ({self._fmt_price(item)})"
            for item in triggered
        )
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

    def market_cycle_seconds(self) -> int:
        cfg = self._market_config or self._MARKET_DEFAULTS
        try:
            return max(1, int(cfg.get("cycle_seconds", 4)))
        except (TypeError, ValueError):
            return 4

    def refresh_market_now(self) -> None:
        threading.Thread(target=self._refresh_market, daemon=True).start()

    def _set_market_hidden(self, hidden: bool) -> None:
        """Efface (ou rétablit) la tuile pendant qu'un détail occupe le bandeau."""
        for action in list(self.live_market):
            try:
                action.set_hidden(hidden)
            except Exception:
                pass

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

    def _market_color(self, pct) -> tuple:
        if pct is None:
            return self._MARKET_FLAT
        return self._MARKET_UP if pct >= 0 else self._MARKET_DOWN

    def render_market_tile(self, asset, index: int, count: int):
        """Tuile 200×100 affichée dans la zone de la molette."""
        width, height = 200, 100
        try:
            font_label = ImageFont.truetype(FONT_BOLD, 18)
            font_price = ImageFont.truetype(FONT_BOLD, 26)
            font_pct = ImageFont.truetype(FONT_BOLD, 19)
            font_tiny = ImageFont.truetype(FONT_REGULAR, 13)
        except OSError:
            font_label = font_price = font_pct = font_tiny = ImageFont.load_default()

        if asset is None:
            img = PILImage.new("RGBA", (width, height), self._MARKET_BG[None])
            draw = ImageDraw.Draw(img)
            draw.text((14, 40), "marchés…", font=font_tiny, fill=(150, 150, 150, 255))
            return img

        alert = asset.get("alert")
        stale = asset.get("stale")
        pct = asset.get("pct")
        img = PILImage.new("RGBA", (width, height), self._MARKET_BG.get(alert, self._MARKET_BG[None]))
        draw = ImageDraw.Draw(img)

        accent = self._market_color(pct) if not stale else self._MARKET_FLAT
        draw.rectangle([0, 0, 5, height], fill=accent)

        text_color = (255, 255, 255, 255) if not stale else (150, 150, 150, 255)
        draw.text((16, 5), str(asset.get("label", "?"))[:9], font=font_label, fill=text_color)
        draw.text((16, 27), self._fmt_price(asset), font=font_price, fill=text_color)

        arrow = "▲" if (pct or 0) > 0 else ("▼" if (pct or 0) < 0 else "•")
        draw.text((16, 63), f"{arrow} {self._fmt_pct(pct)}", font=font_pct,
                  fill=accent if not stale else self._MARKET_FLAT)

        if stale:
            draw.text((width - 46, 8), "hors ligne", font=font_tiny, fill=(150, 120, 60, 255))

        # Points du cycle : indique quel actif est affiché
        for i in range(count):
            x = width - 12 - (count - 1 - i) * 12
            filled = i == index
            draw.ellipse(
                [x - 4, height - 12, x + 2, height - 6],
                fill=(235, 235, 235, 255) if filled else (95, 95, 95, 255),
            )
        return img

    def show_market_details(self, highlight: list = None, duration: int = 5) -> None:
        """Détail des trois actifs sur toute la largeur du bandeau."""
        assets = self.get_market_assets()
        highlight = highlight or []

        img = PILImage.new("RGBA", (800, 100), (16, 16, 16, 255))
        draw = ImageDraw.Draw(img)
        try:
            font_label = ImageFont.truetype(FONT_BOLD, 19)
            font_price = ImageFont.truetype(FONT_BOLD, 28)
            font_pct = ImageFont.truetype(FONT_BOLD, 19)
            font_tiny = ImageFont.truetype(FONT_REGULAR, 15)
        except OSError:
            font_label = font_price = font_pct = font_tiny = ImageFont.load_default()

        if not assets:
            draw.text((30, 36), "Cours indisponibles", font=font_price, fill=(200, 200, 200, 255))
        else:
            column = 800 // max(1, len(assets))
            for i, item in enumerate(assets):
                x = i * column + 22
                pct = item.get("pct")
                accent = self._market_color(pct) if not item.get("stale") else self._MARKET_FLAT
                draw.rectangle([x - 12, 12, x - 7, 88], fill=accent)
                label = str(item.get("label", "?"))
                if item["label"] in highlight:
                    label += "  ⚠"
                draw.text((x, 6), label, font=font_label, fill=(255, 255, 255, 255))
                draw.text((x, 28), self._fmt_price(item), font=font_price, fill=(255, 255, 255, 255))
                arrow = "▲" if (pct or 0) > 0 else ("▼" if (pct or 0) < 0 else "•")
                draw.text((x, 66), f"{arrow} {self._fmt_pct(pct)}", font=font_pct, fill=accent)

            if self._market_ts:
                age = int(time.time() - self._market_ts)
                stamp = f"maj il y a {age} s" if age < 90 else f"maj il y a {age // 60} min"
                draw.text((800 - 12 - draw.textlength(stamp, font=font_tiny), 8), stamp,
                          font=font_tiny, fill=(130, 130, 130, 255))

        self._flash_strip(img, duration=duration)

    def _prune_sessions(self) -> None:
        """Ménage périodique des sessions mortes, exécuté côté hôte."""
        try:
            subprocess.run(
                [
                    "flatpak-spawn",
                    "--host",
                    os.path.expanduser("~/.claude/hooks/streamdeck-state.py"),
                    "--prune",
                ],
                capture_output=True,
                timeout=15,
            )
        except Exception:
            pass

    def _on_usage_tick(self) -> bool:
        self._usage_tick += 1
        threading.Thread(target=self._prune_sessions, daemon=True).start()
        threading.Thread(target=self._refresh_kuma, daemon=True).start()

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

    @staticmethod
    def _pct_color(pct, pace=None) -> tuple:
        if pct is None:
            return (190, 190, 190, 255)
        if pct >= 90:
            return (220, 60, 50, 255)
        if pct >= (70 if pace is None else min(pace, 90)):
            return (230, 150, 0, 255)
        return (70, 190, 100, 255)

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

    def _draw_gauge(self, draw, x, y, width, pct, color=None, tick=None) -> None:
        draw.rounded_rectangle([x, y, x + width, y + 10], radius=5, fill=(60, 60, 60, 255))
        if pct:
            fill_w = max(10, int(width * min(pct, 100) / 100))
            draw.rounded_rectangle(
                [x, y, x + fill_w, y + 10], radius=5, fill=color or self._pct_color(pct)
            )
        if tick:
            tx = x + int(width * min(tick, 100) / 100)
            draw.rectangle([tx - 1, y - 3, tx + 1, y + 13], fill=(235, 235, 235, 255))

    def _usage_slides(self) -> list:
        """Les deux vues d'usage qui défilent l'une après l'autre."""
        usage = self._usage or {}

        def reset_relative(ts):
            remaining = max(0, ts - time.time())
            h, m = int(remaining // 3600), int(remaining % 3600 // 60)
            return f"réinit. dans {h} h {m:02d}" if h else f"réinit. dans {m} min"

        def reset_absolute(ts):
            dt = datetime.datetime.fromtimestamp(ts)
            return f"réinit. {self._JOURS[dt.weekday()]} {dt.strftime('%H:%M')}"

        return [
            {
                "title": "Session actuelle",
                "pct": usage.get("session_pct"),
                "reset": reset_relative(usage["session_reset"]) if usage.get("session_reset") else "",
            },
            {
                "title": "Semaine · tous modèles",
                "pct": usage.get("week_pct"),
                "reset": reset_absolute(usage["week_reset"]) if usage.get("week_reset") else "",
                "pace": self._week_pace_pct(),
            },
        ]

    def _on_strip_tick(self) -> bool:
        """Fait défiler l'usage au même rythme que les cours."""
        if self._details_timer is None:
            self._render_status_strip()
        return True

    def _render_status_strip(self) -> bool:
        if self._details_timer is not None:
            return False  # un détail occupe le bandeau, on ne l'écrase pas

        slides = self._usage_slides()
        index = int(time.time() / self.market_cycle_seconds()) % len(slides)
        slide = slides[index]

        accent = self._pct_color(slide["pct"], slide.get("pace"))
        signature = (index, slide["pct"], slide["reset"], accent, self._usage is None)
        if signature == self._strip_signature:
            return False
        self._strip_signature = signature

        img = PILImage.new("RGBA", (800, 100), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        try:
            font_title = ImageFont.truetype(FONT_BOLD, 20)
            font_big = ImageFont.truetype(FONT_BOLD, 42)
            font_small = ImageFont.truetype(FONT_REGULAR, 17)
        except OSError:
            font_title = font_big = font_small = ImageFont.load_default()

        if self._usage is None:
            draw.text((28, 38), "chargement de l'usage…", font=font_small, fill=(190, 190, 190, 255))
        else:
            pct = slide["pct"]
            draw.rectangle([16, 12, 21, 88], fill=accent)
            draw.text((40, 6), slide["title"], font=font_title, fill=(255, 255, 255, 255))
            draw.text((40, 28), f"{round(pct)} %" if pct is not None else "?", font=font_big,
                      fill=accent)
            self._draw_gauge(draw, 186, 48, 300, pct, color=accent, tick=slide.get("pace"))
            if slide["reset"]:
                draw.text((40, 76), slide["reset"], font=font_small, fill=(180, 180, 180, 255))

            # Points du cycle, comme sur la tuile des cours
            for i in range(len(slides)):
                x = 560 - (len(slides) - 1 - i) * 14
                draw.ellipse([x - 4, 84, x + 2, 90],
                             fill=(235, 235, 235, 255) if i == index else (95, 95, 95, 255))

        img.save(STRIP)
        self._refresh_strip()
        return False

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
