#!/usr/bin/env python3
"""
Verbesserungs-Varianten der Liquidity-Grab-Strategie, getestet gegen dieselben
XAUUSD-15min-Daten wie der Basis-Backtest (liquidity_grab_backtest.py).

Parametrisierte Version der Strategie:
  - pivot_bars:  Left/Right Bars fuer Pivot-Levels (Thread: 1 -> Rauschen)
  - rr:          Take-Profit als Vielfaches des Risikos (Thread: 1.0)
  - hours:       erlaubte Entry-Stunden in UTC (None = alle, wie im Thread)
  - min_sweep:   Mindest-Sweep-Tiefe unter/ueber dem Level, als Anteil der
                 Kerzen-Range (0 = aus, wie im Thread)
  - ema_slope:   zusaetzlich steigende/fallende EMA30 verlangen (Thread: nein)
  - direction:   'both', 'long', 'short'

Jede Variante wird auf der ersten Datenhaelfte (In-Sample) und der zweiten
(Out-of-Sample) getrennt ausgewertet: Nur was in BEIDEN Haelften funktioniert,
ist ein Kandidat — alles andere ist Kurvenanpassung.

Aufruf: python3 improvement_variants.py xauusd_15m.json
"""
import json
import sys


def ema(values, period):
    k = 2 / (period + 1)
    out = [None] * len(values)
    if len(values) < period:
        return out
    out[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


def run(data, cost=0.25, order_ttl=20, pivot_bars=1, rr=1.0, hours=None,
        min_sweep=0.0, ema_slope=False, direction="both"):
    t, o, h, l, c = data["time"], data["open"], data["high"], data["low"], data["close"]
    n = len(c)
    ema30 = ema(c, 30)
    pb = pivot_bars

    support = None
    resistance = None
    trades = []
    pending = None
    position = None

    def close_position(i, d, entry, sl, tp, et):
        hit_sl = l[i] <= sl if d == "long" else h[i] >= sl
        hit_tp = h[i] >= tp if d == "long" else l[i] <= tp
        if hit_sl and hit_tp:      # konservativ: Verlust
            return {"dir": d, "entry_time": et, "risk": abs(entry - sl),
                    "pnl": -abs(entry - sl) - cost}
        if hit_sl:
            return {"dir": d, "entry_time": et, "risk": abs(entry - sl),
                    "pnl": -abs(entry - sl) - cost}
        if hit_tp:
            return {"dir": d, "entry_time": et, "risk": abs(entry - sl),
                    "pnl": abs(tp - entry) - cost}
        return None

    for i in range(2 * pb, n):
        # Pivot mit left=right=pb: Bar i-pb ist Pivot, bestaetigt auf Bar i
        p = i - pb
        if all(l[p] < l[p - k] for k in range(1, pb + 1)) and \
           all(l[p] < l[p + k] for k in range(1, pb + 1)):
            support = l[p]
        if all(h[p] > h[p - k] for k in range(1, pb + 1)) and \
           all(h[p] > h[p + k] for k in range(1, pb + 1)):
            resistance = h[p]

        if position:
            d, entry, sl, tp, et = position
            res = close_position(i, d, entry, sl, tp, et)
            if res:
                trades.append(res)
                position = None
            else:
                continue

        if pending:
            d, entry, sl, tp, ci, st = pending
            invalid = (l[i] < sl) if d == "long" else (h[i] > sl)
            filled = (h[i] >= entry) if d == "long" else (l[i] <= entry)
            if filled:
                position = (d, entry, sl, tp, t[i])
                pending = None
                res = close_position(i, d, entry, sl, tp, t[i])
                if res:
                    trades.append(res)
                    position = None
            elif invalid or i - ci > order_ttl:
                pending = None

        if position or pending or ema30[i] is None:
            continue
        if hours is not None and int(t[i][11:13]) not in hours:
            continue

        rng = h[i] - l[i]
        if rng <= 0:
            continue

        long_ok = direction in ("both", "long")
        short_ok = direction in ("both", "short")
        slope_up = (not ema_slope) or (ema30[i - 5] is not None and ema30[i] > ema30[i - 5])
        slope_dn = (not ema_slope) or (ema30[i - 5] is not None and ema30[i] < ema30[i - 5])

        if long_ok and support is not None and l[i] < support and c[i] > support \
                and c[i] > ema30[i] and slope_up \
                and (support - l[i]) >= min_sweep * rng:
            entry, sl = h[i], l[i]
            pending = ("long", entry, sl, entry + rr * (entry - sl), i, t[i])
        elif short_ok and resistance is not None and h[i] > resistance and c[i] < resistance \
                and c[i] < ema30[i] and slope_dn \
                and (h[i] - resistance) >= min_sweep * rng:
            entry, sl = l[i], h[i]
            pending = ("short", entry, sl, entry - rr * (sl - entry), i, t[i])

    return trades


def stats(trades):
    if not trades:
        return "     0 Trades"
    wins = sum(1 for x in trades if x["pnl"] > 0)
    r = sum(x["pnl"] / x["risk"] for x in trades if x["risk"] > 0)
    return f"{len(trades):>4} Trades | WR {100 * wins / len(trades):5.1f}% | {r:+6.1f} R | EV {r / len(trades):+.3f} R/T"


def split(data, frac=0.5):
    n = int(len(data["close"]) * frac)
    a = {k: (v[:n] if isinstance(v, list) else v) for k, v in data.items()}
    b = {k: (v[n:] if isinstance(v, list) else v) for k, v in data.items()}
    return a, b


if __name__ == "__main__":
    data = json.load(open(sys.argv[1]))
    is_data, oos_data = split(data)

    LONDON_NY = set(range(7, 20))  # 07:00-19:59 UTC

    variants = [
        ("A  Original (Thread: Pivot 1/1, RR 1:1)", {}),
        ("B  Pivot 5/5 (echte Levels)", {"pivot_bars": 5}),
        ("C  Pivot 10/10", {"pivot_bars": 10}),
        ("D  RR 2:1 statt 1:1", {"rr": 2.0}),
        ("E  Session-Filter London/NY (07-20 UTC)", {"hours": LONDON_NY}),
        ("F  EMA30-Slope-Filter", {"ema_slope": True}),
        ("G  Mindest-Sweep 25% der Range", {"min_sweep": 0.25}),
        ("H  Nur Shorts", {"direction": "short"}),
        ("I  Kombi: Pivot 5 + Session + RR 2", {"pivot_bars": 5, "hours": LONDON_NY, "rr": 2.0}),
        ("J  Kombi: Pivot 5 + Session + Slope + RR 1.5",
         {"pivot_bars": 5, "hours": LONDON_NY, "ema_slope": True, "rr": 1.5}),
    ]

    print(f"Daten: {len(data['close'])} Kerzen | In-Sample = 1. Haelfte, Out-of-Sample = 2. Haelfte")
    print(f"Kosten: 0.25 USD/Trade\n")
    for name, kw in variants:
        print(name)
        print(f"  Gesamt: {stats(run(data, **kw))}")
        print(f"  IS:     {stats(run(is_data, **kw))}")
        print(f"  OOS:    {stats(run(oos_data, **kw))}")
        print()
