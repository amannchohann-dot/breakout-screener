#!/usr/bin/env python3
"""
Backtest: Trendline-Breakout-Strategie auf Basis von
"Trendlines with Breaks [LuxAlgo]" (Pine Script v5), portiert nach Python.

Indikator-Logik (originalgetreu, Non-Backpainting = kein Lookahead):
  - Pivot-High/Low mit left = right = length (Standard: 14),
    bestaetigt erst `length` Kerzen spaeter.
  - Steigung: ATR(length) / length * mult  (Methode 'Atr', Standard mult = 1)
  - Ab einem bestaetigten Pivot-High faellt eine Widerstands-Trendlinie mit
    dieser Steigung; ab einem Pivot-Low steigt eine Unterstuetzungs-Trendlinie.
  - Upward Breakout:  erster Close ueber der fallenden Linie  (upos 0 -> 1)
  - Downward Breakout: erster Close unter der steigenden Linie (dnos 0 -> 1)
  - ta.atr nutzt Wilder-RMA; hier identisch implementiert.

Trade-Management (im Indikator nicht definiert, hier festgelegt):
  - Entry: Open der Kerze NACH der Signalkerze (Alert kommt zum Kerzenschluss).
  - Stop-Loss: atr_mult x ATR(14) vom Entry.
  - Take-Profit: RR x Stop-Distanz.
  - Optional EMA30-Trendfilter (nur Longs ueber, Shorts unter der EMA).
  - Eine Position gleichzeitig; SL+TP in derselben Kerze = Verlust (konservativ).
  - Kosten: 0.25 USD pro Trade.

Aufruf: python3 trendline_breakout.py
"""
import json
from improvement_variants import ema, stats, split


def atr_rma(h, l, c, period):
    n = len(c)
    tr = [None] * n
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    out = [None] * n
    if n <= period:
        return out
    out[period] = sum(tr[1:period + 1]) / period
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def signals(data, length=14, mult=1.0):
    """Liefert Liste von (bar_index, 'up'|'down') Breakout-Signalen."""
    h, l, c = data["high"], data["low"], data["close"]
    n = len(c)
    atr = atr_rma(h, l, c, length)

    upper = lower = None          # Linienwert am Pivot (Pine: var upper/lower)
    slope_ph = slope_pl = 0.0
    upos = dnos = 0
    out = []

    for i in range(2 * length, n):
        p = i - length            # Pivot-Kandidat, bestaetigt auf Bar i
        is_ph = all(h[p] > h[p - k] for k in range(1, length + 1)) and \
                all(h[p] > h[p + k] for k in range(1, length + 1))
        is_pl = all(l[p] < l[p - k] for k in range(1, length + 1)) and \
                all(l[p] < l[p + k] for k in range(1, length + 1))
        slope = (atr[i] / length * mult) if atr[i] else None
        if slope is None:
            continue

        if is_ph:
            slope_ph = slope
            upper = h[p]
        elif upper is not None:
            upper -= slope_ph

        if is_pl:
            slope_pl = slope
            lower = l[p]
        elif lower is not None:
            lower += slope_pl

        # Realtime-Linienwert = Pivotwert minus/plus Steigung ueber die
        # length Kerzen seit dem tatsaechlichen Pivot (Pine: upper - slope_ph*length)
        prev_upos, prev_dnos = upos, dnos
        if is_ph:
            upos = 0
        elif upper is not None and c[i] > upper - slope_ph * length:
            upos = 1
        if is_pl:
            dnos = 0
        elif lower is not None and c[i] < lower + slope_pl * length:
            dnos = 1

        if upos > prev_upos:
            out.append((i, "up"))
        if dnos > prev_dnos:
            out.append((i, "down"))
    return out


def run_trades(data, sigs, rr=1.0, atr_mult=1.5, ema_filter=False,
               cost=0.25, length=14):
    t, o, h, l, c = data["time"], data["open"], data["high"], data["low"], data["close"]
    n = len(c)
    atr = atr_rma(h, l, c, length)
    ema30 = ema(c, 30)
    sig_at = {}
    for i, d in sigs:
        sig_at.setdefault(i, []).append(d)

    trades = []
    position = None  # (dir, entry, sl, tp, entry_time)

    for i in range(n):
        if position:
            d, entry, sl, tp, et = position
            hit_sl = l[i] <= sl if d == "long" else h[i] >= sl
            hit_tp = h[i] >= tp if d == "long" else l[i] <= tp
            if hit_sl:  # both-hit zaehlt konservativ als Verlust
                trades.append({"dir": d, "entry_time": et, "risk": abs(entry - sl),
                               "pnl": -abs(entry - sl) - cost})
                position = None
            elif hit_tp:
                trades.append({"dir": d, "entry_time": et, "risk": abs(entry - sl),
                               "pnl": abs(tp - entry) - cost})
                position = None
            continue

        # Signal auf Kerze i-1 -> Entry zum Open von Kerze i
        for d in sig_at.get(i - 1, []):
            if atr[i - 1] is None or ema30[i - 1] is None:
                continue
            risk = atr_mult * atr[i - 1]
            if d == "up":
                if ema_filter and c[i - 1] <= ema30[i - 1]:
                    continue
                position = ("long", o[i], o[i] - risk, o[i] + rr * risk, t[i])
            else:
                if ema_filter and c[i - 1] >= ema30[i - 1]:
                    continue
                position = ("short", o[i], o[i] + risk, o[i] - rr * risk, t[i])
            break
    return trades


TIMEFRAMES = [
    ("15m", "xauusd_15m.json"),
    ("30m", "xauusd_30m.json"),
    ("1h",  "xauusd_1h.json"),
    ("2h",  "xauusd_2h.json"),
    ("4h",  "xauusd_4h.json"),
]

if __name__ == "__main__":
    variants = [
        ("RR 1:1, SL 1.5xATR",            {"rr": 1.0}),
        ("RR 2:1, SL 1.5xATR",            {"rr": 2.0}),
        ("RR 2:1 + EMA30-Filter",         {"rr": 2.0, "ema_filter": True}),
        ("RR 3:1, SL 1.5xATR",            {"rr": 3.0}),
    ]
    for tf, path in TIMEFRAMES:
        data = json.load(open(path))
        is_data, oos_data = split(data)
        print(f"===== {tf}  ({data['chart_start'][:10]} bis {data['chart_end'][:10]}, "
              f"{len(data['close'])} Kerzen, {len(signals(data))} Signale) =====")
        for name, kw in variants:
            print(f"  {name}")
            print(f"    Gesamt: {stats(run_trades(data, signals(data), **kw))}")
            print(f"    IS:     {stats(run_trades(is_data, signals(is_data), **kw))}")
            print(f"    OOS:    {stats(run_trades(oos_data, signals(oos_data), **kw))}")
        print()
