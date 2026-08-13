#!/usr/bin/env python3
"""
Positionsgroessen- und Hebel-Simulation fuer die Trendline-Breakout-Strategie
(Kerzen-SL + RR 3:1) auf einem 5.000-USD-Konto.

Logik:
  - Pro Trade wird ein fester Prozentsatz f des aktuellen Kontostands riskiert.
  - Positionsgroesse (Unzen) = Risikobetrag / Stop-Distanz (USD/Unze).
  - Effektiver Hebel = (Unzen x Einstiegskurs) / Kontostand
    -> ergibt sich automatisch, je enger der Stop, desto groesser Position & Hebel.
  - Equity compoundiert: equity *= 1 + f * R_i  (R_i = Trade-Ergebnis in R).

Auswertung pro Risikostufe f:
  - Endkapital, Rendite p.a., max. Drawdown (historische Trade-Reihenfolge)
  - Verteilung des effektiven Hebels (Median / Maximum)
  - Bootstrap-Monte-Carlo (10.000 Laeufe, Ziehen mit Zuruecklegen):
    Median-Ergebnis, 5%-Quantil, P(Konto halbiert sich zwischenzeitlich)

Aufruf: python3 position_sizing.py
"""
import json
import random
from trendline_breakout import signals
from trendline_v2 import run_trades_v2


def enrich_with_price(data, trades):
    """Ergaenzt jeden Trade um Einstiegskurs (Open der Entry-Kerze)."""
    idx = {ts: i for i, ts in enumerate(data["time"])}
    for x in trades:
        x["entry_price"] = data["open"][idx[x["entry_time"]]]
    return trades


def simulate(trades, start=5000.0, f=0.01):
    equity = start
    peak = start
    max_dd = 0.0
    levs = []
    for x in trades:
        risk_usd = equity * f
        ounces = risk_usd / x["risk"]
        levs.append(ounces * x["entry_price"] / equity)
        equity *= 1 + f * (x["pnl"] / x["risk"])
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1)
        if equity <= 0:
            break
    levs.sort()
    return {"end": equity, "max_dd": max_dd,
            "lev_med": levs[len(levs) // 2], "lev_max": levs[-1]}


def bootstrap(trades, start=5000.0, f=0.01, runs=10000, seed=42):
    rng = random.Random(seed)
    rs = [x["pnl"] / x["risk"] for x in trades]
    n = len(rs)
    ends, ruins = [], 0
    for _ in range(runs):
        eq, peak, halved = start, start, False
        for _ in range(n):
            eq *= 1 + f * rng.choice(rs)
            peak = max(peak, eq)
            if eq <= peak / 2:
                halved = True
        ends.append(eq)
        ruins += halved
    ends.sort()
    return {"median": ends[len(ends) // 2], "p05": ends[int(0.05 * len(ends))],
            "p_halved": ruins / runs}


if __name__ == "__main__":
    START = 5000.0
    for tf, path, years in [("4h", "xauusd_4h.json", 2.38),
                            ("1d", "xauusd_1d.json", 13.6)]:
        data = json.load(open(path))
        trades = enrich_with_price(
            data, run_trades_v2(data, signals(data), sl_mode="candle", rr=3.0))
        per_year = len(trades) / years
        print(f"===== {tf}: {len(trades)} Trades ueber {years:.1f} Jahre "
              f"(~{per_year:.0f}/Jahr), Startkapital {START:.0f} USD =====")
        for f in (0.005, 0.01, 0.02, 0.03, 0.05):
            s = simulate(trades, START, f)
            b = bootstrap(trades, START, f)
            cagr = (s["end"] / START) ** (1 / years) - 1
            print(f"  Risiko {f * 100:.1f}%/Trade "
                  f"({START * f:.0f} USD beim Start):")
            print(f"    Historisch: Ende {s['end']:>9.0f} USD | {cagr * 100:+6.1f}% p.a. "
                  f"| max DD {s['max_dd'] * 100:5.1f}%")
            print(f"    Hebel: Median {s['lev_med']:.1f}x, Maximum {s['lev_max']:.1f}x")
            print(f"    Monte-Carlo: Median {b['median']:>9.0f} USD | "
                  f"5%-Quantil {b['p05']:>9.0f} USD | "
                  f"P(zwischenzeitlich halbiert) {b['p_halved'] * 100:.1f}%")
        print()
