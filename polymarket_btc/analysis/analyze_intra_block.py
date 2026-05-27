#!/usr/bin/env python3
"""
Intra-Block-Analyse: Wie bewegt sich BTC nach M1, und gibt es einen
besseren Einstiegszeitpunkt als sofort nach Minute 1?

Für jeden Signal-Block:
  - M1-Richtung (UP/DOWN)
  - Bewegung Minute 2, 3, 4 (relativ zum Block-Open in %)
  - Bedingte Win-Quote: gegeben M_n-Bewegung, wie oft endet Block in M1-Richtung?

Ziel: prüfen ob ein "warten auf Pullback"-Setup höhere Acc UND besseren Preis bringt.
"""
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median

CSV_PATH  = Path(__file__).parent / "footprint_BTCUSDT_1m_2022-01-01_2026-04-13.csv"
THRESHOLD = 0.05

print(f"Lese {CSV_PATH.name} …")
blocks = defaultdict(list)
with open(CSV_PATH, newline="") as f:
    r = csv.DictReader(f)
    for row in r:
        try:
            dt = datetime.strptime(row["timestamp_utc"], "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        ep_min  = int(dt.timestamp() // 60)
        block_k = ep_min // 5
        min_in  = ep_min %  5
        blocks[block_k].append((min_in, float(row["open"]), float(row["close"])))

print(f"  {len(blocks):,} Blocks geladen\n")

# ── Bewegungs-Stats pro Minute, nach Signal-Richtung ──
# Für jeden Signal-Block: speichere %-Bewegung close_min_n / block_open
# in Signal-Richtung (positiv = pro Signal, negativ = gegen)
stats = []     # list of dicts
for bk, mins in blocks.items():
    if len(mins) != 5: continue
    mins.sort()
    if [m for m, _, _ in mins] != [0, 1, 2, 3, 4]: continue

    bo  = mins[0][1]
    m1c = mins[0][2]
    m2c = mins[1][2]
    m3c = mins[2][2]
    m4c = mins[3][2]
    bc  = mins[4][2]

    m1_pct = (m1c - bo) / bo * 100
    if abs(m1_pct) < THRESHOLD: continue
    if bc == bo: continue

    sign = 1 if m1_pct > 0 else -1     # +1 = UP-Signal, -1 = DOWN-Signal
    # Bewegungen "in Signal-Richtung" (positiv = bullish für Signal)
    m1_dir = (m1c - bo) / bo * 100 * sign       # = |M1| (immer positiv)
    m2_dir = (m2c - bo) / bo * 100 * sign       # nach Min 2 (kumuliert)
    m3_dir = (m3c - bo) / bo * 100 * sign
    m4_dir = (m4c - bo) / bo * 100 * sign
    bc_dir = (bc  - bo) / bo * 100 * sign       # finaler Outcome (>0 = win)

    win = bc_dir > 0

    stats.append({
        "m1": m1_dir, "m2": m2_dir, "m3": m3_dir, "m4": m4_dir, "bc": bc_dir,
        "win": win,
    })

n = len(stats)
print(f"Signal-Trades: {n:,}\n")

# ── 1) Durchschnittliche kumul. Bewegung nach M_n (in Signal-Richtung) ──
print("─── Durchschn. kumul. Bewegung in Signal-Richtung (in % vom Block-Open) ───")
print(f"{'Min':<6}{'Mean':>10}{'Median':>10}{'%>0':>10}{'%<-0.05':>12}")
for tag, key in [("M1", "m1"), ("M2", "m2"), ("M3", "m3"), ("M4", "m4"), ("Block", "bc")]:
    vals = [s[key] for s in stats]
    pct_pos  = sum(1 for v in vals if v > 0)     / n * 100
    pct_neg  = sum(1 for v in vals if v < -0.05) / n * 100   # Pullback-Schwelle
    print(f"{tag:<6}{mean(vals):>9.4f}%{median(vals):>9.4f}%{pct_pos:>9.1f}%{pct_neg:>11.1f}%")
print()

# ── 2) Win-Quote bei verschiedenen Einstiegs-Bedingungen ──
print("─── Bedingte Win-Quote (Block endet in Signal-Richtung) ───")
print()

scenarios = [
    ("Sofort nach M1 (Baseline)",
     lambda s: True),
    ("M2 nochmal in Signal-Richtung weiter (>=+0.02%)",
     lambda s: s["m2"] >= s["m1"] + 0.02),
    ("M2 ungefähr stehen geblieben (-0.02% bis +0.02%)",
     lambda s: s["m1"] - 0.02 <= s["m2"] <= s["m1"] + 0.02),
    ("M2 PULLBACK gegen Signal (-0.05% bis -0.02%)",
     lambda s: s["m1"] - 0.05 <= s["m2"] < s["m1"] - 0.02),
    ("M2 starker PULLBACK (mehr als -0.05%)",
     lambda s: s["m2"] < s["m1"] - 0.05),
    ("M2 PULLBACK über Block-Open hinaus (m2 < 0)",
     lambda s: s["m2"] < 0),
    ("M3 PULLBACK über Block-Open hinaus (m3 < 0)",
     lambda s: s["m3"] < 0),
    ("M2 ODER M3 PULLBACK über Open (m2<0 oder m3<0)",
     lambda s: s["m2"] < 0 or s["m3"] < 0),
    ("M2 starker Pullback UND M3 wieder positiv",
     lambda s: s["m2"] < 0 and s["m3"] > 0),
]

print(f"{'Szenario':<55}{'N':>8}{'%v.allen':>10}{'WinRate':>10}")
for name, cond in scenarios:
    matches = [s for s in stats if cond(s)]
    if not matches: continue
    wr = sum(1 for s in matches if s["win"]) / len(matches) * 100
    pct = len(matches) / n * 100
    print(f"{name:<55}{len(matches):>8,}{pct:>9.1f}%{wr:>9.2f}%")

# ── 3) Pullback-Tiefe vs Win-Quote ──
print()
print("─── Pullback-Tiefe nach M2 vs Win-Quote (M1-Signal triggert) ───")
print(f"{'M2-Range (% in Sig-Richt.)':<35}{'N':>8}{'WinRate':>10}{'Avg M1-Mag':>12}")
buckets = [
    (-99, -0.10, "stark gegen Signal (<-0.10%)"),
    (-0.10, -0.05, "moderat gegen (-0.10..-0.05)"),
    (-0.05, -0.02, "leicht gegen (-0.05..-0.02)"),
    (-0.02, +0.02, "stehen geblieben (±0.02)"),
    (+0.02, +0.05, "leicht weiter (+0.02..+0.05)"),
    (+0.05, +0.10, "moderat weiter (+0.05..+0.10)"),
    (+0.10, +99, "stark weiter (>+0.10%)"),
]
for lo, hi, label in buckets:
    # Δ = m2 - m1 (relative Bewegung in Min 2)
    matches = [s for s in stats if lo <= (s["m2"] - s["m1"]) < hi]
    if not matches: continue
    wr = sum(1 for s in matches if s["win"]) / len(matches) * 100
    avg_m1 = mean(s["m1"] for s in matches)
    print(f"{label:<35}{len(matches):>8,}{wr:>9.2f}%{avg_m1:>11.4f}%")

# ── 4) Implikation für Polymarket-Einstieg ──
print()
print("─── Was das für deinen Einstieg bedeutet ───")
print()
print("Annahme: Polymarket-Preis korreliert mit BTC-Bewegung (je weiter BTC")
print("in Signal-Richtung läuft, desto teurer das Token; bei Pullback billiger).")
print()
print("→ Wenn du in M2 wartest und BTC pullbacked (M2 unter M1):")
print("   - Polymarket-Preis sollte fallen (vielleicht von 70¢ auf 60¢)")
print("   - Risk/Reward verbessert sich signifikant")
print("   - Win-Quote KÖNNTE leiden (siehe Tabelle oben)")
print()
print("Trade-off: Bessere Odds vs niedrigere Win-Rate → Erwartungswert hängt davon ab.")
print()

# ── 5) Erwartungswert-Sim: Pullback-Strategie vs Direkt-Einstieg ──
print("─── Erwartungswert-Sim: $5 Bet ───")
print(f"{'Strategie':<60}{'N':>8}{'WinRate':>10}{'Avg fairer Preis':>18}{'EV pro Trade':>14}")
print()
# Wir nehmen vereinfacht an: fairer Preis = aktuelle BTC-Bewegung in % vom maximalen Move
# (um eine Idee von Polymarket-Preis-Bewegung zu simulieren — approx)
# Realere Annahme: Polymarket-Preis zum M_n-Zeitpunkt ≈ Signal-Konfidenz basiert auf
# kumulativer Bewegung gegenüber initialem Signal-Bias

# Direkt-Einstieg: Preis ≈ 0.70 (median Live-Beobachtung)
# Pullback-Einstieg: nehmen wir an, Preis sinkt um Δm = (m1 - m2) * 30 (heuristisch)
# Das ist nur eine grobe Schätzung — echter Polymarket-Preis variiert.

def sim(label, cond, base_price=0.70, m2_price_sensitivity=30):
    matches = [s for s in stats if cond(s)]
    if not matches:
        print(f"{label:<60}{'-':>8}{'-':>10}{'-':>18}{'-':>14}")
        return
    wr = sum(1 for s in matches if s["win"]) / len(matches)
    # Heuristischer Polymarket-Preis: höher wenn BTC weiter in Signal-Richtung lief
    avg_price = mean(
        max(0.05, min(0.95, base_price + (s["m2"] - s["m1"]) * m2_price_sensitivity / 100))
        for s in matches
    )
    # EV: P(win)*(1-price) - P(lose)*price
    ev = wr * (1 - avg_price) - (1 - wr) * avg_price
    ev_dollar = ev * 5  # $5 Bet
    print(f"{label:<60}{len(matches):>8,}{wr*100:>9.1f}%{avg_price:>17.3f}{ev_dollar:>13.3f}")

sim("Direkt M1 (alle Signale, Preis ~0.70)",
    lambda s: True, base_price=0.70, m2_price_sensitivity=0)
sim("Warten bis M2, dann immer kaufen (Preis bewegt sich)",
    lambda s: True, base_price=0.70, m2_price_sensitivity=30)
sim("Warten bis M2, NUR kaufen wenn Pullback (m2 < m1)",
    lambda s: s["m2"] < s["m1"], base_price=0.70, m2_price_sensitivity=30)
sim("Warten bis M2, kaufen wenn STARKER Pullback (m2 < 0)",
    lambda s: s["m2"] < 0, base_price=0.70, m2_price_sensitivity=30)
sim("Warten bis M3, kaufen wenn Pullback (m3 < m1*0.5)",
    lambda s: s["m3"] < s["m1"] * 0.5, base_price=0.70, m2_price_sensitivity=30)
print()
print("Hinweis: Polymarket-Preis ist heuristisch geschätzt (echte Preise nicht historisch verfügbar).")
print("Die WinRate-Spalte ist exakt (aus Binance), die Preis/EV-Spalte ist ein Modell.")
