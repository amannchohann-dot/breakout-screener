#!/usr/bin/env python3
"""
Backtest der "Liquidity Grab"-Strategie (XAU/USD, 15min) aus dem Twitter-Thread:

  Indikatoren:
    - EMA 30 (Trendfilter): Close > EMA30 = nur Longs, Close < EMA30 = nur Shorts
    - "Support and Resistance Levels with Breaks" [LuxAlgo], Left/Right Bars = 1
      -> Support  = letztes Pivot-Low  (low[i] < low[i-1] und low[i] < low[i+1])
      -> Resistance = letztes Pivot-High (high[i] > high[i-1] und high[i] > high[i+1])
      Pivots werden erst 1 Kerze spaeter bestaetigt (rightBars = 1).

  Long-Setup ("Liquidity Grab"):
    - Kerze bricht das Support-Level (low < support), schliesst aber darueber (close > support)
    - Close > EMA30
    - Entry: Buy-Stop am Hoch dieser Kerze
    - Stop-Loss: Tief dieser Kerze
    - Take-Profit: 1:1 (Entry + Risiko)

  Short-Setup: spiegelbildlich (high > resistance, close < resistance, Close < EMA30).

  Konventionen (im Thread nicht spezifiziert, hier konservativ gewaehlt):
    - Pending-Order verfaellt, wenn vor dem Fill das Setup-Tief/-Hoch gerissen wird
      oder nach ORDER_TTL Kerzen.
    - Trifft eine Kerze SL und TP gleichzeitig, zaehlt der Trade als Verlust
      (Anzahl solcher Faelle wird separat ausgewiesen).
    - Kosten: Spread/Slippage pro Trade konfigurierbar (Standard: 0.25 USD round-trip).

Datenquelle: Interactive Brokers, London Gold (XAUUSD Spot), 15-Minuten-Kerzen.
Aufruf: python3 liquidity_grab_backtest.py <ohlc.json>
"""
import json
import sys


def ema(values, period):
    k = 2 / (period + 1)
    out = [None] * len(values)
    if len(values) < period:
        return out
    sma = sum(values[:period]) / period
    out[period - 1] = sma
    for i in range(period, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


def run(data, cost=0.25, order_ttl=20, both_hit_counts_as="loss"):
    t, o, h, l, c = data["time"], data["open"], data["high"], data["low"], data["close"]
    n = len(c)
    ema30 = ema(c, 30)

    support = None      # letztes bestaetigtes Pivot-Low
    resistance = None   # letztes bestaetigtes Pivot-High

    trades = []
    pending = None      # (dir, entry, sl, tp, created_idx, setup_time)
    position = None     # (dir, entry, sl, tp, entry_time)

    for i in range(2, n):
        # Pivot mit left=right=1: Bar i-1 ist Pivot, bestaetigt auf Bar i
        if l[i - 1] < l[i - 2] and l[i - 1] < l[i]:
            support = l[i - 1]
        if h[i - 1] > h[i - 2] and h[i - 1] > h[i]:
            resistance = h[i - 1]

        # ---- offene Position verwalten ----
        if position:
            d, entry, sl, tp, et = position
            hit_sl = l[i] <= sl if d == "long" else h[i] >= sl
            hit_tp = h[i] >= tp if d == "long" else l[i] <= tp
            if hit_sl and hit_tp:
                res = -abs(entry - sl) if both_hit_counts_as == "loss" else abs(tp - entry)
                trades.append({"dir": d, "entry_time": et, "exit_time": t[i],
                               "risk": abs(entry - sl), "pnl": res - cost, "ambiguous": True})
                position = None
            elif hit_sl:
                trades.append({"dir": d, "entry_time": et, "exit_time": t[i],
                               "risk": abs(entry - sl), "pnl": -abs(entry - sl) - cost, "ambiguous": False})
                position = None
            elif hit_tp:
                trades.append({"dir": d, "entry_time": et, "exit_time": t[i],
                               "risk": abs(entry - sl), "pnl": abs(tp - entry) - cost, "ambiguous": False})
                position = None
            if position:
                continue  # immer nur ein Trade gleichzeitig

        # ---- Pending-Order verwalten ----
        if pending:
            d, entry, sl, tp, ci, st = pending
            invalid = (l[i] < sl) if d == "long" else (h[i] > sl)
            filled = (h[i] >= entry) if d == "long" else (l[i] <= entry)
            if filled:
                position = (d, entry, sl, tp, t[i])
                pending = None
                # Konservativ: Fill-Kerze selbst kann bereits SL/TP treffen
                dd, entry2, sl2, tp2, et = position
                hit_sl = l[i] <= sl2 if dd == "long" else h[i] >= sl2
                hit_tp = h[i] >= tp2 if dd == "long" else l[i] <= tp2
                if hit_sl and hit_tp:
                    res = -abs(entry2 - sl2) if both_hit_counts_as == "loss" else abs(tp2 - entry2)
                    trades.append({"dir": dd, "entry_time": et, "exit_time": t[i],
                                   "risk": abs(entry2 - sl2), "pnl": res - cost, "ambiguous": True})
                    position = None
                elif hit_sl:
                    trades.append({"dir": dd, "entry_time": et, "exit_time": t[i],
                                   "risk": abs(entry2 - sl2), "pnl": -abs(entry2 - sl2) - cost, "ambiguous": False})
                    position = None
                elif hit_tp:
                    trades.append({"dir": dd, "entry_time": et, "exit_time": t[i],
                                   "risk": abs(entry2 - sl2), "pnl": abs(tp2 - entry2) - cost, "ambiguous": False})
                    position = None
            elif invalid or i - ci > order_ttl:
                pending = None

        if position or pending:
            continue

        # ---- neues Setup suchen (auf der aktuellen, geschlossenen Kerze i) ----
        if ema30[i] is None:
            continue
        # Long: Liquidity Grab unter Support
        if support is not None and l[i] < support and c[i] > support and c[i] > ema30[i]:
            entry, sl = h[i], l[i]
            if entry > sl:
                pending = ("long", entry, sl, entry + (entry - sl), i, t[i])
        # Short: Liquidity Grab ueber Resistance
        elif resistance is not None and h[i] > resistance and c[i] < resistance and c[i] < ema30[i]:
            entry, sl = l[i], h[i]
            if sl > entry:
                pending = ("short", entry, sl, entry - (sl - entry), i, t[i])

    return trades


def summarize(trades, label):
    if not trades:
        print(f"{label}: keine Trades")
        return
    wins = [x for x in trades if x["pnl"] > 0]
    losses = [x for x in trades if x["pnl"] <= 0]
    ambiguous = [x for x in trades if x["ambiguous"]]
    total_r = sum(x["pnl"] / x["risk"] for x in trades if x["risk"] > 0)
    avg_risk = sum(x["risk"] for x in trades) / len(trades)
    longs = [x for x in trades if x["dir"] == "long"]
    shorts = [x for x in trades if x["dir"] == "short"]
    print(f"--- {label} ---")
    print(f"Trades: {len(trades)}  (Long: {len(longs)}, Short: {len(shorts)})")
    print(f"Winrate: {100 * len(wins) / len(trades):.1f}%  (Gewinner: {len(wins)}, Verlierer: {len(losses)})")
    print(f"Netto-Ergebnis: {total_r:+.1f} R  |  Erwartungswert: {total_r / len(trades):+.3f} R/Trade")
    print(f"Durchschnittliches Risiko (SL-Distanz): {avg_risk:.2f} USD")
    print(f"Kerzen mit SL+TP in derselben Kerze (als Verlust gezaehlt): {len(ambiguous)}")
    print()


if __name__ == "__main__":
    path = sys.argv[1]
    data = json.load(open(path))
    print(f"Daten: {len(data['close'])} x 15min-Kerzen, {data['chart_start']} bis {data['chart_end']}\n")

    summarize(run(data, cost=0.0), "Ohne Kosten (Spread = 0)")
    summarize(run(data, cost=0.25), "Mit realistischen Kosten (0.25 USD Spread/Slippage pro Trade)")
    summarize(run(data, cost=0.50), "Mit hohen Kosten (0.50 USD pro Trade)")
