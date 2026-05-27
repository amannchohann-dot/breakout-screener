#!/usr/bin/env python3
"""
Weitere Edge-Kandidaten jenseits von M1+M2:

  1. Tageszeit (UTC-Stunde) → manche Sessions volatiler/klarer
  2. Vorherige 5-Min-Block-Richtung → Autokorrelation?
  3. M3 als Zusatz-Filter auf CONFIRM → noch präzisere Auswahl
  4. M1-Magnitude × M2-Alignment Heatmap → wo ist der echte Sweet Spot
"""
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

CSV_PATH  = Path(__file__).parent / "footprint_BTCUSDT_1m_2022-01-01_2026-04-13.csv"
THRESHOLD = 0.05

print(f"Lese {CSV_PATH.name} …")
blocks = defaultdict(list)
with open(CSV_PATH, newline="") as f:
    for row in csv.DictReader(f):
        try:
            dt = datetime.strptime(row["timestamp_utc"], "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        ep = int(dt.timestamp() // 60)
        blocks[ep // 5].append((ep % 5, float(row["open"]), float(row["close"])))

# ── Signal-Trades extrahieren mit vollen Infos ──
signals = []
block_keys_sorted = sorted(blocks.keys())
prev_block_dir = {}   # block_k → "UP"/"DOWN"/None

# Erstmal Block-Richtungen ermitteln (für Autocorrelation)
block_dirs = {}
for bk in block_keys_sorted:
    mins = blocks[bk]
    if len(mins) != 5: continue
    mins.sort()
    if [m for m, _, _ in mins] != [0, 1, 2, 3, 4]: continue
    bo, bc = mins[0][1], mins[4][2]
    if bc > bo:   block_dirs[bk] = "UP"
    elif bc < bo: block_dirs[bk] = "DOWN"
    else:         block_dirs[bk] = None

for bk in block_keys_sorted:
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
    block_dt = datetime.utcfromtimestamp(bk * 300)
    signals.append({
        "bk":       bk,
        "m1_abs":   abs(m1),
        "m1_dir":   "UP" if m1 > 0 else "DOWN",
        "m1":       m1 * sign,                 # |M1|
        "m2":       (m2c - bo) / bo * 100 * sign,
        "m3":       (m3c - bo) / bo * 100 * sign,
        "m4":       (m4c - bo) / bo * 100 * sign,
        "bc":       (bc  - bo) / bo * 100 * sign,
        "sig_win":  (bc - bo) / bo * 100 * sign > 0,
        "hour":     block_dt.hour,
        "dow":      block_dt.weekday(),         # 0=Mon
        "prev_dir": block_dirs.get(bk - 1),
    })

n = len(signals)
print(f"  {n:,} Signal-Trades\n")

# ── 1) Tageszeit-Effekt ──
print("─── HYPOTHESE 1: Tageszeit-Effekt (UTC-Stunde) ───")
print(f"{'Stunde (UTC)':<15}{'Session':<18}{'N':>8}{'WR':>8}{'Edge vs Baseline':>20}")
by_hour = defaultdict(lambda: {"n": 0, "w": 0})
for s in signals:
    by_hour[s["hour"]]["n"] += 1
    if s["sig_win"]: by_hour[s["hour"]]["w"] += 1
baseline_wr = sum(1 for s in signals if s["sig_win"]) / n

def session(h):
    if 0 <= h < 6:    return "Asia Night"
    if 6 <= h < 8:    return "Asia/EU Over"
    if 8 <= h < 13:   return "EU Morning"
    if 13 <= h < 17:  return "EU/US Open"
    if 17 <= h < 22:  return "US Afternoon"
    return "US Close/Asia"

for h in range(24):
    d = by_hour[h]
    if d["n"] == 0: continue
    wr = d["w"] / d["n"]
    edge = (wr - baseline_wr) * 100
    marker = " ★" if abs(edge) > 2 else ""
    print(f"{h:>2}:00-{h+1:>2}:00       {session(h):<18}{d['n']:>8,}{wr*100:>7.1f}%{edge:>+18.2f}pp{marker}")

# ── 2) Previous-Block-Autokorrelation ──
print()
print("─── HYPOTHESE 2: Autokorrelation mit vorherigem Block ───")
print(f"{'Vorher':<15}{'Signal-Richt.':<15}{'N':>8}{'WR':>8}{'Edge':>10}")
by_prev = defaultdict(lambda: {"n": 0, "w": 0})
for s in signals:
    if s["prev_dir"] is None: continue
    key = (s["prev_dir"], s["m1_dir"])
    by_prev[key]["n"] += 1
    if s["sig_win"]: by_prev[key]["w"] += 1

for prev in ["UP", "DOWN"]:
    for sig in ["UP", "DOWN"]:
        d = by_prev[(prev, sig)]
        if d["n"] == 0: continue
        wr = d["w"] / d["n"]
        edge = (wr - baseline_wr) * 100
        label = "SAME" if prev == sig else "OPP"
        print(f"  prev={prev:<8}   sig={sig:<8}   {d['n']:>8,}{wr*100:>7.1f}% {edge:>+7.2f}pp  ({label})")

# ── 3) M3-Filter: was passiert NACH M2 ──
print()
print("─── HYPOTHESE 3: M3 als Zusatz-Filter auf CONFIRM-Pfad ───")
print("(Kontext: wenn M1+M2 CONFIRM signalisieren, gibt M3 nochmal Info?)")
print()
print(f"{'M3-Bedingung auf CONFIRM':<50}{'N':>8}{'%vConf':>9}{'WR':>8}")
confirm = [s for s in signals if s["m2"] >= s["m1"] - 0.01]
n_c = len(confirm)
wr_c = sum(1 for s in confirm if s["sig_win"]) / n_c * 100

sub_confirm = [
    ("Baseline (nur M1+M2)",         lambda s: True),
    ("M3 >= M2 (hält Continuation)", lambda s: s["m3"] >= s["m2"]),
    ("M3 >= M2 - 0.02",              lambda s: s["m3"] >= s["m2"] - 0.02),
    ("M3 weiter pos (m3 > 0)",       lambda s: s["m3"] > 0),
    ("M3 noch stärker (m3 >= m2+0.02)", lambda s: s["m3"] >= s["m2"] + 0.02),
    ("M3 fällt leicht (m2-0.05 <= m3 < m2)", lambda s: s["m2"] - 0.05 <= s["m3"] < s["m2"]),
    ("M3 bricht stark ein (m3 < m2 - 0.05)",  lambda s: s["m3"] < s["m2"] - 0.05),
]
for name, cond in sub_confirm:
    matches = [s for s in confirm if cond(s)]
    if not matches: continue
    wr = sum(1 for s in matches if s["sig_win"]) / len(matches) * 100
    print(f"{name:<50}{len(matches):>8,}{len(matches)/n_c*100:>8.1f}%{wr:>7.1f}%")

# ── 4) M1-Magnitude × M2-Alignment Heatmap ──
print()
print("─── HYPOTHESE 4: Heatmap Win-Rate nach M1-Stärke × M2-Bewegung ───")
print()
print("(Zeilen = |M1|, Spalten = M2-Bewegung relativ zu M1)")
m1_buckets = [(0.05, 0.08), (0.08, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 99)]
m2_buckets = [
    ("M2 < m1-0.15",   lambda m1, m2: m2 < m1 - 0.15),
    ("m1-0.15..-0.05", lambda m1, m2: m1 - 0.15 <= m2 < m1 - 0.05),
    ("m1-0.05..-0.01", lambda m1, m2: m1 - 0.05 <= m2 < m1 - 0.01),
    ("m1-0.01..+0.02", lambda m1, m2: m1 - 0.01 <= m2 < m1 + 0.02),
    ("m1+0.02..+0.10", lambda m1, m2: m1 + 0.02 <= m2 < m1 + 0.10),
    ("M2 > m1+0.10",   lambda m1, m2: m2 >= m1 + 0.10),
]

print(f"{'|M1|':<15}", end="")
for name, _ in m2_buckets: print(f"{name:<18}", end="")
print()
for lo, hi in m1_buckets:
    label = f"{lo:.2f}-{hi:.2f}" if hi < 99 else f">={lo:.2f}"
    print(f"{label:<15}", end="")
    for _, cond in m2_buckets:
        matches = [s for s in signals if lo <= s["m1"] < hi and cond(s["m1"], s["m2"])]
        if len(matches) < 100:
            print(f"{'—':<18}", end="")
            continue
        wr = sum(1 for s in matches if s["sig_win"]) / len(matches) * 100
        inv_wr = sum(1 for s in matches if not s["sig_win"]) / len(matches) * 100
        # Annotation: S=Signal besser, I=Invers besser
        if wr > 75: tag = "SIG"
        elif inv_wr > 70: tag = "INV"
        else: tag = "mix"
        print(f"{wr:4.0f}% N={len(matches)//1000}k {tag:<5}", end="")
    print()

# ── 5) Kombinations-Idee: Session + Mode ──
print()
print("─── HYPOTHESE 5: Beste Session für Reversal-Trades ───")
print()
rev_signals = [s for s in signals if s["m2"] < -0.05]
print(f"Gesamt REVERSAL: {len(rev_signals):,} Trades, Invers-WR: "
      f"{sum(1 for s in rev_signals if not s['sig_win'])/len(rev_signals)*100:.1f}%")
print()
by_sess_rev = defaultdict(lambda: {"n": 0, "inv_w": 0})
for s in rev_signals:
    sess = session(s["hour"])
    by_sess_rev[sess]["n"] += 1
    if not s["sig_win"]: by_sess_rev[sess]["inv_w"] += 1

print(f"{'Session':<20}{'N':>8}{'Inv-WR':>10}")
for sess in ["Asia Night", "Asia/EU Over", "EU Morning", "EU/US Open",
              "US Afternoon", "US Close/Asia"]:
    d = by_sess_rev[sess]
    if d["n"] == 0: continue
    wr = d["inv_w"] / d["n"] * 100
    print(f"{sess:<20}{d['n']:>8,}{wr:>9.1f}%")
