#!/usr/bin/env python3
"""
Multi-Asset-Test der Trendline-Breakout-Strategie (Kerzen-SL, RR 3:1 & Varianten).

Die Konfiguration wurde auf XAUUSD entwickelt — jeder weitere Markt ist damit
ein echter Out-of-Instrument-Test ohne erneutes Parameter-Tuning.

Verfuegbare Maerkte (IBKR): London Silver (XAGUSD) 4h + 1d.
Nicht verfuegbar in dieser Session:
  - SPY / US-Aktien & -Indizes / Forex: "Session is connected from a different
    IP address" — das IBKR-Konto ist parallel woanders eingeloggt (TWS/Mobile),
    was konkurrierende Marktdaten-Sessions blockiert.
  - BTC (PAXOS/ZEROHASH): "No market data permissions" — im IBKR-Konto ist
    kein Krypto-Marktdaten-Abo aktiviert.

Kosten werden relativ skaliert: gleicher relativer Spread wie im Gold-Test
(0.25 USD bei ~4000 USD Goldpreis ≈ 0.6 Basispunkte vom Kurs).

Aufruf: python3 multi_asset.py
"""
import json
from improvement_variants import stats, split
from trendline_breakout import signals
from trendline_v2 import run_trades_v2

ASSETS = [
    ("Silber 4h (2,4 J.)",  "xagusd_4h.json"),
    ("Silber 1d (13,6 J.)", "xagusd_1d.json"),
]

VARIANTS = [
    ("Kerzen-SL RR 3:1", {"sl_mode": "candle", "rr": 3.0}),
    ("Kerzen-SL RR 2:1", {"sl_mode": "candle", "rr": 2.0}),
    ("ATR-SL RR 3:1",    {"sl_mode": "atr",    "rr": 3.0}),
]

if __name__ == "__main__":
    for label, path in ASSETS:
        data = json.load(open(path))
        is_d, oos_d = split(data)
        avg_price = sum(data["close"]) / len(data["close"])
        cost = 0.25 * avg_price / 4000   # relativer Spread wie beim Gold-Test
        print(f"===== {label}: {data['time'][0][:10]} bis {data['time'][-1][:10]}, "
              f"Kosten {cost:.3f} USD/Trade =====")
        for name, kw in VARIANTS:
            print(f"  {name}")
            print(f"    Gesamt: {stats(run_trades_v2(data, signals(data), cost=cost, **kw))}")
            print(f"    IS:     {stats(run_trades_v2(is_d, signals(is_d), cost=cost, **kw))}")
            print(f"    OOS:    {stats(run_trades_v2(oos_d, signals(oos_d), cost=cost, **kw))}")
        print()
