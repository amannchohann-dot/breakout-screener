#!/usr/bin/env python3
"""
Trendline-Breakout v2: Stop-Loss- und Exit-Varianten, inkl. Langzeittest.

Aufbauend auf trendline_breakout.py (LuxAlgo-Port, Signale unveraendert):

  Stop-Loss-Varianten:
    - 'atr':    1.5 x ATR(14) vom Entry (wie v1)
    - 'candle': Tief der Ausbruchskerze (Long) bzw. Hoch (Short)

  Exit-Varianten:
    - Fixes RR-Ziel (1, 2, 3)
    - 'breakeven': ab +1R (Schluss einer Kerze ueber Entry+1R) wird der SL
      auf Entry gezogen (wirksam ab der Folgekerze — keine Intrabar-Annahme)
    - 'opposite': kein TP; Exit beim naechsten Gegensignal (Open der
      Folgekerze), Initial-SL bleibt aktiv

  Daten: 2h (14 Monate), 4h (2.4 Jahre) und NEU 1d (2013-2026, 13.6 Jahre —
  enthaelt Baerenmarkt 2013-2015, Seitwaertsphasen 2016-2018 und 2021-2022,
  Bullenmaerkte 2019-2020 und 2023-2026 sowie den Spike/Crash Anfang 2026).

  Konservative Konventionen wie gehabt: Entry am Open nach der Signalkerze,
  SL+TP in derselben Kerze = Verlust, eine Position, 0.25 USD Kosten/Trade.

Aufruf: python3 trendline_v2.py
"""
import json
from improvement_variants import stats, split
from trendline_breakout import signals, atr_rma


def run_trades_v2(data, sigs, rr=2.0, sl_mode="atr", atr_mult=1.5,
                  breakeven=False, exit_opposite=False, cost=0.25, length=14):
    t, o, h, l, c = data["time"], data["open"], data["high"], data["low"], data["close"]
    n = len(c)
    atr = atr_rma(h, l, c, length)
    sig_at = {}
    for i, d in sigs:
        sig_at.setdefault(i, []).append(d)

    trades = []
    position = None  # dict: dir, entry, sl, tp, risk, be_armed

    for i in range(n):
        if position:
            p = position
            d = p["dir"]
            # Breakeven wird ab der Folgekerze wirksam
            if breakeven and p["be_armed"]:
                p["sl"] = max(p["sl"], p["entry"]) if d == "long" else min(p["sl"], p["entry"])
                p["be_armed"] = False

            hit_sl = l[i] <= p["sl"] if d == "long" else h[i] >= p["sl"]
            hit_tp = p["tp"] is not None and \
                (h[i] >= p["tp"] if d == "long" else l[i] <= p["tp"])
            opp = exit_opposite and any(
                (d == "long" and s == "down") or (d == "short" and s == "up")
                for s in sig_at.get(i - 1, []))

            if hit_sl:  # konservativ: SL gewinnt bei Mehrfach-Treffern
                pnl = (p["sl"] - p["entry"]) if d == "long" else (p["entry"] - p["sl"])
                trades.append({"dir": d, "entry_time": p["et"], "risk": p["risk"],
                               "pnl": pnl - cost})
                position = None
            elif hit_tp:
                pnl = abs(p["tp"] - p["entry"])
                trades.append({"dir": d, "entry_time": p["et"], "risk": p["risk"],
                               "pnl": pnl - cost})
                position = None
            elif opp:
                pnl = (o[i] - p["entry"]) if d == "long" else (p["entry"] - o[i])
                trades.append({"dir": d, "entry_time": p["et"], "risk": p["risk"],
                               "pnl": pnl - cost})
                position = None
            else:
                if breakeven:
                    trig = p["entry"] + p["risk"] if d == "long" else p["entry"] - p["risk"]
                    if (d == "long" and c[i] >= trig) or (d == "short" and c[i] <= trig):
                        p["be_armed"] = True
                continue

        if position:
            continue

        for d in sig_at.get(i - 1, []):
            if atr[i - 1] is None:
                continue
            entry = o[i]
            if sl_mode == "atr":
                risk = atr_mult * atr[i - 1]
                sl = entry - risk if d == "up" else entry + risk
            else:  # 'candle': Extrem der Ausbruchskerze
                sl = l[i - 1] if d == "up" else h[i - 1]
                risk = (entry - sl) if d == "up" else (sl - entry)
                if risk <= 0:
                    continue
            tp = None if exit_opposite else \
                (entry + rr * risk if d == "up" else entry - rr * risk)
            position = {"dir": "long" if d == "up" else "short", "entry": entry,
                        "sl": sl, "tp": tp, "risk": risk, "et": t[i], "be_armed": False}
            break
    return trades


TIMEFRAMES = [
    ("2h", "xauusd_2h.json"),
    ("4h", "xauusd_4h.json"),
    ("1d", "xauusd_1d.json"),
]

VARIANTS = [
    ("ATR-SL, RR 1:1",              {"sl_mode": "atr", "rr": 1.0}),
    ("ATR-SL, RR 2:1",              {"sl_mode": "atr", "rr": 2.0}),
    ("ATR-SL, RR 3:1",              {"sl_mode": "atr", "rr": 3.0}),
    ("Kerzen-SL, RR 1:1",           {"sl_mode": "candle", "rr": 1.0}),
    ("Kerzen-SL, RR 2:1",           {"sl_mode": "candle", "rr": 2.0}),
    ("Kerzen-SL, RR 3:1",           {"sl_mode": "candle", "rr": 3.0}),
    ("ATR-SL, RR 2:1 + Breakeven",  {"sl_mode": "atr", "rr": 2.0, "breakeven": True}),
    ("ATR-SL, RR 3:1 + Breakeven",  {"sl_mode": "atr", "rr": 3.0, "breakeven": True}),
    ("ATR-SL, Exit bei Gegensignal", {"sl_mode": "atr", "exit_opposite": True}),
    ("Kerzen-SL, Exit bei Gegensignal", {"sl_mode": "candle", "exit_opposite": True}),
]

if __name__ == "__main__":
    for tf, path in TIMEFRAMES:
        data = json.load(open(path))
        is_data, oos_data = split(data)
        sigs_all = signals(data)
        print(f"===== {tf}  ({data['time'][0][:10]} bis {data['time'][-1][:10]}, "
              f"{len(data['close'])} Kerzen, {len(sigs_all)} Signale) =====")
        for name, kw in VARIANTS:
            print(f"  {name}")
            print(f"    Gesamt: {stats(run_trades_v2(data, sigs_all, **kw))}")
            print(f"    IS:     {stats(run_trades_v2(is_data, signals(is_data), **kw))}")
            print(f"    OOS:    {stats(run_trades_v2(oos_data, signals(oos_data), **kw))}")
        print()
