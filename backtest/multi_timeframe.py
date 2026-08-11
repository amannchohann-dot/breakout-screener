#!/usr/bin/env python3
"""
Multi-Timeframe-Test der Liquidity-Grab-Strategie (XAUUSD).

Gleiche Regeln wie im Thread bzw. die besten Varianten aus
improvement_variants.py, angewendet auf 15m/30m/1h/2h/4h.
Der Datenanbieter (IBKR) liefert max. ~3.500 Kerzen pro Abfrage, daher
deckt jeder hoehere Timeframe automatisch eine laengere Periode ab:

  15m ≈ 2 Monate, 30m ≈ 3.5 Monate, 1h ≈ 7 Monate,
  2h ≈ 14 Monate, 4h ≈ 2.4 Jahre

Getestet wird pro Timeframe:
  1. Original wie im Thread (Pivot 1/1, RR 1:1)
  2. Nur RR 2:1
  3. Kombi: Pivot 5/5 + RR 2:1 (+ Session-Filter 07-20 UTC nur intraday <= 1h)

Jeweils mit In-Sample/Out-of-Sample-Split (1./2. Datenhaelfte).
Kosten: 0.25 USD pro Trade.

Aufruf: python3 multi_timeframe.py
"""
import json
from improvement_variants import run, stats, split

TIMEFRAMES = [
    ("15m", "xauusd_15m.json"),
    ("30m", "xauusd_30m.json"),
    ("1h",  "xauusd_1h.json"),
    ("2h",  "xauusd_2h.json"),
    ("4h",  "xauusd_4h.json"),
]

LONDON_NY = set(range(7, 20))

if __name__ == "__main__":
    for tf, path in TIMEFRAMES:
        data = json.load(open(path))
        is_data, oos_data = split(data)
        intraday = tf in ("15m", "30m", "1h")

        variants = [
            ("Original (Pivot 1/1, RR 1:1)", {}),
            ("RR 2:1", {"rr": 2.0}),
            ("Kombi: Pivot 5/5 + RR 2" + (" + Session" if intraday else ""),
             {"pivot_bars": 5, "rr": 2.0, "hours": LONDON_NY if intraday else None}),
        ]

        print(f"===== {tf}  ({data['chart_start'][:10]} bis {data['chart_end'][:10]}, "
              f"{len(data['close'])} Kerzen) =====")
        for name, kw in variants:
            print(f"  {name}")
            print(f"    Gesamt: {stats(run(data, **kw))}")
            print(f"    IS:     {stats(run(is_data, **kw))}")
            print(f"    OOS:    {stats(run(oos_data, **kw))}")
        print()
