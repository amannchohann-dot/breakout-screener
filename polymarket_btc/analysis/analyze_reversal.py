#!/usr/bin/env python3
"""
Reversal-Analyse: Wenn M2 stark gegen das M1-Signal läuft, ist der Block
signifikant öfter in M2-Richtung → Invers-Wette lohnt sich.
"""
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

CSV_PATH  = Path(__file__).parent / "footprint_BTCUSDT_1m_2022-01-01_2026-04-13.csv"
THRESHOLD = 0.05

blocks = defaultdict(list)
with open(CSV_PATH, newline="") as f:
    for row in csv.DictReader(f):
        try:
            dt = datetime.strptime(row["timestamp_utc"], "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        ep = int(dt.timestamp() // 60)
        blocks[ep // 5].append((ep % 5, float(row["open"]), float(row["close"])))

stats = []
for bk, mins in blocks.items():
    if len(mins) != 5: continue
    mins.sort()
    if [m for m, _, _ in mins] != [0, 1, 2, 3, 4]: continue
    bo  = mins[0][1]
    m1c, m2c, m3c, m4c, bc = mins[0][2], mins[1][2], mins[2][2], mins[3][2], mins[4][2]
    m1_pct = (m1c - bo) / bo * 100
    if abs(m1_pct) < THRESHOLD: continue
    if bc == bo: continue
    sign = 1 if m1_pct > 0 else -1
    stats.append({
        "m1":   m1_pct * sign,
        "m2":   (m2c - bo) / bo * 100 * sign,
        "m3":   (m3c - bo) / bo * 100 * sign,
        "m4":   (m4c - bo) / bo * 100 * sign,
        "bc":   (bc  - bo) / bo * 100 * sign,
        "sig_win":  (bc - bo) / bo * 100 * sign > 0,
        "inv_win":  (bc - bo) / bo * 100 * sign < 0,
    })

n = len(stats)
print(f"Signal-Trades gesamt: {n:,}\n")

# ── Invers-Wette Szenarien ──
print("─── 3-Wege-Strategie: Confirmation / Skip / Reversal ───")
print()
print(f"{'Bedingung':<60}{'N':>8}{'%vAll':>8}{'SigWin':>9}{'InvWin':>9}")
print()

scenarios = [
    ("BASELINE: sofort nach M1, immer Signal",
     lambda s: True, "sig"),
    ("─ CONFIRMATION (M2 weiter in Signal-Richtung) ─", None, None),
    ("  M2 >= M1 (mind. gehalten)",
     lambda s: s["m2"] >= s["m1"], "sig"),
    ("  M2 >= M1 + 0.02 (echte Continuation)",
     lambda s: s["m2"] >= s["m1"] + 0.02, "sig"),
    ("  M2 >= M1 + 0.05 (starke Continuation)",
     lambda s: s["m2"] >= s["m1"] + 0.05, "sig"),
    ("─ REVERSAL (M2 gegen Signal → wette INVERS) ─", None, None),
    ("  M2 < 0 (unter Block-Open)",
     lambda s: s["m2"] < 0, "inv"),
    ("  M2 < -0.02 (deutlich unter Open)",
     lambda s: s["m2"] < -0.02, "inv"),
    ("  M2 < -0.05 (stark unter Open)",
     lambda s: s["m2"] < -0.05, "inv"),
    ("  M2 < -0.10 (sehr stark unter Open)",
     lambda s: s["m2"] < -0.10, "inv"),
    ("─ REVERSAL bei M3 (mehr Zeit, späterer Einstieg) ─", None, None),
    ("  M3 < 0",
     lambda s: s["m3"] < 0, "inv"),
    ("  M3 < -0.05",
     lambda s: s["m3"] < -0.05, "inv"),
    ("  M2 und M3 beide < 0 (kein Rebound)",
     lambda s: s["m2"] < 0 and s["m3"] < 0, "inv"),
]

for row in scenarios:
    if row[1] is None:
        print(f"{row[0]}")
        continue
    name, cond, mode = row
    matches = [s for s in stats if cond(s)]
    if not matches:
        continue
    sig_wr = sum(1 for s in matches if s["sig_win"]) / len(matches) * 100
    inv_wr = sum(1 for s in matches if s["inv_win"]) / len(matches) * 100
    pct    = len(matches) / n * 100
    print(f"{name:<60}{len(matches):>8,}{pct:>7.1f}%{sig_wr:>8.1f}%{inv_wr:>8.1f}%")

# ── Konkret: 3-Wege-Entscheidungsregel ──
print()
print("─── Proposed 3-Wege-Regel ───")
print()

def classify(s):
    # CONFIRMATION: M2 mindestens gehalten oder weiter
    if s["m2"] >= s["m1"] - 0.01:
        return "SIG"
    # REVERSAL: M2 deutlich unter Block-Open
    if s["m2"] < -0.02:
        return "INV"
    # Alles dazwischen: SKIP
    return "SKIP"

buckets = defaultdict(lambda: {"n": 0, "sig_w": 0, "inv_w": 0})
for s in stats:
    c = classify(s)
    buckets[c]["n"]     += 1
    buckets[c]["sig_w"] += int(s["sig_win"])
    buckets[c]["inv_w"] += int(s["inv_win"])

print(f"{'Regel':<20}{'N':>10}{'%':>8}{'Action':>12}{'WinRate':>10}")
total_n = sum(b["n"] for b in buckets.values())
for c in ["SIG", "INV", "SKIP"]:
    b = buckets[c]
    if c == "SIG":
        action = "trade Signal"
        wr = b["sig_w"] / b["n"] * 100
    elif c == "INV":
        action = "trade INVERS"
        wr = b["inv_w"] / b["n"] * 100
    else:
        action = "skip"
        wr = 0
    print(f"{c:<20}{b['n']:>10,}{b['n']/total_n*100:>7.1f}%{action:>12}{wr:>9.1f}%")

# ── Kombinierte Gesamt-Accuracy vs reine Baseline ──
total_trades = buckets["SIG"]["n"] + buckets["INV"]["n"]
total_wins   = buckets["SIG"]["sig_w"] + buckets["INV"]["inv_w"]
print()
print(f"Kombinierte Strategie:  {total_trades:,} Trades, "
      f"Win-Rate {total_wins/total_trades*100:.2f}%")
print(f"Baseline (alle M1):     {n:,} Trades, "
      f"Win-Rate {sum(1 for s in stats if s['sig_win'])/n*100:.2f}%")

# ── Feinheit: ganz starke Reversals separat ──
print()
print("─── Fine-Tune: sehr starke Reversals (hohe Invers-Win-Rate) ───")
print()
thresholds = [-0.02, -0.05, -0.08, -0.10, -0.15, -0.20]
print(f"{'M2 < (threshold)':<20}{'N':>10}{'% v.all':>10}{'InvWin':>10}{'AvgM1':>10}")
for t in thresholds:
    matches = [s for s in stats if s["m2"] < t]
    if not matches: continue
    wr  = sum(1 for s in matches if s["inv_win"]) / len(matches) * 100
    avg = mean(s["m1"] for s in matches)
    print(f"{t:<20.2f}{len(matches):>10,}{len(matches)/n*100:>9.1f}%{wr:>9.1f}%{avg:>9.3f}%")
