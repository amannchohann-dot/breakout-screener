#!/usr/bin/env python3
"""
Polymarket BTC 5-Min Up/Down — PRE-BLOCK Bot
═══════════════════════════════════════════════════════════════

Strategie: Mean-Reversion-Signale auf 5m-Candles VOR Block-Start.
Komplementär zum bestehenden M1-Bot (Trend-Following nach 1 Min).

Trade-Logik:
  1. Bei T = Block-Start + 5s (z.B. 14:15:05 UTC) wachen wir auf
  2. Hol letzte 5m-Candles von Binance
  3. Match Pre-Block-Setups (Streak/Body) auf gerade-abgeschlossenen Candle
  4. Wenn Setup aktiv → P_Up berechnen → Edge gegen Polymarket-Ask
  5. Wenn Edge ≥ MIN_EDGE → Order platzieren

Edges aus btc_5m_edge_research/41_polymarket_profitability.csv (OOS-validiert).

Run:
  python3 pre_block_bot.py        # Paper-Mode default
  DRY_RUN=false python3 pre_block_bot.py  # Live (vorsichtig!)
"""
import os, sys, time, json, signal, traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Wiederverwende Klassen aus dem bestehenden Bot
from bot import (
    Config, BinanceData, PythData, MarketFinder, OrderExecutor,
    log, send_telegram, _acquire_lock, _release_lock,
)
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds


# ═══════════════════════════════════════════════════════════════
# PRE-BLOCK SETUP-DEFINITIONEN (aus OOS-Research)
# ═══════════════════════════════════════════════════════════════
# Format: (Name, Predicate, P_Up, Side, ExpectedEdgePP_at_52c)
# Predicate Args: green (0/1), streak_len (int), body_abs (%), body_pct_max_in_streak,
#                 hour_utc (0-23), is_xl_body (bool)

XL_BODY_THRESHOLD_PCT = 0.13  # 80. Perzentil aus historischen 5m-Daten

def _last_n_streak_xl(candles, n_lookback=5):
    """Berechnet aus den letzten N abgeschlossenen Candles:
       streak_len, was die Farbe ist, ob letzter Body XL ist, Stunde."""
    if len(candles) < n_lookback:
        return None
    last = candles[-1]
    color = 1 if last["close"] > last["open"] else 0
    body_pct = (last["close"] - last["open"]) / last["open"] * 100
    body_abs = abs(body_pct)
    is_xl = body_abs >= XL_BODY_THRESHOLD_PCT
    # Streak: wie viele in Folge dieselbe Farbe wie letzte
    streak = 1
    for c in reversed(candles[:-1]):
        c_color = 1 if c["close"] > c["open"] else 0
        if c_color == color:
            streak += 1
        else:
            break
    hour = last["close_time"].hour  # UTC
    return {
        "color": color,
        "streak_len": streak,
        "body_abs": body_abs,
        "body_pct": body_pct,
        "is_xl_body": is_xl,
        "hour_utc": hour,
        "candle_close": last["close"],
        "candle_open": last["open"],
    }


SETUPS = [
    # ═════════════════════════════════════════════════════════════
    # TIER 1 — Top-Edges (|p_up − 0.5| ≥ 5.5pp, Backtest-Hitrate ≥55.5%)
    # 2026-05-14: Live-Hitrate war ~44% mit allen 18 Setups (Backtest 53-57%).
    # Verdacht: schwache Setups (p_up ~0.54) bringen nur Rauschen → disabled.
    # ═════════════════════════════════════════════════════════════
    # DOWN-Setups (2026-05-17): in BTC-Up-Regime systematisch unprofitabel.
    # Live: 56 DOWN-trades, 37.5% Acc, -$41.17 vs UP 73 trades, 43.8%, +$36.28
    # → DEAKTIVIERT bis Trend dreht.
    {"name": "S5+G_LateNight_DOWN", "enabled": False,
     "desc": "5+ grüne Candles in 22-23 UTC → mean revert DOWN",
     "p_up": 0.396, "side": "DOWN",
     "check": lambda f: f["color"]==1 and f["streak_len"]>=5 and 22 <= f["hour_utc"] <= 23},

    {"name": "S5+R_Europe_UP", "enabled": True,
     "desc": "5+ rote Candles in 07-12 UTC → mean revert UP",
     "p_up": 0.573, "side": "UP",
     "check": lambda f: f["color"]==0 and f["streak_len"]>=5 and 7 <= f["hour_utc"] <= 12},

    {"name": "S4+G_XL_DOWN", "enabled": False,
     "desc": "4+ grüne Candles & letzter XL-Body → mean revert DOWN",
     "p_up": 0.429, "side": "DOWN",
     "check": lambda f: f["color"]==1 and f["streak_len"]>=4 and f["is_xl_body"]},

    {"name": "S4+G_Europe_DOWN", "enabled": False,
     "desc": "4+ grüne Candles in 07-12 UTC → mean revert DOWN",
     "p_up": 0.432, "side": "DOWN",
     "check": lambda f: f["color"]==1 and f["streak_len"]>=4 and 7 <= f["hour_utc"] <= 12},

    {"name": "S4+R_Europe_UP", "enabled": True,
     "desc": "4+ rote Candles in 07-12 UTC → mean revert UP",
     "p_up": 0.563, "side": "UP",
     "check": lambda f: f["color"]==0 and f["streak_len"]>=4 and 7 <= f["hour_utc"] <= 12},

    {"name": "S4+G_LateNight_DOWN", "enabled": False,
     "desc": "4+ grüne Candles in 22-23 UTC → mean revert DOWN",
     "p_up": 0.436, "side": "DOWN",
     "check": lambda f: f["color"]==1 and f["streak_len"]>=4 and 22 <= f["hour_utc"] <= 23},

    {"name": "S3+R_XL_UP", "enabled": True,
     "desc": "3+ rote Candles & letzter XL-Body → mean revert UP",
     "p_up": 0.558, "side": "UP",
     "check": lambda f: f["color"]==0 and f["streak_len"]>=3 and f["is_xl_body"]},

    {"name": "S3+G_XL_DOWN", "enabled": False,
     "desc": "3+ grüne Candles & letzter XL-Body → mean revert DOWN",
     "p_up": 0.443, "side": "DOWN",
     "check": lambda f: f["color"]==1 and f["streak_len"]>=3 and f["is_xl_body"]},

    # ═════════════════════════════════════════════════════════════
    # TIER 2 — Mittel (4-5pp Edge) — DEAKTIVIERT 2026-05-14
    # Zu nah an 50/50: bei Ask 50¢+ frisst Spread+Slippage den Edge.
    # ═════════════════════════════════════════════════════════════
    {"name": "S5+R_general_UP", "enabled": False,
     "desc": "5+ rote Candles (allg.) → mean revert UP",
     "p_up": 0.549, "side": "UP",
     "check": lambda f: f["color"]==0 and f["streak_len"]>=5},

    {"name": "S5+G_general_DOWN", "enabled": False,
     "desc": "5+ grüne Candles (allg.) → mean revert DOWN",
     "p_up": 0.453, "side": "DOWN",
     "check": lambda f: f["color"]==1 and f["streak_len"]>=5},

    {"name": "S4+R_general_UP", "enabled": True,  # 2026-05-17: Live +$32 / 54.5% Acc (Backtest 54.8% ✅)
     "desc": "4+ rote Candles (allg.) → mean revert UP",
     "p_up": 0.548, "side": "UP",
     "check": lambda f: f["color"]==0 and f["streak_len"]>=4},

    {"name": "S4+G_general_DOWN", "enabled": False,
     "desc": "4+ grüne Candles (allg.) → mean revert DOWN",
     "p_up": 0.451, "side": "DOWN",
     "check": lambda f: f["color"]==1 and f["streak_len"]>=4},

    {"name": "S2+R_XL_UP", "enabled": False,
     "desc": "2+ rote Candles & letzter XL-Body → mean revert UP",
     "p_up": 0.548, "side": "UP",
     "check": lambda f: f["color"]==0 and f["streak_len"]>=2 and f["is_xl_body"]},

    {"name": "S2+G_XL_DOWN", "enabled": True,  # 2026-05-22: Live 57.1% Acc, +$8.93 (n=7) — einziger profitabler DOWN
     "desc": "2+ grüne Candles & letzter XL-Body → mean revert DOWN",
     "p_up": 0.450, "side": "DOWN",
     "check": lambda f: f["color"]==1 and f["streak_len"]>=2 and f["is_xl_body"]},

    # ═════════════════════════════════════════════════════════════
    # TIER 3 — Schwach (3-4pp Edge) — DEAKTIVIERT 2026-05-14
    # ═════════════════════════════════════════════════════════════
    {"name": "S3+R_general_UP", "enabled": False,
     "desc": "3+ rote Candles (allg.) → mean revert UP",
     "p_up": 0.542, "side": "UP",
     "check": lambda f: f["color"]==0 and f["streak_len"]>=3},

    {"name": "S3+G_general_DOWN", "enabled": False,
     "desc": "3+ grüne Candles (allg.) → mean revert DOWN",
     "p_up": 0.463, "side": "DOWN",
     "check": lambda f: f["color"]==1 and f["streak_len"]>=3},

    {"name": "XL_R_UP", "enabled": True,  # 2026-05-22: Live 57.1% Acc, +$9.72 (n=7)
     "desc": "Einzelner XL-Body roter Candle → mean revert UP",
     "p_up": 0.531, "side": "UP",
     "check": lambda f: f["color"]==0 and f["is_xl_body"] and f["streak_len"]==1},

    {"name": "XL_G_DOWN", "enabled": False,
     "desc": "Einzelner XL-Body grüner Candle → mean revert DOWN",
     "p_up": 0.469, "side": "DOWN",
     "check": lambda f: f["color"]==1 and f["is_xl_body"] and f["streak_len"]==1},
]


def find_active_setups(features):
    """Returns list of matching enabled setups, oder leer wenn keiner aktiv."""
    return [s for s in SETUPS if s.get("enabled", True) and s["check"](features)]


def consensus_signal(active_setups):
    """Aggregiert mehrere aktive Setups zu einem Signal.
       Return: ('UP'|'DOWN'|None, p_up_estimate, list_of_names)
    """
    if not active_setups:
        return None, None, []
    sides = set(s["side"] for s in active_setups)
    if len(sides) > 1:
        return None, None, [s["name"] for s in active_setups]  # Konflikt
    # Höchste Konfidenz nehmen (extremster P_Up)
    side = next(iter(sides))
    if side == "UP":
        p_up = max(s["p_up"] for s in active_setups)
    else:
        p_up = min(s["p_up"] for s in active_setups)
    return side, p_up, [s["name"] for s in active_setups]


# ═══════════════════════════════════════════════════════════════
# CONFIG (überschreibt M1-Bot-Defaults wo nötig)
# ═══════════════════════════════════════════════════════════════

class PreBlockConfig:
    BET_SIZE          = float(os.getenv("PRE_BET_SIZE", "5"))
    MIN_EDGE_PP       = float(os.getenv("PRE_MIN_EDGE_PP", "2"))   # min 2pp Edge — viele Trades
    MAX_ASK           = float(os.getenv("PRE_MAX_ASK", "0.65"))    # nicht über 65¢ kaufen
    # MIN_ASK (2026-05-17 Live-Data): bei Ask <30¢ 0-14% Acc (5/5 verloren) → Setup ausgepreist
    MIN_ASK           = float(os.getenv("PRE_MIN_ASK", "0.30"))
    # Stunden-Filter (2026-05-17 Live-Data): 21-01 UTC = größte Verluste,
    # 02-20 UTC = profitabel. Format: comma-separated UTC-Stunden die ERLAUBT sind.
    ALLOWED_HOURS     = set(int(h) for h in os.getenv("PRE_ALLOWED_HOURS",
                                                       "2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20").split(","))
    MAX_SLIPPAGE      = float(os.getenv("PRE_MAX_SLIPPAGE", "0.02"))
    DAILY_LOSS_LIMIT  = float(os.getenv("PRE_DAILY_LOSS_LIMIT", "30"))
    MAX_LOSS_STREAK   = int(os.getenv("PRE_MAX_LOSS_STREAK", "8"))
    DRY_RUN           = os.getenv("PRE_DRY_RUN", os.getenv("DRY_RUN", "true")).lower() == "true"
    TRADES_FILE       = Path(__file__).parent / "pre_block_trades.json"
    # Wann nach Block-Start traden (Sek). +5s = aggressiv, +30s = Liquidität-freundlich
    TRIGGER_OFFSET_S  = int(os.getenv("PRE_TRIGGER_OFFSET_S", "30"))
    # Retry: falls Orderbook leer, x-mal mit 10s-Pause neu versuchen
    EMPTY_BOOK_RETRY  = int(os.getenv("PRE_EMPTY_BOOK_RETRY", "3"))


# ═══════════════════════════════════════════════════════════════
# TRADE LOG
# ═══════════════════════════════════════════════════════════════

class PreBlockLog:
    def __init__(self):
        self.file = PreBlockConfig.TRADES_FILE
        self.trades = []
        if self.file.exists():
            try:
                self.trades = json.loads(self.file.read_text())
            except Exception:
                self.trades = []

    def add(self, trade):
        self.trades.append(trade)
        try:
            self.file.write_text(json.dumps(self.trades, indent=2, default=str))
        except Exception as e:
            log.warning(f"Konnte Log nicht schreiben: {e}")

    def stats(self):
        if not self.trades:
            return {"total": 0, "won": 0, "lost": 0, "pnl": 0.0}
        resolved = [t for t in self.trades if t.get("result") in ("WIN", "LOSS")]
        won  = sum(1 for t in resolved if t["result"]=="WIN")
        lost = sum(1 for t in resolved if t["result"]=="LOSS")
        pnl  = sum(t.get("pnl", 0) for t in resolved)
        return {"total": len(self.trades), "resolved": len(resolved),
                "won": won, "lost": lost, "pnl": round(pnl, 2),
                "acc": round(won / len(resolved) * 100, 1) if resolved else 0}

    def daily_pnl(self, date=None):
        date = date or datetime.now(timezone.utc).date()
        return sum(t.get("pnl", 0) for t in self.trades
                   if t.get("result") in ("WIN", "LOSS")
                   and datetime.fromisoformat(str(t["block_start"]).replace("Z","+00:00")).date() == date)

    def loss_streak(self):
        resolved = [t for t in self.trades if t.get("result") in ("WIN", "LOSS")]
        streak = 0
        for t in reversed(resolved):
            if t["result"] == "LOSS":
                streak += 1
            else:
                break
        return streak


# ═══════════════════════════════════════════════════════════════
# RESOLUTION CHECK
# ═══════════════════════════════════════════════════════════════

def resolve_trade(trade, plog):
    """Nach Block-Ende: hat unser Tip gestimmt?"""
    block_end = datetime.fromisoformat(trade["block_end"].replace("Z","+00:00"))
    if datetime.now(timezone.utc) < block_end + timedelta(seconds=15):
        return False  # noch zu früh

    block_start_dt = datetime.fromisoformat(trade["block_start"].replace("Z","+00:00"))
    p_open, p_close = PythData.get_block_prices(block_start_dt)

    # Fallback: Binance 5m-Kline (weniger genau als Pyth, aber besser als nichts)
    if p_open is None or p_close is None:
        start_ms = int(block_start_dt.timestamp() * 1000)
        end_ms   = start_ms + 5 * 60 * 1000
        try:
            import requests
            r = requests.get(
                f"{Config.BINANCE_URL}/api/v3/klines",
                params={"symbol":"BTCUSDT","interval":"5m","startTime":start_ms,"endTime":end_ms,"limit":1},
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            if data:
                p_open, p_close = float(data[0][1]), float(data[0][4])
                log.info(f"📊 Binance-Fallback: Open=${p_open:,.2f} → Close=${p_close:,.2f}")
        except Exception as e:
            log.warning(f"Binance-Fallback Fehler: {e}")

    if p_open is None or p_close is None:
        log.warning(f"Resolution: keine Preise für {trade['block_start']}")
        return False

    actual_up = p_close > p_open
    if trade["side"] == "UP":
        won = actual_up
    else:
        won = not actual_up

    trade["resolved_at"]   = datetime.now(timezone.utc).isoformat()
    trade["actual_up"]     = bool(actual_up)
    trade["price_open"]    = p_open
    trade["price_close"]   = p_close
    trade["result"]        = "WIN" if won else "LOSS"
    trade["pnl"]           = round(trade["payout"] - trade["bet_size"], 4) if won else round(-trade["bet_size"], 4)

    # In-place update + persist
    for i, t in enumerate(plog.trades):
        if t.get("trade_id") == trade.get("trade_id"):
            plog.trades[i] = trade
            break
    plog.file.write_text(json.dumps(plog.trades, indent=2, default=str))

    s = "✅ WIN" if won else "❌ LOSS"
    log.info(f"{s} | {trade['side']} | {trade['setups']} | "
             f"open={p_open:.2f} close={p_close:.2f} | P&L=${trade['pnl']:+.2f}")
    send_telegram(
        f"{s} {trade['side']} | ${trade['pnl']:+.2f}\n"
        f"Setup: {','.join(trade['setups'])}\n"
        f"BTC: {p_open:.0f} → {p_close:.0f}"
    )
    return True


# ═══════════════════════════════════════════════════════════════
# MAIN BOT
# ═══════════════════════════════════════════════════════════════

class PreBlockBot:
    def __init__(self):
        self.running = True
        self.last_block_traded = None
        self.plog = PreBlockLog()

        log.info("═══ Pre-Block Mean-Reversion Bot ═══")
        log.info(f"Modus:        {'🧪 DRY RUN' if PreBlockConfig.DRY_RUN else '🔴 LIVE'}")
        log.info(f"Bet:          ${PreBlockConfig.BET_SIZE}")
        log.info(f"Min Edge:     {PreBlockConfig.MIN_EDGE_PP}pp")
        log.info(f"Ask-Range:    ${PreBlockConfig.MIN_ASK}–${PreBlockConfig.MAX_ASK}")
        log.info(f"Stunden:      {sorted(PreBlockConfig.ALLOWED_HOURS)} UTC")
        _enabled = sum(1 for s in SETUPS if s.get("enabled", True))
        log.info(f"Setups:       {_enabled}/{len(SETUPS)} aktive Pre-Block-Setups")
        log.info(f"Daily limit:  ${PreBlockConfig.DAILY_LOSS_LIMIT}/Tag")

        if not PreBlockConfig.DRY_RUN:
            self._init_polymarket()
        else:
            self.clob = None
            self.market_finder = None
            self.executor = None

    def _init_polymarket(self):
        try:
            self.clob = ClobClient(
                host=Config.CLOB_HOST,
                chain_id=Config.CHAIN_ID,
                key=Config.PRIVATE_KEY,
                signature_type=Config.SIG_TYPE,
                funder=Config.FUNDER,
            )
            if Config.API_KEY and Config.API_SECRET and Config.API_PASSPHRASE:
                self.clob.set_api_creds(ApiCreds(
                    api_key=Config.API_KEY,
                    api_secret=Config.API_SECRET,
                    api_passphrase=Config.API_PASSPHRASE,
                ))
            else:
                creds = self.clob.create_or_derive_api_key()
                self.clob.set_api_creds(creds)
            self.market_finder = MarketFinder(self.clob)
            self.executor = OrderExecutor(self.clob)
            log.info(f"Polymarket Verbindung: {'✅' if self.clob.get_ok() else '❌'}")
        except Exception as e:
            log.error(f"Polymarket Init Fehler: {e}")
            traceback.print_exc()
            sys.exit(1)

    def _check_resolutions(self):
        """Versucht offene Trades zu resolven. Throttled gegen Pyth-Rate-Limit (429)."""
        unresolved = [t for t in self.plog.trades if not t.get("result")]
        # Älteste zuerst → max 20 pro Tick, sonst hämmern wir Pyth
        unresolved.sort(key=lambda t: t.get("block_start", ""))
        for t in unresolved[:20]:
            try:
                resolve_trade(t, self.plog)
            except Exception as e:
                log.warning(f"Resolution Fehler: {e}")
            time.sleep(0.4)  # ~2.5 req/s → bleibt unter Pyth-Limit

    def _check_can_trade(self):
        """Daily limits, loss-streak."""
        daily = self.plog.daily_pnl()
        if daily <= -PreBlockConfig.DAILY_LOSS_LIMIT:
            return False, f"Daily-Verlust ${daily:.2f} ≥ Limit"
        ls = self.plog.loss_streak()
        if ls >= PreBlockConfig.MAX_LOSS_STREAK:
            return False, f"Loss-Streak {ls} ≥ Limit"
        return True, "OK"

    def _trade_block(self):
        """Hauptlogik: bei Block-Start aufgerufen, T+5s nach :05/:10/:15..."""
        now = datetime.now(timezone.utc)
        block_start = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 5)
        block_end   = block_start + timedelta(minutes=5)

        if self.last_block_traded == block_start:
            return  # schon gehandelt

        # 1) Hole letzte abgeschlossene 5m-Candles
        candles = BinanceData.get_klines(symbol="BTCUSDT", interval="5m", limit=10)
        if len(candles) < 6:
            log.warning("Zu wenig 5m-Candles — skip")
            return

        # Letzte Kerze in der Liste = aktuell laufender Block (sehr neu),
        # daher die VORLETZTE = der gerade abgeschlossene Block (close_time=block_start)
        # Falls Binance schon den neuen Block hat, ist [-1] = neu, [-2] = abgeschlossen
        last_closed_idx = -2 if candles[-1]["close_time"] > block_start else -1
        signal_candles = candles[:last_closed_idx + 1] if last_closed_idx == -2 else candles
        if len(signal_candles) < 6:
            log.warning("Nach Trim zu wenig Candles — skip")
            return

        # 2) Features berechnen
        feat = _last_n_streak_xl(signal_candles)
        if not feat:
            return
        log.info(f"Block {block_start.strftime('%H:%M')} | "
                 f"letzter Candle {'GRÜN' if feat['color'] else 'ROT'} "
                 f"streak={feat['streak_len']} body={feat['body_pct']:+.3f}% "
                 f"{'XL' if feat['is_xl_body'] else 'normal'} hour={feat['hour_utc']}")

        # 3) Stundenfilter (2026-05-17 Live-Data): 21-01 UTC = große Verluste
        if feat["hour_utc"] not in PreBlockConfig.ALLOWED_HOURS:
            log.debug(f"Stunde {feat['hour_utc']} UTC nicht in ALLOWED_HOURS — skip")
            self.last_block_traded = block_start
            return

        # 4) Setups matchen
        active = find_active_setups(feat)
        if not active:
            log.debug(f"Keine Pre-Block-Setups aktiv für Block {block_start.strftime('%H:%M')}")
            self.last_block_traded = block_start
            return

        side, p_up, names = consensus_signal(active)
        if side is None:
            log.info(f"⚠️ Konflikt zwischen {len(active)} Setups: {names} — skip")
            self.last_block_traded = block_start
            return

        log.info(f"🎯 {len(active)} Setups aktiv: {names}")
        log.info(f"   → Side: {side} | P_Up={p_up:.3f} | erwartet: {'GRÜN' if side=='UP' else 'ROT'}")

        # 4) Polymarket-Markt holen + Edge berechnen
        if PreBlockConfig.DRY_RUN:
            # Paper-Mode: simuliere Ask = 0.52
            ask = 0.52
            log.info(f"   📝 PAPER: simulierter Ask {ask:.2f}")
        else:
            mkt = self.market_finder.find_active_market(block_start=block_start)
            if not mkt:
                log.warning("Kein Markt gefunden — skip")
                self.last_block_traded = block_start
                return
            # Retry-Loop: Orderbook kann am Block-Anfang noch leer sein
            ask = None
            prices = {}
            for attempt in range(PreBlockConfig.EMPTY_BOOK_RETRY):
                prices = self.market_finder.get_market_prices(mkt["token_id_up"], mkt["token_id_down"])
                ask_up   = prices.get("up_ask")
                ask_down = prices.get("down_ask")
                ask = ask_up if side == "UP" else ask_down
                if ask is not None and ask < 0.97:
                    break
                if attempt < PreBlockConfig.EMPTY_BOOK_RETRY - 1:
                    log.info(f"   ⏳ Orderbook leer (attempt {attempt+1}/{PreBlockConfig.EMPTY_BOOK_RETRY}), prices={prices} — warte 10s")
                    time.sleep(10)

            if ask is None:
                log.warning(f"Kein Ask nach {PreBlockConfig.EMPTY_BOOK_RETRY} Versuchen — skip (prices={prices})")
                self.last_block_traded = block_start
                return
            if ask >= 0.97:
                log.warning(f"Ask {ask:.2f} ≥ 0.97 (illiquider Markt) — skip")
                self.last_block_traded = block_start
                return

        # 5) Edge berechnen
        win_prob = p_up if side == "UP" else (1 - p_up)
        edge = (win_prob - ask) * 100  # in Prozentpunkten

        log.info(f"   Ask: {ask*100:.0f}¢ | Win-Prob: {win_prob*100:.0f}% | Edge: {edge:+.1f}pp")

        if ask >= PreBlockConfig.MAX_ASK:
            log.info(f"   ⏭️ Ask {ask:.2f} ≥ MAX_ASK {PreBlockConfig.MAX_ASK} — skip")
            self.last_block_traded = block_start
            return

        if ask < PreBlockConfig.MIN_ASK:
            log.info(f"   ⏭️ Ask {ask:.2f} < MIN_ASK {PreBlockConfig.MIN_ASK} — Setup ausgepreist, skip")
            self.last_block_traded = block_start
            return

        if edge < PreBlockConfig.MIN_EDGE_PP:
            log.info(f"   ⏭️ Edge {edge:.1f}pp < {PreBlockConfig.MIN_EDGE_PP}pp — skip")
            self.last_block_traded = block_start
            return

        # 6) Risk Check
        ok, reason = self._check_can_trade()
        if not ok:
            log.warning(f"   🛑 Trade blockiert: {reason}")
            self.last_block_traded = block_start
            return

        # 7) Order!
        bet = PreBlockConfig.BET_SIZE
        log.info(f"   ✅ TRADE {side} ${bet:.2f} @ {ask*100:.0f}¢ | erwarteter Profit ${bet*(1/ask-1)*win_prob - bet*(1-win_prob):+.2f}")

        trade_id = f"pb_{int(block_start.timestamp())}"
        trade_record = {
            "trade_id":     trade_id,
            "block_start":  block_start.isoformat(),
            "block_end":    block_end.isoformat(),
            "side":         side,
            "p_up_model":   round(p_up, 4),
            "ask":          round(ask, 4),
            "edge_pp":      round(edge, 2),
            "bet_size":     bet,
            "setups":       names,
            "feature":      feat,
            "dry_run":      PreBlockConfig.DRY_RUN,
            "payout":       round(bet / ask, 2),
            "result":       None,
            "placed_at":    datetime.now(timezone.utc).isoformat(),
        }

        if PreBlockConfig.DRY_RUN:
            trade_record["status"] = "PAPER"
            log.info(f"   📝 PAPER-Trade gespeichert (kein realer Order)")
        else:
            token_id = mkt["token_id_up"] if side == "UP" else mkt["token_id_down"]
            resp = self.executor.place_market_buy(token_id, bet)
            if resp and resp.get("status") in ("matched", "delayed"):
                trade_record["status"] = "FILLED"
                trade_record["order_resp"] = resp
                send_telegram(
                    f"🎯 PRE-BLOCK {side} ${bet}\n"
                    f"Setup: {','.join(names)}\n"
                    f"Edge: {edge:+.1f}pp @ {ask*100:.0f}¢\n"
                    f"Block: {block_start.strftime('%H:%M UTC')}"
                )
            else:
                trade_record["status"] = "FAILED"
                trade_record["order_resp"] = resp
                log.error(f"Order fehlgeschlagen: {resp}")

        self.plog.add(trade_record)
        self.last_block_traded = block_start

    def run(self):
        signal.signal(signal.SIGTERM, lambda s,f: setattr(self, 'running', False))
        signal.signal(signal.SIGINT,  lambda s,f: setattr(self, 'running', False))

        send_telegram(f"🚀 Pre-Block Bot gestartet ({'PAPER' if PreBlockConfig.DRY_RUN else 'LIVE'})")

        while self.running:
            try:
                now = datetime.now(timezone.utc)
                # Berechne nächsten Block-Start
                block_minute_offset = now.minute % 5
                next_block = now.replace(second=0, microsecond=0) + timedelta(
                    minutes=(5 - block_minute_offset) % 5 or 5
                )
                # Trigger nach Block-Start (default +30s für Liquidität)
                trigger_time = next_block + timedelta(seconds=PreBlockConfig.TRIGGER_OFFSET_S)
                wait_s = (trigger_time - now).total_seconds()

                if wait_s > 0:
                    log.debug(f"Warte {wait_s:.0f}s bis nächster Trigger {trigger_time.strftime('%H:%M:%S')}")
                    # In kleinen Schritten warten, damit Resolutions zwischendurch laufen
                    end_t = time.time() + wait_s
                    while self.running and time.time() < end_t:
                        time.sleep(min(20, end_t - time.time()))
                        # Alle 20s Resolutions checken
                        self._check_resolutions()

                if not self.running:
                    break

                # Trade dieser Block
                self._trade_block()

                # Stats alle 12 Blocks (1h) loggen
                stats = self.plog.stats()
                if stats["total"] % 12 == 0 and stats["total"] > 0:
                    log.info(f"📊 Stats: {stats['total']} trades | "
                             f"{stats['resolved']} resolved | "
                             f"Acc {stats['acc']}% | P&L ${stats['pnl']:+.2f}")

            except Exception as e:
                log.error(f"Loop Fehler: {e}")
                traceback.print_exc()
                time.sleep(30)

        # Cleanup
        log.info("Bot Shutdown — finales Stats:")
        s = self.plog.stats()
        log.info(f"  Trades: {s['total']} | Resolved: {s['resolved']} | "
                 f"Acc: {s['acc']}% | P&L: ${s['pnl']:+.2f}")
        send_telegram(f"🛑 Pre-Block Bot beendet | {s['total']} trades | P&L ${s['pnl']:+.2f}")


def main():
    # Eigene Lock-Datei, damit M1-Bot (bot.pid) und Pre-Block-Bot parallel laufen können
    import bot as _botmod
    _botmod.LOCKFILE = Path("pre_block_bot.pid")
    if not _acquire_lock():
        log.error("Anderer Pre-Block-Bot läuft schon (pre_block_bot.pid existiert)")
        sys.exit(1)
    try:
        bot = PreBlockBot()
        bot.run()
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
