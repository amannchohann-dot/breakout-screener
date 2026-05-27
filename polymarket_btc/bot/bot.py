#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║  POLYMARKET BTC 5-MIN PREDICTION BOT                            ║
║  Late-Entry Strategie: M1 Momentum → 74.8% Accuracy            ║
║                                                                  ║
║  Backtest: 200.833 Blöcke, 28/28 Monate profitabel             ║
║  Edge: Nach Minute 1 die Richtung des 5-Min-Blocks vorhersagen ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import time
import json
import logging
import math
import signal
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── Polymarket SDK ──
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import (
    ApiCreds, OrderArgs, OrderType
)
from py_clob_client_v2.order_builder.constants import BUY, SELL
from py_clob_client_v2.constants import POLYGON


# ═══════════════════════════════════════════════════════════════
# KONFIGURATION
# ═══════════════════════════════════════════════════════════════

load_dotenv()

class Config:
    # Polymarket
    PRIVATE_KEY       = os.getenv("POLYMARKET_PRIVATE_KEY", "")
    FUNDER            = os.getenv("POLYMARKET_FUNDER", "")
    SIG_TYPE          = int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "1"))
    CLOB_HOST         = os.getenv("CLOB_HOST", "https://clob.polymarket.com")
    CHAIN_ID          = int(os.getenv("CHAIN_ID", "137"))

    # Optional API creds
    API_KEY           = os.getenv("POLYMARKET_API_KEY", "")
    API_SECRET        = os.getenv("POLYMARKET_API_SECRET", "")
    API_PASSPHRASE    = os.getenv("POLYMARKET_API_PASSPHRASE", "")

    # Strategie
    M1_THRESHOLD      = float(os.getenv("M1_THRESHOLD", "0.05"))
    BET_SIZE          = float(os.getenv("BET_SIZE", "5"))
    MAX_TRADES_BLOCK  = int(os.getenv("MAX_TRADES_PER_BLOCK", "1"))

    # Risk
    DAILY_LOSS_LIMIT  = float(os.getenv("DAILY_LOSS_LIMIT", "50"))
    MAX_LOSS_STREAK   = int(os.getenv("MAX_LOSS_STREAK", "5"))
    STREAK_PAUSE      = int(os.getenv("STREAK_PAUSE", "300"))
    MAX_BANKROLL      = float(os.getenv("MAX_BANKROLL", "200"))
    MAX_SLIPPAGE      = float(os.getenv("MAX_SLIPPAGE", "0.03"))
    # M1-Ask-Filter (2026-05-14): bei Ask >70¢ ist Edge zu klein für sicheren Gewinn,
    # selbst bei 86% Konfidenz. Mathe: Win bringt (1-ask)/ask, Loss kostet 1$/share.
    # Bei 80¢ Ask braucht man 80% Hitrate für Break-Even.
    M1_MAX_ASK        = float(os.getenv("M1_MAX_ASK", "0.70"))

    # Balance-basiertes Position Sizing
    # INITIAL_BANKROLL = aktueller Polymarket-Kontostand (vor jedem Neustart prüfen!)
    # Internes P&L-Tracking ist unzuverlässig → nur dieser Wert zählt für Scaling.
    INITIAL_BANKROLL  = float(os.getenv("INITIAL_BANKROLL", "100"))
    # Skalierungs-Stufen: bei welcher Balance → welcher Einsatz
    SCALE_AT_200      = float(os.getenv("SCALE_AT_200", "200"))   # $200 → $7/Trade
    BET_SIZE_200      = float(os.getenv("BET_SIZE_200", "7"))
    SCALE_AT_300      = float(os.getenv("SCALE_AT_300", "300"))   # $300 → $10/Trade
    BET_SIZE_300      = float(os.getenv("BET_SIZE_300", "10"))

    # Pyramid-Sizing (Variante C): Initial bei M2, Nachkauf bei M3-Confirm
    PYRAMID_ENABLE     = os.getenv("PYRAMID_ENABLE", "true").lower() == "true"
    # Auto-Scale: Addon = Initial-Bet × Multiplier. Addon skaliert mit Bankroll-Stufen.
    # Default 3.0 = bei $5 Initial → $15 Addon, bei $10 Initial → $30 Addon.
    PYRAMID_MULTIPLIER = float(os.getenv("PYRAMID_MULTIPLIER", "3.0"))
    # Optional: expliziter Override (wenn > 0, überschreibt den Multiplier)
    PYRAMID_ADDON_BET  = float(os.getenv("PYRAMID_ADDON_BET", "0"))

    # Betrieb
    DRY_RUN           = os.getenv("DRY_RUN", "true").lower() == "true"
    LOG_LEVEL         = os.getenv("LOG_LEVEL", "INFO")

    # Telegram
    TG_TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TG_CHAT_ID        = os.getenv("TELEGRAM_CHAT_ID", "")

    # Binance
    BINANCE_URL       = os.getenv("BINANCE_BASE_URL", "https://api.binance.com")


# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

log_file = LOG_DIR / f"bot_{datetime.now(timezone.utc).strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format="%(asctime)s │ %(levelname)-5s │ %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
)
log = logging.getLogger("pm5m")


# ═══════════════════════════════════════════════════════════════
# TELEGRAM ALERTS
# ═══════════════════════════════════════════════════════════════

def send_telegram(msg: str):
    """Sende Telegram-Nachricht (optional)."""
    if not Config.TG_TOKEN or not Config.TG_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{Config.TG_TOKEN}/sendMessage",
            json={"chat_id": Config.TG_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        log.warning(f"Telegram Fehler: {e}")


# ═══════════════════════════════════════════════════════════════
# PYTH NETWORK PREIS-ORACLE (identisch zu Polymarket Resolution)
# ═══════════════════════════════════════════════════════════════

class PythData:
    """
    Holt BTC/USD-Preise direkt vom Pyth Hermes API —
    dieselbe Quelle die Polymarket für die Markt-Resolution nutzt.

    BTC/USD Feed ID: e62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43
    Docs: https://hermes.pyth.network/docs
    """

    HERMES_URL = "https://hermes.pyth.network"
    BTC_FEED_ID = "e62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43"

    @staticmethod
    def _parse_price(parsed_entry: dict) -> float | None:
        """Wandelt Pyth-Rohpreis in USD um."""
        try:
            price_info = parsed_entry.get("price", {})
            raw   = int(price_info["price"])
            expo  = int(price_info["expo"])
            return raw * (10 ** expo)
        except Exception:
            return None

    @staticmethod
    def get_price_at(unix_ts: int) -> float | None:
        """
        Holt den BTC/USD Pyth-Preis zum nächstgelegenen Zeitstempel.
        unix_ts: Unix-Timestamp (int)
        """
        try:
            r = requests.get(
                f"{PythData.HERMES_URL}/v2/updates/price/{unix_ts}",
                params={"ids[]": PythData.BTC_FEED_ID},
                timeout=10,
            )
            if r.status_code != 200:
                log.warning(f"Pyth API Fehler {r.status_code} @ ts={unix_ts}")
                return None
            data = r.json()
            parsed = data.get("parsed", [])
            if not parsed:
                return None
            return PythData._parse_price(parsed[0])
        except Exception as e:
            log.warning(f"Pyth Preis-Abfrage Fehler (ts={unix_ts}): {e}")
            return None

    @staticmethod
    def get_block_prices(block_start: datetime) -> tuple[float | None, float | None]:
        """
        Holt Open- und Close-Preis eines 5-Min-Blocks von Pyth.
        Returns: (open_price, close_price)
        """
        open_ts  = int(block_start.timestamp())
        close_ts = int((block_start + timedelta(minutes=5)).timestamp())

        open_price  = PythData.get_price_at(open_ts)
        close_price = PythData.get_price_at(close_ts)

        if open_price and close_price:
            log.info(
                f"📡 Pyth Preise: Open=${open_price:,.2f} → Close=${close_price:,.2f} "
                f"({'↑' if close_price > open_price else '↓'}{abs(close_price-open_price):.2f})"
            )
        else:
            log.warning(f"Pyth: Open={open_price}, Close={close_price} — Fallback auf Binance")

        return open_price, close_price


# ═══════════════════════════════════════════════════════════════
# BINANCE KLINE-DATEN (für M1-Signal, nicht mehr für Resolution)
# ═══════════════════════════════════════════════════════════════

class BinanceData:
    """Holt 1-Minuten-Kerzendaten von Binance (öffentlich, kein Key nötig)."""

    BASE = Config.BINANCE_URL

    # Circuit Breaker: verhindert Retry-Storms bei Netzwerkausfall
    _circuit_open       = False
    _circuit_open_until = None

    @staticmethod
    def get_klines(symbol="BTCUSDT", interval="1m", limit=10) -> list[dict]:
        """
        Holt die letzten `limit` 1m-Kerzen.
        Beinhaltet Exponential Backoff (3 Versuche) + Circuit Breaker (2 Min Pause).
        Returns: [{open, high, low, close, volume, timestamp, close_time}, ...]
        """
        # Circuit Breaker: wenn Binance kürzlich down war → sofort returnen
        if BinanceData._circuit_open:
            now = datetime.now(timezone.utc)
            if now < BinanceData._circuit_open_until:
                remaining = int((BinanceData._circuit_open_until - now).total_seconds())
                log.debug(f"Binance Circuit Breaker aktiv — noch {remaining}s")
                return []
            else:
                BinanceData._circuit_open = False
                log.info("Binance Circuit Breaker zurückgesetzt — versuche erneut")

        url    = f"{BinanceData.BASE}/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}

        for attempt in range(3):
            try:
                r = requests.get(url, params=params, timeout=10)
                r.raise_for_status()
                candles = []
                for k in r.json():
                    candles.append({
                        "timestamp":  datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc),
                        "open":       float(k[1]),
                        "high":       float(k[2]),
                        "low":        float(k[3]),
                        "close":      float(k[4]),
                        "volume":     float(k[5]),
                        "close_time": datetime.fromtimestamp(k[6] / 1000, tz=timezone.utc),
                    })
                return candles
            except Exception as e:
                if attempt < 2:
                    wait = 2 ** attempt  # 1s, dann 2s
                    log.warning(f"Binance Fehler (Versuch {attempt+1}/3) — warte {wait}s: {e}")
                    time.sleep(wait)
                else:
                    # Nach 3 Fehlern: Circuit Breaker für 2 Minuten öffnen
                    BinanceData._circuit_open       = True
                    BinanceData._circuit_open_until = datetime.now(timezone.utc) + timedelta(minutes=2)
                    log.error(f"Binance nach 3 Versuchen nicht erreichbar — Circuit Breaker für 2 Min: {e}")
                    return []

    @staticmethod
    def get_current_block_data() -> dict | None:
        """
        Holt die aktuelle 5-Min-Block-Info:
        - block_open: Open-Preis des 5-Min-Blocks
        - m1_close: Close der 1. Minute
        - m1_move_pct: Kumulative Bewegung in %
        - m1_direction: UP oder DOWN
        - block_start: Beginn des 5-Min-Blocks
        - minutes_elapsed: Wie viele Minuten im Block vergangen
        """
        candles = BinanceData.get_klines(limit=8)
        if not candles:
            return None

        now = datetime.now(timezone.utc)
        current_minute = now.minute
        block_minute = current_minute % 5  # 0-4 innerhalb des Blocks

        # Finde den Anfang des aktuellen 5-Min-Blocks
        block_start_min = current_minute - block_minute
        block_start = now.replace(minute=block_start_min, second=0, microsecond=0)

        # Suche die Kerzen die zu diesem Block gehören
        block_candles = [c for c in candles if c["timestamp"] >= block_start]

        if not block_candles:
            return None

        block_open = block_candles[0]["open"]

        # Für 3-Wege-Strategie brauchen wir M1 UND M2 (Confirmation/Reversal)
        if block_minute < 2 or len(block_candles) < 2:
            return {"status": "waiting", "minutes_elapsed": block_minute, "block_start": block_start}

        m1 = block_candles[0]  # Erste Minute des Blocks
        m1_close = m1["close"]
        m1_move_pct = (m1_close - block_open) / block_open * 100
        m1_direction = "UP" if m1_move_pct > 0 else "DOWN"
        m1_volume = m1["volume"]

        m2 = block_candles[1]
        m2_close = m2["close"]
        m2_move_pct = (m2_close - block_open) / block_open * 100

        return {
            "status":           "ready",
            "block_start":      block_start,
            "block_open":       block_open,
            "m1_close":         m1_close,
            "m1_move_pct":      m1_move_pct,
            "m1_abs":           abs(m1_move_pct),
            "m1_direction":     m1_direction,
            "m1_volume":        m1_volume,
            "m2_move_pct":      m2_move_pct,
            "m3_move_pct":      (
                (block_candles[2]["close"] - block_open) / block_open * 100
                if len(block_candles) >= 3 else None
            ),
            "minutes_elapsed":  block_minute,
            "current_price":    block_candles[-1]["close"],
        }


# ═══════════════════════════════════════════════════════════════
# POLYMARKET MARKET FINDER
# ═══════════════════════════════════════════════════════════════

class MarketFinder:
    """
    Findet den aktuellen BTC 5-Min Up/Down Markt auf Polymarket.

    Slug-Format: btc-updown-5m-{end_unix_timestamp}
    Beispiel:    btc-updown-5m-1776193200
    API:         gamma-api.polymarket.com/events?slug={slug}

    Strategie: Slug direkt aus aktuellem Timestamp berechnen —
    kein Durchsuchen von 1000 Märkten nötig.
    """

    GAMMA_API = "https://gamma-api.polymarket.com"

    def __init__(self, clob: ClobClient):
        self.clob = clob

    def _slug_for_block(self, offset_blocks: int = 0) -> str:
        """Berechnet den Slug für den aktuellen (oder n-ten nächsten) 5-Min-Block.
        Polymarket verwendet den Block-START-Timestamp im Slug, nicht das Ende.
        Beispiel: Block 14:00–14:05 UTC → btc-updown-5m-{14:00:00}
        """
        now_ts = int(time.time())
        block_start_ts = now_ts - (now_ts % 300) + (offset_blocks * 300)
        return f"btc-updown-5m-{block_start_ts}"

    def _fetch_event(self, slug: str) -> dict | None:
        """Holt ein Event von der Gamma API per Slug."""
        try:
            r = requests.get(
                f"{self.GAMMA_API}/events",
                params={"slug": slug, "limit": 1},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            if not data:
                return None
            return data[0] if isinstance(data, list) else data
        except Exception as e:
            log.debug(f"Gamma fetch Fehler ({slug}): {e}")
            return None

    def _extract_market(self, event: dict) -> dict | None:
        """Extrahiert condition_id + Token IDs aus einem Gamma Event."""
        markets = event.get("markets", [])
        if not markets:
            return None

        m = markets[0]
        condition_id = m.get("conditionId", m.get("condition_id", ""))
        if not condition_id:
            return None

        # Token IDs via CLOB holen
        try:
            clob_market = self.clob.get_market(condition_id)
            tokens = clob_market.get("tokens", [])
        except Exception:
            tokens = m.get("tokens", [])

        token_up = token_down = None
        for t in tokens:
            outcome = t.get("outcome", "").lower()
            if any(x in outcome for x in ["up", "auf", "yes"]):
                token_up = t.get("token_id")
            elif any(x in outcome for x in ["down", "ab", "no"]):
                token_down = t.get("token_id")

        if not token_up or not token_down:
            if len(tokens) >= 2:
                token_up   = tokens[0].get("token_id")
                token_down = tokens[1].get("token_id")
            else:
                log.warning("Token IDs nicht gefunden")
                return None

        return {
            "condition_id":  condition_id,
            "token_id_up":   token_up,
            "token_id_down": token_down,
            "question":      event.get("title", m.get("question", "")),
            "end_time":      event.get("endDate", ""),
            "market_slug":   event.get("slug", ""),
        }

    def find_active_market(self, block_start: datetime | None = None) -> dict | None:
        """
        Findet den aktuellen BTC 5-min Up/Down Markt.
        Probiert NUR den aktuellen Block — kein Fallback auf nächsten Block,
        da sonst M1-Signal von Block X in Markt X+1 landet (falscher Trade).

        block_start: Wenn angegeben, wird der Slug gegen den Signal-Block-Start validiert.
                     Polymarket-Slugs enthalten den Block-START-Timestamp.
        Returns: {condition_id, token_id_up, token_id_down, question, end_time}
        """
        # Erwarteter Slug-Timestamp = Block-START (nicht Ende!)
        expected_slug_ts = None
        if block_start:
            expected_slug_ts = int(block_start.timestamp())

        # Nur aktuellen Block probieren (kein +1, das wäre falscher Markt!)
        for offset in [0]:
            slug = self._slug_for_block(offset)
            log.info(f"🔍 Slug-Suche: {slug}")
            event = self._fetch_event(slug)
            if not event:
                log.warning(f"Markt nicht gefunden für Block: {slug}")
                return None

            result = self._extract_market(event)
            if not result:
                return None

            # Validiere dass der Markt zum Signal-Block gehört
            if expected_slug_ts:
                slug_ts = int(slug.split("-")[-1])
                if abs(slug_ts - expected_slug_ts) > 60:
                    log.warning(
                        f"⚠️ Falscher Block: Slug-Timestamp={slug_ts}, "
                        f"Signal-Block-Start≈{expected_slug_ts} — skip"
                    )
                    return None

            log.info(f"Markt gefunden: {result['question'][:60]}")
            log.info(f"  Slug:       {result['market_slug']}")
            log.info(f"  End:        {result['end_time']}")
            log.debug(f"  UP Token:   {result['token_id_up']}")
            log.debug(f"  DOWN Token: {result['token_id_down']}")
            return result

        log.warning("Kein BTC 5-Min Markt gefunden — warte auf nächsten Block")
        return None

    def get_market_prices(self, token_id_up: str, token_id_down: str) -> dict:
        """Holt aktuelle Preise für UP und DOWN Token.
        Kompatibel mit OrderBookSummary-Objekten (py-clob-client >= 0.20).
        """
        def _best_ask(book) -> float | None:
            # min() statt [0]: Polymarket-CLOB liefert Asks von hoch→niedrig,
            # daher ist asks[0] oft der 99¢-Sentinel (schlechtester Preis).
            try:
                asks = book.asks if hasattr(book, "asks") else book.get("asks", [])
                if not asks:
                    return None
                prices = [float(o.price if hasattr(o, "price") else o["price"]) for o in asks]
                return min(prices)
            except Exception:
                return None

        def _best_bid(book) -> float | None:
            # max() statt [0]: Bids kommen von niedrig→hoch,
            # daher ist bids[0] oft 1¢ (schlechtester Preis).
            try:
                bids = book.bids if hasattr(book, "bids") else book.get("bids", [])
                if not bids:
                    return None
                prices = [float(o.price if hasattr(o, "price") else o["price"]) for o in bids]
                return max(prices)
            except Exception:
                return None

        try:
            book_up   = self.clob.get_order_book(token_id_up)
            book_down = self.clob.get_order_book(token_id_down)

            best_ask_up   = _best_ask(book_up)
            best_bid_up   = _best_bid(book_up)
            best_ask_down = _best_ask(book_down)
            best_bid_down = _best_bid(book_down)

            mid_up   = (best_ask_up   + best_bid_up)   / 2 if best_ask_up   and best_bid_up   else None
            mid_down = (best_ask_down + best_bid_down) / 2 if best_ask_down and best_bid_down else None

            return {
                "up_ask":   best_ask_up,
                "up_bid":   best_bid_up,
                "up_mid":   mid_up,
                "down_ask": best_ask_down,
                "down_bid": best_bid_down,
                "down_mid": mid_down,
            }
        except Exception as e:
            log.error(f"Preis-Abfrage Fehler: {e}")
            return {}


# ═══════════════════════════════════════════════════════════════
# ORDER EXECUTION
# ═══════════════════════════════════════════════════════════════

class OrderExecutor:
    """Platziert Orders auf Polymarket."""

    def __init__(self, clob: ClobClient):
        self.clob = clob

    def place_limit_order(
        self, token_id: str, side: str, price: float, size: float
    ) -> dict | None:
        """
        Platziert eine Limit-Order.
        side: "BUY" oder "SELL"
        price: 0.01 - 0.99
        size: Anzahl Shares
        """
        try:
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=BUY if side == "BUY" else SELL,
            )
            signed_order = self.clob.create_order(order_args)
            resp = self.clob.post_order(signed_order, OrderType.GTC)
            log.info(f"Order platziert: {side} {size:.1f} @ ${price:.2f} → {resp}")
            return resp
        except Exception as e:
            log.error(f"Order Fehler: {e}")
            traceback.print_exc()
            return None

    def place_market_buy(self, token_id: str, amount: float) -> dict | None:
        """
        Platziert eine FOK Limit-Order zum besten Ask.
        Nutzt min(ask_prices) statt [0] — Polymarket-CLOB sortiert Asks hoch→niedrig,
        daher ist asks[0] oft der 99¢-Sentinel (schlechtester Preis, nicht bester!).
        amount: USDC-Betrag
        """
        try:
            book = self.clob.get_order_book(token_id)

            # Kompatibel mit OrderBookSummary-Objekten (py-clob-client >= 0.20)
            asks = book.asks if hasattr(book, "asks") else book.get("asks", [])
            if not asks:
                log.warning("Kein Ask im Orderbook")
                return None

            # min() statt [0]: Polymarket-CLOB liefert Asks von hoch→niedrig,
            # daher ist asks[0] oft der 99¢-Sentinel (schlechtester Preis).
            ask_prices = [float(o.price if hasattr(o, "price") else o["price"]) for o in asks]
            best_ask = min(ask_prices)

            if best_ask >= 0.97:
                log.warning(f"❌ Kein echter Ask (best_ask={best_ask:.3f} ≥ 0.97) — illiquider Markt, skip")
                return None

            if best_ask > Config.M1_MAX_ASK:
                log.warning(
                    f"⏭️  Ask ${best_ask:.2f} > M1_MAX_ASK ${Config.M1_MAX_ASK:.2f} — "
                    f"Edge zu klein für sicheren Gewinn, skip"
                )
                return None

            # Slippage-Schutz: worst_price = best_ask + MAX_SLIPPAGE (max 0.97)
            # Polymarket: price muss max 2 Nachkommastellen haben
            worst_price = round(min(best_ask + Config.MAX_SLIPPAGE, 0.97), 2)

            # Shares berechnen: USDC / Preis
            # Polymarket-Constraint: maker amount (= shares × price) muss als USDC
            # max 2 Dezimalstellen haben. Bei Preisen mit ungeraden Cents (0.69, 0.71)
            # zwingt das `shares` auf grobe Schritte (manchmal nur ganze Zahlen).
            # Schrittgröße via gcd berechnen, dann nach unten runden.
            amount_rounded   = round(amount, 2)
            price_cents      = int(round(worst_price * 100))   # 1-97
            if price_cents <= 0:
                log.warning(f"Ungültiger worst_price={worst_price} — skip")
                return None
            step_int_raw     = 10000 // math.gcd(price_cents, 10000)
            # Shares dürfen max 2 Dezimalstellen haben (py-clob-client rejects sonst,
            # auch wenn die Fehlermeldung "max 4 decimals" verspricht).
            # step_int muss also Vielfaches von 100 sein → LCM berechnen.
            step_int         = step_int_raw * 100 // math.gcd(step_int_raw, 100)
            target_size_int  = int(amount_rounded * 10000 / worst_price)
            valid_size_int   = (target_size_int // step_int) * step_int  # abrunden
            if valid_size_int <= 0:
                log.warning(
                    f"Bei worst_price={worst_price} kein gültiger Order-Betrag "
                    f"(step={step_int/10000:.4f} shares) für ${amount_rounded:.2f} — skip"
                )
                return None
            shares     = valid_size_int / 10000
            usdc_check = round(shares * worst_price, 2)
            log.info(
                f"FOK Limit Order: {shares:.4f} Shares @ best_ask=${best_ask:.4f} "
                f"(worst={worst_price:.2f}) | USDC={usdc_check:.2f} "
                f"(target=${amount_rounded:.2f}, step={step_int/10000:.4f})"
            )

            # Float-Precision-Fix (2026-04-22):
            # py-clob-client's `round_down(size, 2)` nutzt floor(size × 100) / 100.
            # Viele 2-Dezimal-Shares wie 33.3 sind in IEEE 754 Float als
            # 33.2999999... gespeichert → floor(3329.99...) = 3329 → Library
            # sendet 33.29 statt 33.30. Das makerAmount wird damit z.B.
            # 33.29 × 0.90 = 29.961 (3 Dezimalen) → Polymarket-Server rejected
            # mit "maker amount max 2 decimals". Winziges Epsilon (1e-9) hebt
            # den Share-Wert knapp über die Rundungsschwelle, so dass die
            # Library korrekt 33.30 draus macht. 29.97 → passt.
            shares_safe = shares + 1e-9

            order_args = OrderArgs(
                token_id=token_id,
                price=worst_price,
                size=shares_safe,
                side=BUY,
            )
            signed = self.clob.create_order(order_args)
            resp = self.clob.post_order(signed, OrderType.FOK)
            log.info(f"FOK Result: {resp}")
            return resp
        except Exception as e:
            log.error(f"Market Order Fehler: {e}")
            traceback.print_exc()
            return None


# ═══════════════════════════════════════════════════════════════
# TRADE TRACKER
# ═══════════════════════════════════════════════════════════════

class TradeTracker:
    """Trackt Trades, P&L, Streaks und tägliche Limits."""

    TRADES_FILE = Path("trades_log.json")

    def __init__(self):
        self.today = datetime.now(timezone.utc).date()
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.loss_streak = 0
        self.win_streak = 0
        self.trades_today = 0
        self.total_trades = 0
        self.total_wins = 0
        self.paused_until = None
        self.trades = []
        self._load()

    def _load(self):
        """Lade vergangene Trades."""
        if self.TRADES_FILE.exists():
            try:
                data = json.loads(self.TRADES_FILE.read_text())
                self.total_pnl = data.get("total_pnl", 0)
                self.total_trades = data.get("total_trades", 0)
                self.total_wins = data.get("total_wins", 0)
                self.trades = data.get("trades", [])[-500:]  # Letzte 500
                log.info(f"Geladen: {self.total_trades} Trades, P&L: ${self.total_pnl:+.2f}")
            except Exception:
                pass

    def _save(self):
        """Speichere Trades."""
        data = {
            "total_pnl":    round(self.total_pnl, 2),
            "total_trades":  self.total_trades,
            "total_wins":    self.total_wins,
            "trades":        self.trades[-500:],
            "last_updated":  datetime.now(timezone.utc).isoformat(),
        }
        self.TRADES_FILE.write_text(json.dumps(data, indent=2))

    def check_daily_reset(self):
        """Reset täglicher Zähler um Mitternacht UTC."""
        today = datetime.now(timezone.utc).date()
        if today != self.today:
            log.info(f"═══ Tageswechsel: {self.today} → {today} | Tages-P&L war: ${self.daily_pnl:+.2f} ═══")
            self.today = today
            self.daily_pnl = 0.0
            self.trades_today = 0

    def can_trade(self) -> tuple[bool, str]:
        """Prüfe ob Trading erlaubt ist."""
        self.check_daily_reset()

        if self.paused_until and datetime.now(timezone.utc) < self.paused_until:
            remaining = (self.paused_until - datetime.now(timezone.utc)).seconds
            return False, f"Pause nach Loss-Streak ({remaining}s verbleibend)"

        if self.daily_pnl <= -Config.DAILY_LOSS_LIMIT:
            return False, f"Tages-Verlustlimit erreicht: ${self.daily_pnl:.2f}"

        return True, "OK"

    def record_trade(self, trade: dict):
        """Zeichne einen Trade auf."""
        pnl = trade.get("pnl", 0)
        self.daily_pnl += pnl
        self.total_pnl += pnl
        self.total_trades += 1
        self.trades_today += 1

        if pnl > 0:
            self.total_wins += 1
            self.win_streak += 1
            self.loss_streak = 0
        elif pnl < 0:
            self.loss_streak += 1
            self.win_streak = 0
            if self.loss_streak >= Config.MAX_LOSS_STREAK:
                self.paused_until = datetime.now(timezone.utc) + timedelta(seconds=Config.STREAK_PAUSE)
                log.warning(f"⚠️ {self.loss_streak}x Loss Streak → Pause bis {self.paused_until.strftime('%H:%M:%S')}")

        self.trades.append({
            **trade,
            "timestamp":    datetime.now(timezone.utc).isoformat(),
            "daily_pnl":    round(self.daily_pnl, 2),
            "loss_streak":  self.loss_streak,
            "trade_num":    self.total_trades,
        })
        self._save()

        acc = self.total_wins / self.total_trades * 100 if self.total_trades > 0 else 0
        log.info(
            f"{'✅' if pnl > 0 else '❌'} Trade #{self.total_trades}: "
            f"${pnl:+.2f} | Heute: ${self.daily_pnl:+.2f} | "
            f"Gesamt: ${self.total_pnl:+.2f} | Acc: {acc:.1f}% | "
            f"Streak: {'W' if pnl > 0 else 'L'}{max(self.win_streak, self.loss_streak)}"
        )

    def get_stats(self) -> dict:
        """Aktuelle Statistiken."""
        acc = self.total_wins / self.total_trades * 100 if self.total_trades > 0 else 0
        return {
            "total_trades":  self.total_trades,
            "total_wins":    self.total_wins,
            "accuracy":      round(acc, 1),
            "total_pnl":     round(self.total_pnl, 2),
            "daily_pnl":     round(self.daily_pnl, 2),
            "trades_today":  self.trades_today,
            "loss_streak":   self.loss_streak,
            "win_streak":    self.win_streak,
        }


# ═══════════════════════════════════════════════════════════════
# HAUPT-BOT
# ═══════════════════════════════════════════════════════════════

class PolymarketBTC5MinBot:
    """
    Hauptlogik des Bots.
    
    Ablauf pro 5-Min-Block:
    1. Warte bis Minute 1 des Blocks abgeschlossen ist (~XX:X1:05)
    2. Hole 1m-Kline von Binance → berechne M1-Move
    3. Wenn |M1| ≥ Threshold → Signal generieren (UP/DOWN)
    4. Finde den passenden Polymarket-Markt
    5. Prüfe Preis/Liquidität im Orderbook
    6. Platziere Order wenn Edge vorhanden
    """

    def __init__(self):
        self.running = True
        self.last_block_traded = None
        self.tracker = TradeTracker()

        # Polymarket Client initialisieren
        log.info("═══ Polymarket BTC 5-Min Bot ═══")
        log.info(f"Modus:     {'🧪 DRY RUN (Paper)' if Config.DRY_RUN else '🔴 LIVE TRADING'}")
        log.info(f"Threshold: |M1| ≥ {Config.M1_THRESHOLD}%")
        current_bet = self._get_bet_size()
        log.info(f"Balance:   ${Config.INITIAL_BANKROLL:.2f} (manuell gesetzt — vor Neustart in .env aktualisieren!)")
        log.info(f"Bet Size:  ${current_bet:.2f} (Stufen: ${Config.BET_SIZE} → ${Config.BET_SIZE_200} @ ${Config.SCALE_AT_200} → ${Config.BET_SIZE_300} @ ${Config.SCALE_AT_300})")
        log.info(f"Risk:      Max ${Config.DAILY_LOSS_LIMIT}/Tag, {Config.MAX_LOSS_STREAK}x Streak-Limit")

        if Config.DRY_RUN:
            log.info("Paper-Modus: Keine echten Orders werden platziert")
            self.clob = None
            self.market_finder = None
            self.executor = None
        else:
            self._init_polymarket()

    def _init_polymarket(self):
        """Initialisiere Polymarket CLOB Client."""
        try:
            self.clob = ClobClient(
                host=Config.CLOB_HOST,
                chain_id=Config.CHAIN_ID,
                key=Config.PRIVATE_KEY,
                signature_type=Config.SIG_TYPE,
                funder=Config.FUNDER,
            )

            # API-Credentials ableiten oder manuell setzen
            if Config.API_KEY and Config.API_SECRET and Config.API_PASSPHRASE:
                self.clob.set_api_creds(ApiCreds(
                    api_key=Config.API_KEY,
                    api_secret=Config.API_SECRET,
                    api_passphrase=Config.API_PASSPHRASE,
                ))
                log.info("API Creds: Manuell gesetzt")
            else:
                creds = self.clob.create_or_derive_api_key()
                self.clob.set_api_creds(creds)
                log.info("API Creds: Automatisch abgeleitet")

            self.market_finder = MarketFinder(self.clob)
            self.executor = OrderExecutor(self.clob)

            # Verbindung testen
            ok = self.clob.get_ok()
            log.info(f"Polymarket Verbindung: {'✅ OK' if ok else '❌ FEHLER'}")

        except Exception as e:
            log.error(f"Polymarket Init Fehler: {e}")
            traceback.print_exc()
            sys.exit(1)

    def _get_bet_size(self) -> float:
        """
        Einsatz basierend auf INITIAL_BANKROLL aus .env.
        Internes P&L-Tracking ist unzuverlässig (Resolution kann von Polymarket abweichen).
        → Nur INITIAL_BANKROLL (manuell auf echten Kontostand gesetzt) bestimmt den Einsatz.
        → Vor jedem Neustart INITIAL_BANKROLL in .env auf aktuellen Polymarket-Stand setzen!

        Stufen:
          < $200  → BET_SIZE     (z.B. $5)
          ≥ $200  → BET_SIZE_200 (z.B. $7)
          ≥ $300  → BET_SIZE_300 (z.B. $10)
        """
        balance = Config.INITIAL_BANKROLL
        if balance >= Config.SCALE_AT_300:
            return Config.BET_SIZE_300
        elif balance >= Config.SCALE_AT_200:
            return Config.BET_SIZE_200
        else:
            return Config.BET_SIZE

    def _wait_for_m2(self) -> dict | None:
        """
        Warte bis Minute 2 des aktuellen 5-Min-Blocks fertig ist.
        Für die 3-Wege-Strategie brauchen wir M1 (Signal) UND M2 (Bestätigung/Reversal).
        Returns: Block-Daten oder None wenn zu spät.
        """
        now = datetime.now(timezone.utc)
        block_minute = now.minute % 5
        block_second = now.second

        # Zielzeit: XX:X2:05 (M2 fertig + 5s Buffer für Binance-Kline)
        if block_minute == 0:
            # In Minute 0 → warte Rest von M0 + komplette M1 + komplette M2 + 5s
            wait_secs = (60 - block_second) + 60 + 5
            log.debug(f"Block startet, warte {wait_secs}s auf M1+M2...")
            time.sleep(wait_secs)
        elif block_minute == 1:
            # In Minute 1 → warte Rest von M1 + komplette M2 + 5s
            wait_secs = (60 - block_second) + 5
            log.debug(f"M1 läuft, warte {wait_secs}s auf M2...")
            time.sleep(wait_secs)
        elif block_minute == 2 and block_second < 5:
            # M2 gerade fertig, kurz warten
            time.sleep(5 - block_second)
        elif block_minute >= 3:
            # Zu spät für diesen Block (nur noch <2:55 Restzeit, reicht für
            # Order+Resolution aber wenig Rückversicherung)
            next_block = now.replace(second=0, microsecond=0)
            next_block += timedelta(minutes=(5 - block_minute))
            wait_secs = (next_block - now).total_seconds() + 5
            if wait_secs > 0:
                log.debug(f"Block schon bei M{block_minute}, warte {wait_secs:.0f}s auf nächsten...")
                time.sleep(max(1, wait_secs))
            return None

        # M2 sollte jetzt fertig sein → Daten holen
        data = BinanceData.get_current_block_data()
        return data

    def _evaluate_signal(self, data: dict) -> dict | None:
        """
        3-Wege-Klassifikation basierend auf Backtest (138k Trades, 4.4 Jahre):

        Nach M1+M2 haben wir zwei Informationen:
          1. M1-Richtung (Signal-Hypothese: Block endet in M1-Richtung)
          2. M2-Kumulativ (bestätigt, stagniert oder kehrt um)

        Pfade:
          CONFIRMATION  — M2 hält M1-Richtung mindestens (aligned >= M1-0.01)
                          → trade Signal, Win-Rate ~87.7 % (52k Trades im Backtest)
          REVERSAL      — M2 deutlich unter Block-Open (aligned < -0.05)
                          → trade GEGEN M1, Win-Rate ~73.6 % (6.5k Trades)
          SKIP          — unklare Zone, kein Trade

        Kombiniert: ~84.5 % Win-Rate über 88k Trades (statt 74.5 % bei 138k baseline).
        Konfidenzwerte unten sind aus Bucket-Analyse des Backtests.
        """
        if data.get("status") != "ready":
            return None

        m1_abs    = data["m1_abs"]
        m1_dir    = data["m1_direction"]
        m1_pct    = data["m1_move_pct"]
        m2_pct    = data.get("m2_move_pct")
        threshold = Config.M1_THRESHOLD

        if m1_abs < threshold:
            log.debug(f"Kein Signal: |M1| = {m1_abs:.4f}% < {threshold}% Threshold")
            return None
        if m2_pct is None:
            log.warning("M2-Daten fehlen — skip (sollte nach _wait_for_m2 nicht passieren)")
            return None

        # M2 in Signal-Richtung ausdrücken: positiv = weiter in M1-Richtung
        sign       = 1 if m1_pct > 0 else -1
        m2_aligned = m2_pct * sign

        # ── Pfad A: CONFIRMATION ──
        if m2_aligned >= m1_abs - 0.01:
            mode = "CONFIRM"
            trade_dir = m1_dir
            # Kalibriert aus Backtest-Bucket-Analyse mit M2-Filter (höher als reine M1-Acc)
            if   m1_abs >= 0.20: confidence = 0.93
            elif m1_abs >= 0.15: confidence = 0.91
            elif m1_abs >= 0.10: confidence = 0.89
            elif m1_abs >= 0.08: confidence = 0.87
            else:                confidence = 0.86     # 0.05-0.08
            arrow = "↗" if trade_dir == "UP" else "↘"
            log.info(
                f"📊 SIGNAL [CONFIRM {arrow}]: {trade_dir} | "
                f"M1={m1_pct:+.4f}%, M2={m2_pct:+.4f}% (aligned {m2_aligned:+.4f}%) | "
                f"Confidence: {confidence*100:.0f}% | BTC: ${data['current_price']:,.0f}"
            )

        # ── Pfad B: REVERSAL (M2 deutlich gegen Signal) ──
        elif m2_aligned < -0.05:
            mode = "REVERSAL"
            trade_dir = "DOWN" if m1_dir == "UP" else "UP"   # invertiert
            # Kalibriert: -0.05 bis -0.08 → 73.6%, -0.08 bis -0.10 → 77.2%, <-0.10 → 79.2%
            if   m2_aligned < -0.15: confidence = 0.82
            elif m2_aligned < -0.10: confidence = 0.79
            elif m2_aligned < -0.08: confidence = 0.76
            else:                    confidence = 0.73     # -0.05 bis -0.08
            arrow = "↗" if trade_dir == "UP" else "↘"
            log.info(
                f"🔄 SIGNAL [REVERSAL {arrow}]: {trade_dir} (M1 war {m1_dir}) | "
                f"M1={m1_pct:+.4f}%, M2={m2_pct:+.4f}% | "
                f"Confidence: {confidence*100:.0f}% | BTC: ${data['current_price']:,.0f}"
            )

        # ── Pfad C: SKIP (unklare Zone zwischen Confirmation und Reversal) ──
        else:
            log.info(
                f"⏸  SKIP: M1={m1_pct:+.4f}% ({m1_dir}), "
                f"M2 unklar (aligned {m2_aligned:+.4f}%, weder confirm noch starkes reverse)"
            )
            return None

        return {
            "direction":   trade_dir,
            "confidence":  confidence,
            "m1_move_pct": m1_pct,
            "m1_abs":      m1_abs,
            "m2_move_pct": m2_pct,
            "m2_aligned":  m2_aligned,
            "mode":        mode,
            "btc_price":   data["current_price"],
            "block_start": data["block_start"],
        }

    def _execute_trade(self, signal: dict) -> dict | None:
        """
        Führe den Trade auf Polymarket aus.
        Returns: Trade-Ergebnis oder None.
        """
        direction = signal["direction"]  # "UP" oder "DOWN"
        bet_size = self._get_bet_size()
        log.info(f"💼 Balance: ${Config.INITIAL_BANKROLL:.2f} → Einsatz: ${bet_size:.2f}/Trade")

        if Config.DRY_RUN:
            # Paper Trading: Simuliere Ergebnis mit realistischen Werten
            sim_price  = 0.50  # Simulierter Füllpreis
            sim_shares = round(bet_size / sim_price, 1)
            log.info(f"🧪 PAPER TRADE: {direction} ${bet_size:.2f} → {sim_shares} Shares @ ${sim_price}")
            return {
                "direction":  direction,
                "bet_size":   round(sim_shares * sim_price, 3),
                "buy_price":  sim_price,
                "shares":     sim_shares,
                "bid_price":  sim_price,
                "order_id":   "PAPER",
                "status":     "filled",
                "paper":      True,
            }

        # Live Trading
        # Zeitlimit-Check: wenn < 90 Sek im Block verbleiben → zu spät
        block_start = signal["block_start"]
        block_end   = block_start + timedelta(minutes=5)
        remaining   = (block_end - datetime.now(timezone.utc)).total_seconds()
        if remaining < 90:
            log.warning(f"⏰ Nur noch {remaining:.0f}s im Block — zu spät für sicheren Trade, skip")
            return None

        market = self.market_finder.find_active_market(block_start=block_start)
        if not market:
            log.warning("Kein aktiver BTC 5-Min Markt gefunden")
            return None

        # Token auswählen basierend auf Richtung
        if direction == "UP":
            token_id = market["token_id_up"]
            token_label = "UP/YES"
        else:
            token_id = market["token_id_down"]
            token_label = "DOWN/NO"

        # Orderbook prüfen
        prices = self.market_finder.get_market_prices(
            market["token_id_up"], market["token_id_down"]
        )
        if not prices:
            log.warning("Konnte Preise nicht abrufen")
            return None

        # Preise loggen
        log.info(
            f"📈 Orderbook: UP ask=${prices.get('up_ask','?')} bid=${prices.get('up_bid','?')} | "
            f"DOWN ask=${prices.get('down_ask','?')} bid=${prices.get('down_bid','?')}"
        )

        our_prob  = signal["confidence"]
        ask_price = prices.get(f"{'up' if direction == 'UP' else 'down'}_ask")

        # Markt ist liquid wenn Ask < 0.90 und Ask > 0.05
        market_liquid = ask_price and 0.05 < ask_price < 0.90

        if market_liquid:
            # Liquid: prüfe ob genug Edge vorhanden
            edge = our_prob - ask_price
            log.info(
                f"🔍 Edge-Check: Konfidenz={our_prob*100:.0f}% | Ask={ask_price*100:.0f}% | "
                f"Edge={edge*100:.1f}%"
            )
            # Edge-Threshold 3%: schützt gegen magere CONFIRM-Trades bei hohen Preisen.
            # Bei 86.7% CONFIRM-Konfidenz → Ask ≤ 0.837 nötig → ROI ≥ 3.3%.
            # REVERSAL-Trades (73.6% Konf, typisch Preis 0.50-0.60) haben meist Edge 15-25%,
            # sind also vom strengeren Filter nicht betroffen.
            if edge < 0.03:
                log.warning(f"❌ Edge zu klein ({edge*100:.1f}% < 3%) — skip")
                return None
            buy_price = ask_price

        else:
            # Illiquider Markt (ask=0.99/bid=0.01) → kein Trade
            # FOK Market Orders würden zu 99¢ füllen → kein Edge
            log.warning(
                f"❌ Illiquider Markt (ask={ask_price}) — kein FOK Trade möglich, skip"
            )
            return None

        log.info(
            f"💰 TRADE: {token_label} @ ask ${buy_price:.3f} | "
            f"Konfidenz: {our_prob*100:.0f}% | Bet: ${bet_size:.2f}"
        )

        # FOK Market Order → volle bet_size sofort füllen oder gar nicht
        # (kein Partial Fill mehr — entweder $5 oder nichts)
        result = self.executor.place_market_buy(token_id, bet_size)

        if result:
            # FOK-Check: makingAmount ist der echte USDC-Betrag der gefüllt wurde.
            # KEIN Fallback auf bet_size — das würde Phantom-Trades erzeugen!
            # Wenn makingAmount fehlt oder 0 → Order nicht gefüllt → return None.
            making_raw = result.get("makingAmount")
            taking_raw = result.get("takingAmount")

            try:
                actual_usdc = float(making_raw) if making_raw is not None else 0.0
            except (TypeError, ValueError):
                actual_usdc = 0.0

            if actual_usdc < 0.50:
                log.warning(
                    f"⚠️ FOK nicht gefüllt (makingAmount={making_raw!r}) — skip"
                )
                return None

            # Order gefüllt → echte Shares aus takingAmount (kein Fallback auf Schätzwert)
            try:
                actual_shares = float(taking_raw) if taking_raw and float(taking_raw) > 0 else None
            except (TypeError, ValueError):
                actual_shares = None

            if actual_shares is None:
                # takingAmount fehlt: Schätzung aus USDC / Preis (nur zur Anzeige, kein Trade-Block)
                actual_shares = round(actual_usdc / buy_price, 4)
                log.warning(f"takingAmount fehlt — Shares geschätzt: {actual_shares:.4f}")

            actual_price  = round(actual_usdc / actual_shares, 4) if actual_shares > 0 else buy_price

            log.info(
                f"✅ FOK Fill: {actual_shares:.4f} Shares @ ${actual_price:.4f} "
                f"= ${actual_usdc:.2f} USDC"
            )

            return {
                "direction":    direction,
                "bet_size":     actual_usdc,    # echte USDC ausgegeben
                "buy_price":    actual_price,   # echter Füllpreis
                "shares":       actual_shares,  # echte Shares erhalten
                "bid_price":    buy_price,      # ursprünglicher Bid (zur Info)
                "order_id":     result.get("orderID", "unknown"),
                "status":       "filled",
                "edge":         round(edge * 100, 1),
                "market_slug":  market.get("market_slug", ""),
            }
        return None

    def _pyramid_addon(self, signal: dict, first_trade: dict) -> dict | None:
        """
        Nach erfolgreichem M2-Kauf (CONFIRM-Mode): warte 1 Min auf M3 und
        entscheide ob zusätzlich $15 nachgekauft werden.

        Klassifikation M3:
          - CONF (m3 >= m2 - 0.01): Nachkauf $15 (Win-Rate 95.1% laut Backtest)
          - NEUTRAL (-0.05 bis -0.01): kein Nachkauf (halten, 85.5% WR)
          - BREAK (< m2 - 0.05): kein Nachkauf (halten, 67.6% WR)

        Returns: Addon-Trade-Dict oder None.
        """
        if not Config.PYRAMID_ENABLE:
            return None

        block_start = signal["block_start"]
        direction   = signal["direction"]
        m2_aligned  = signal.get("m2_aligned", 0.0)

        # Warte bis M3 fertig (XX:X3:05) — M2 war bei X2:05, also +60s
        target = block_start + timedelta(minutes=3, seconds=5)
        wait_secs = (target - datetime.now(timezone.utc)).total_seconds()
        if wait_secs > 0:
            log.info(f"🔼 Pyramid: warte {wait_secs:.0f}s auf M3-Entscheidung...")
            time.sleep(wait_secs)

        # Hole aktualisierte Block-Daten (M3 sollte jetzt verfügbar sein)
        data = BinanceData.get_current_block_data()
        if not data or data.get("m3_move_pct") is None:
            log.warning("🔼 Pyramid: M3-Daten fehlen → kein Nachkauf")
            return None

        sign = 1 if signal["m1_move_pct"] > 0 else -1
        m3_aligned = data["m3_move_pct"] * sign
        mode       = signal.get("mode", "CONFIRM")

        # M3-Klassifikation — UNTERSCHIEDLICH je nach Mode!
        # CONFIRM-Mode:  wir wetten in M1-Richtung → M3 soll diese Richtung halten
        #   CONF = M3 >= M2 - 0.01   (Continuation hält)
        #   BREAK = M3 < M2 - 0.05   (M3 bricht gegen M1)
        # REVERSAL-Mode: wir wetten GEGEN M1-Richtung → M3 soll weiter gegen M1 laufen
        #   CONF = M3 <= M2 - 0.02   (Reversal bestätigt sich, noch tiefer)
        #   BREAK = M3 > M2 + 0.05   (bounct zurück Richtung M1, Signal kaputt)
        if mode == "CONFIRM":
            if m3_aligned >= m2_aligned - 0.01:
                m3_class = "CONF"
            elif m3_aligned < m2_aligned - 0.05:
                m3_class = "BREAK"
            else:
                m3_class = "NEUTRAL"
        else:  # REVERSAL
            if m3_aligned <= m2_aligned - 0.02:
                m3_class = "CONF"    # Reversal bestätigt (M3 weiter tiefer)
            elif m3_aligned > m2_aligned + 0.05:
                m3_class = "BREAK"   # bouncet zurück
            else:
                m3_class = "NEUTRAL"

        log.info(
            f"🔼 Pyramid M3-Check [{mode}]: M2_al={m2_aligned:+.4f}%, "
            f"M3_al={m3_aligned:+.4f}% → {m3_class}"
        )

        if m3_class != "CONF":
            log.info(f"🔼 Pyramid: kein Nachkauf ({m3_class}) — halte nur Initial-Position")
            return None

        # Restzeit-Check: mind. 75s bis Block-Ende
        block_end = block_start + timedelta(minutes=5)
        remaining = (block_end - datetime.now(timezone.utc)).total_seconds()
        if remaining < 75:
            log.warning(f"🔼 Pyramid: nur {remaining:.0f}s Rest — zu knapp für Nachkauf")
            return None

        # Markt und Orderbook nochmal frisch holen
        market = self.market_finder.find_active_market(block_start=block_start)
        if not market:
            log.warning("🔼 Pyramid: Markt nicht gefunden")
            return None
        token_id = market["token_id_up"] if direction == "UP" else market["token_id_down"]

        prices = self.market_finder.get_market_prices(
            market["token_id_up"], market["token_id_down"]
        )
        if not prices:
            return None
        ask_price = prices.get(f"{'up' if direction == 'UP' else 'down'}_ask")
        if not ask_price or ask_price > 0.95:
            log.warning(f"🔼 Pyramid: Ask {ask_price} zu hoch/niedrig → kein Nachkauf")
            return None

        # Edge-Check: M3-Bestätigung hebt Konfidenz — Boost unterscheidet sich je nach Mode
        # CONFIRM: von ~87% auf ~95% → +8pp Boost
        # REVERSAL: von ~73% auf ~90% → +17pp Boost (größerer Sprung durch Bestätigung)
        if mode == "CONFIRM":
            boost = 0.08
        else:  # REVERSAL
            boost = 0.17
        our_prob_addon = min(0.95, signal["confidence"] + boost)
        edge = our_prob_addon - ask_price
        log.info(
            f"🔼 Pyramid Edge-Check [{mode}]: Konfidenz={our_prob_addon*100:.0f}% "
            f"(+{boost*100:.0f}pp Boost) | Ask={ask_price*100:.0f}% | Edge={edge*100:.1f}%"
        )
        if edge < 0.03:
            log.info(f"🔼 Pyramid: Edge zu klein ({edge*100:.1f}%) — kein Nachkauf")
            return None

        # Auto-Scale: Addon = Initial-Bet × Multiplier (unless explizit überschrieben)
        initial_bet = self._get_bet_size()
        if Config.PYRAMID_ADDON_BET > 0:
            addon_bet = Config.PYRAMID_ADDON_BET   # manueller Override
        else:
            addon_bet = round(initial_bet * Config.PYRAMID_MULTIPLIER, 2)
        log.info(
            f"🔼 PYRAMID BUY: +${addon_bet:.2f} {direction} @ ask ${ask_price:.3f} "
            f"(Initial-Position bleibt bestehen)"
        )

        result = self.executor.place_market_buy(token_id, addon_bet)
        if not result:
            log.warning("🔼 Pyramid: Nachkauf fehlgeschlagen")
            return None

        try:
            actual_usdc   = float(result.get("makingAmount") or 0)
            actual_shares = float(result.get("takingAmount") or 0)
        except (TypeError, ValueError):
            return None

        if actual_usdc < 0.50 or actual_shares <= 0:
            log.warning("🔼 Pyramid: Fill zu klein oder fehlerhaft")
            return None

        actual_price = round(actual_usdc / actual_shares, 4)
        log.info(
            f"✅ Pyramid Fill: {actual_shares:.4f} Shares @ ${actual_price:.4f} "
            f"= ${actual_usdc:.2f} USDC"
        )

        return {
            "bet_size": actual_usdc,
            "buy_price": actual_price,
            "shares": actual_shares,
            "order_id": result.get("orderID", "unknown"),
        }

    def _merge_legs(self, first: dict, addon: dict) -> dict:
        """Führt zwei Kauf-Legs zu einem konsolidierten Trade zusammen."""
        total_bet    = first["bet_size"] + addon["bet_size"]
        total_shares = first["shares"]   + addon["shares"]
        avg_price    = round(total_bet / total_shares, 4) if total_shares > 0 else first["buy_price"]

        merged = dict(first)
        merged["bet_size"]  = round(total_bet, 4)
        merged["shares"]    = round(total_shares, 4)
        merged["buy_price"] = avg_price
        merged["pyramid"]   = True
        merged["order_id"]  = f"{first['order_id']}+{addon['order_id']}"
        log.info(
            f"🔼 Pyramid konsolidiert: {merged['shares']:.4f} Shares @ Ø ${merged['buy_price']:.4f} "
            f"= ${merged['bet_size']:.2f} total (M2: ${first['bet_size']:.2f} + M3: ${addon['bet_size']:.2f})"
        )
        return merged

    def _check_resolution(self, trade: dict, signal: dict) -> float:
        """
        Prüfe das Ergebnis des Trades (nach Ablauf der 5 Min).
        Nutzt Pyth Network als Preis-Quelle — identisch zu Polymarket.
        Fallback auf Binance wenn Pyth nicht erreichbar.
        Returns: P&L in USDC.
        """
        # Warte bis der 5-Min-Block endet + 20s Buffer für Pyth-Propagation
        block_start = signal["block_start"]
        block_end   = block_start + timedelta(minutes=5, seconds=20)
        now = datetime.now(timezone.utc)

        if now < block_end:
            wait = (block_end - now).total_seconds()
            log.info(f"⏳ Warte {wait:.0f}s auf Block-Ende + Pyth-Propagation...")
            time.sleep(max(1, wait))

        # ── Pyth-Preise holen (gleiche Quelle wie Polymarket) ──
        pyth_open, pyth_close = PythData.get_block_prices(block_start)

        if pyth_open and pyth_close:
            block_open  = pyth_open
            block_close = pyth_close
            price_source = "Pyth"
        else:
            # Fallback: Binance (weniger genau, aber besser als nichts)
            log.warning("Pyth nicht verfügbar — Fallback auf Binance")
            candles = BinanceData.get_klines(limit=12)
            if not candles:
                log.warning("Auch Binance nicht verfügbar — Resolution übersprungen")
                return 0

            block_end_time = block_start + timedelta(minutes=5)
            block_candles  = [c for c in candles if block_start <= c["timestamp"] < block_end_time]
            after_candles  = [c for c in candles if c["timestamp"] >= block_end_time]

            block_open = signal["block_start_price"]
            if block_candles:
                block_close = block_candles[-1]["close"]
            elif after_candles:
                block_close = after_candles[0]["open"]
            else:
                log.warning("Keine Preisdaten für Resolution")
                return 0
            price_source = "Binance"

        # Richtung bestimmen
        actual_dir    = "UP" if block_close > block_open else "DOWN"
        predicted_dir = signal["direction"]
        correct       = actual_dir == predicted_dir

        bet    = trade.get("bet_size", Config.BET_SIZE)
        shares = trade.get("shares") or (bet / trade.get("buy_price", 0.50))

        if correct:
            # Gewinn: Shares * $1 Auszahlung - Einsatz (2% Redemption Fee)
            pnl = round(shares * 1.0 * 0.98 - bet, 2)
        else:
            # Verlust: gesamter Einsatz weg
            pnl = -round(bet, 2)

        log.info(
            f"{'✅' if correct else '❌'} Resolution [{price_source}]: "
            f"Predicted {predicted_dir}, Actual {actual_dir} | "
            f"${block_open:,.2f} → ${block_close:,.2f} "
            f"({'↑' if block_close > block_open else '↓'}{abs(block_close-block_open):.2f}) | "
            f"P&L: ${pnl:+.2f}"
        )

        return pnl

    def run(self):
        """Hauptschleife des Bots."""
        log.info("═══ Bot gestartet ═══")
        current_bet = self._get_bet_size()
        send_telegram(
            f"🤖 <b>Polymarket BTC 5-Min Bot gestartet</b>\n"
            f"Modus: {'Paper' if Config.DRY_RUN else 'LIVE'}\n"
            f"Balance: ${Config.INITIAL_BANKROLL:.2f} | Bet: ${current_bet:.2f}\n"
            f"Threshold: {Config.M1_THRESHOLD}%"
        )

        while self.running:
            try:
                # ── Schritt 1: Risk-Check ──
                can_trade, reason = self.tracker.can_trade()
                if not can_trade:
                    log.info(f"⏸️  {reason}")
                    time.sleep(30)
                    continue

                # ── Schritt 2: Warte auf M1 ──
                data = self._wait_for_m2()
                if not data:
                    continue

                # Duplikat-Check
                block_start = data.get("block_start")
                if block_start and block_start == self.last_block_traded:
                    log.debug("Block bereits getradet, überspringe...")
                    time.sleep(10)
                    continue

                # ── Schritt 3: Signal evaluieren ──
                signal = self._evaluate_signal(data)
                if not signal:
                    time.sleep(5)
                    continue

                signal["block_start_price"] = data["block_open"]

                # ── Schritt 4: Trade ausführen ──
                trade = self._execute_trade(signal)
                # Block immer als "versucht" markieren — verhindert Endlosschleife
                self.last_block_traded = block_start
                if not trade:
                    log.warning("Trade nicht ausgeführt — warte auf nächsten Block")
                    time.sleep(60)
                    continue

                # ── Schritt 4b: Pyramid-Nachkauf bei M3-Bestätigung ──
                # Für CONFIRM-Mode: +$15 wenn M3 Continuation bestätigt (95% WR)
                # Für REVERSAL-Mode: +$15 wenn M3 Reversal bestätigt (90% WR)
                # Initial-$5 steht, 1 Min auf M3 warten, dann ggf. nachlegen.
                if (Config.PYRAMID_ENABLE
                        and not Config.DRY_RUN
                        and signal.get("mode") in ("CONFIRM", "REVERSAL")
                        and not trade.get("paper")):
                    addon = self._pyramid_addon(signal, trade)
                    if addon:
                        trade = self._merge_legs(trade, addon)

                # ── Schritt 5: Resolution prüfen ──
                pnl = self._check_resolution(trade, signal)

                # ── Schritt 6: Trade aufzeichnen ──
                self.tracker.record_trade({
                    "direction":  signal["direction"],
                    "m1_move":    signal["m1_move_pct"],
                    "m1_abs":     signal["m1_abs"],
                    "btc_price":  signal["btc_price"],
                    "buy_price":  trade.get("buy_price", 0.50),
                    "bet_size":   trade.get("bet_size", Config.BET_SIZE),
                    "pnl":        pnl,
                    "correct":    pnl > 0,
                    "paper":      trade.get("paper", False),
                })

                # Telegram Update alle 10 Trades
                stats = self.tracker.get_stats()
                if stats["total_trades"] % 10 == 0:
                    cur_bet = self._get_bet_size()
                    send_telegram(
                        f"📊 <b>Update #{stats['total_trades']}</b>\n"
                        f"Accuracy: {stats['accuracy']}%\n"
                        f"Heute: ${stats['daily_pnl']:+.2f} ({stats['trades_today']} Trades)\n"
                        f"Einsatz: ${cur_bet:.2f}/Trade"
                    )

            except KeyboardInterrupt:
                log.info("Bot gestoppt (Ctrl+C)")
                self.running = False
            except Exception as e:
                log.error(f"Fehler in Hauptschleife: {e}")
                traceback.print_exc()
                time.sleep(30)

        # Shutdown
        stats = self.tracker.get_stats()
        log.info(f"═══ Bot beendet | Trades: {stats['total_trades']} | P&L: ${stats['total_pnl']:+.2f} | Acc: {stats['accuracy']}% ═══")
        send_telegram(f"🛑 Bot beendet | ${stats['total_pnl']:+.2f} P&L | {stats['accuracy']}% Acc")


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

LOCKFILE = Path("bot.pid")

def _acquire_lock() -> bool:
    """
    Verhindert dass mehrere Bot-Instanzen gleichzeitig laufen.
    Schreibt PID in bot.pid. Wenn eine andere Instanz läuft → Exit.
    """
    if LOCKFILE.exists():
        try:
            old_pid = int(LOCKFILE.read_text().strip())
            # Prüfen ob Prozess noch lebt (Unix: kill -0 = kein Signal, nur Existenz-Check)
            os.kill(old_pid, 0)
            log.error(
                f"❌ Bot läuft bereits als PID {old_pid} — nur eine Instanz erlaubt!\n"
                f"   Stoppen mit: kill {old_pid}\n"
                f"   Oder: pkill -f bot.py"
            )
            return False
        except (ProcessLookupError, ValueError):
            # Prozess existiert nicht mehr → altes Lockfile entfernen
            log.warning(f"Altes Lockfile (PID {LOCKFILE.read_text().strip()}) überschrieben")
            LOCKFILE.unlink(missing_ok=True)

    LOCKFILE.write_text(str(os.getpid()))
    return True

def _release_lock():
    """Lockfile beim Beenden entfernen."""
    try:
        if LOCKFILE.exists():
            pid = int(LOCKFILE.read_text().strip())
            if pid == os.getpid():
                LOCKFILE.unlink()
    except Exception:
        pass

def main():
    # ── Singleton-Schutz: nur eine Bot-Instanz ──
    if not _acquire_lock():
        sys.exit(1)

    try:
        bot = PolymarketBTC5MinBot()
        signal.signal(signal.SIGINT,  lambda *_: setattr(bot, 'running', False))
        signal.signal(signal.SIGTERM, lambda *_: setattr(bot, 'running', False))
        bot.run()
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
