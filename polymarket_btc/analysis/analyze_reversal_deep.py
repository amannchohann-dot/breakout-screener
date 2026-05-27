#!/usr/bin/env python3
"""
REVERSAL-tiefe Analyse — wo sind die besten Invers-Trades versteckt?
"""
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

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

signals = []
for bk in sorted(blocks.keys()):
    mins = blocks[bk]
    if len(mins) != 5: continue
    mins.sort()
    if [m for m, _, _ in mins] != [0, 1, 2, 3, 4]: continue
    bo  = mins[0][1]
    m1c, m2c, m3c, m4c, bc = mins[0][2], mins[1][2], mins[2][2], mins[3][2], mins[4][2]
    m1 = (m1c - bo) / bo * 100
    if abs(m1) < THRESHOLD: continue
    if bc == bo: continue
    sign = 1 if m1 > 0 else -1
    signals.append({
        "m1_abs": abs(m1),
        "m1":     m1 * sign,
        "m2":     (m2c - bo) / bo * 100 * sign,
        "m3":     (m3c - bo) / bo * 100 * sign,
        "m4":     (m4c - bo) / bo * 100 * sign,
        "bc_al":  (bc  - bo) / bo * 100 * sign,
        "inv_win": (bc - bo) / bo * 100 * sign < 0,
    })

# Alle REVERSAL-Kandidaten (M2 < -0.05, invers gewettet)
rev = [s for s in signals if s["m2"] < -0.05]
print(f"REVERSAL-Kandidaten: {len(rev):,} (Baseline Invers-WR: "
      f"{sum(1 for s in rev if s['inv_win'])/len(rev)*100:.2f}%)\n")

# ── 1) REVERSAL-Tiefe vs WR ──
print("─── 1) Wie tief muss M2 brechen? (feinere Buckets) ───")
print(f"{'M2-Bereich':<20}{'N':>8}{'%vRev':>9}{'Inv-WR':>10}")
buckets = [
    (-0.08, -0.05), (-0.10, -0.08), (-0.15, -0.10),
    (-0.20, -0.15), (-99,   -0.20)
]
for lo, hi in buckets:
    matches = [s for s in rev if lo <= s["m2"] < hi]
    if not matches: continue
    wr = sum(1 for s in matches if s["inv_win"]) / len(matches) * 100
    print(f"{lo:5.2f}..{hi:5.2f}       {len(matches):>8,}{len(matches)/len(rev)*100:>8.1f}%{wr:>9.1f}%")

# ── 2) M1-Magnitude × REVERSAL-Tiefe ──
print()
print("─── 2) Qualitäts-Heatmap: |M1| × M2-Tiefe ───")
print("(Zeigt wo REVERSAL wirklich ausgeprägt ist)\n")
m1_b = [(0.05, 0.08), (0.08, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 99)]
m2_b = [(-99, -0.20), (-0.20, -0.15), (-0.15, -0.10), (-0.10, -0.08), (-0.08, -0.05)]

print(f"{'|M1|':<13}", end="")
for lo, hi in m2_b:
    hdr = f"M2∈[{lo:.2f},{hi:.2f})" if lo > -99 else f"M2 < {hi}"
    print(f"{hdr:<20}", end="")
print()
for lo_m1, hi_m1 in m1_b:
    lbl = f"{lo_m1:.2f}-{hi_m1:.2f}" if hi_m1 < 99 else f">={lo_m1:.2f}"
    print(f"{lbl:<13}", end="")
    for lo_m2, hi_m2 in m2_b:
        matches = [s for s in rev
                   if lo_m1 <= s["m1_abs"] < hi_m1
                   and lo_m2 <= s["m2"] < hi_m2]
        if len(matches) < 30:
            print(f"{'—':<20}", end="")
            continue
        wr = sum(1 for s in matches if s["inv_win"]) / len(matches) * 100
        print(f"{wr:>5.0f}% N={len(matches):<5}  ", end="")
    print()

# ── 3) M3-Check auf REVERSAL ──
print()
print("─── 3) M3 als Zusatz-Bestätigung für REVERSAL ───")
print("(Falls wir noch 1 Min länger warten könnten)\n")
print(f"{'M3-Bedingung':<50}{'N':>8}{'%vRev':>9}{'Inv-WR':>10}")

sub = [
    ("Baseline (nur M2 < -0.05)",                 lambda s: True),
    ("M3 bleibt tief (M3 <= M2)",                 lambda s: s["m3"] <= s["m2"]),
    ("M3 fällt weiter (M3 <= M2 - 0.02)",         lambda s: s["m3"] <= s["m2"] - 0.02),
    ("M3 bricht noch stärker (M3 <= M2 - 0.05)",  lambda s: s["m3"] <= s["m2"] - 0.05),
    ("M3 bounct zurück (M3 > M2 + 0.02)",         lambda s: s["m3"] > s["m2"] + 0.02),
    ("M3 bounct über Open zurück (M3 > 0)",       lambda s: s["m3"] > 0),
    ("M3 bestätigt aber nicht voll (M3 < -0.05)", lambda s: s["m3"] < -0.05),
]
for name, cond in sub:
    matches = [s for s in rev if cond(s)]
    if not matches: continue
    wr = sum(1 for s in matches if s["inv_win"]) / len(matches) * 100
    print(f"{name:<50}{len(matches):>8,}{len(matches)/len(rev)*100:>8.1f}%{wr:>9.1f}%")

# ── 4) Der reinste Reversal-Filter ──
print()
print("─── 4) Elite-REVERSAL-Filter (Kombination der besten Signale) ───\n")
elite = [
    ("REV baseline (M2 < -0.05)",
     lambda s: True),
    ("REV stark (M2 < -0.10)",
     lambda s: s["m2"] < -0.10),
    ("REV + schwaches M1 (|M1| < 0.10)",
     lambda s: s["m1_abs"] < 0.10),
    ("REV stark + schwaches M1 (|M1| < 0.10, M2 < -0.10)",
     lambda s: s["m1_abs"] < 0.10 and s["m2"] < -0.10),
    ("REV + M3 fällt weiter",
     lambda s: s["m3"] <= s["m2"] - 0.02),
    ("REV stark + M3 fällt weiter",
     lambda s: s["m2"] < -0.10 and s["m3"] <= s["m2"] - 0.02),
    ("REV stark + schwaches M1 + M3 fällt weiter",
     lambda s: s["m1_abs"] < 0.10 and s["m2"] < -0.10 and s["m3"] <= s["m2"] - 0.02),
]
print(f"{'Filter':<60}{'N':>8}{'Inv-WR':>10}{'EV@50¢':>10}{'EV@55¢':>10}")
for name, cond in elite:
    matches = [s for s in rev if cond(s)]
    if len(matches) < 50: continue
    wr = sum(1 for s in matches if s["inv_win"]) / len(matches)
    # EV bei verschiedenen Polymarket-Preisen (Bet = $5)
    ev_50 = (wr * 0.50 - (1 - wr) * 0.50) * 5
    ev_55 = (wr * 0.45 - (1 - wr) * 0.55) * 5
    print(f"{name:<60}{len(matches):>8,}{wr*100:>9.1f}%{ev_50:>+9.2f}{ev_55:>+9.2f}")
