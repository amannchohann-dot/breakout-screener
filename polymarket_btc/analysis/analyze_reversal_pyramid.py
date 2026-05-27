#!/usr/bin/env python3
"""
REVERSAL-Pyramide: $5 initial bei M2-Bruch, $15 Nachkauf bei M3-Confirmation.
Analog zur CONFIRM-Pyramide, aber für den Invers-Pfad.
"""
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

CSV_PATH  = Path(__file__).parent / "footprint_BTCUSDT_1m_2022-01-01_2026-04-13.csv"
THRESHOLD = 0.05

# ── Preis-Annahmen für REVERSAL ──
# REVERSAL tokens sind BILLIGER als CONFIRM, weil Markt erst nach M2-Bruch revidiert
PRICE_M2_REV  = 0.55   # Invers-Token nach M2-Bruch (Bot kauft z.B. DOWN wenn M1 war UP)
PRICE_M3_REV  = 0.60   # Nach M3-Bestätigung leicht höher
FEE_PCT = 0.02

blocks = defaultdict(list)
with open(CSV_PATH, newline="") as f:
    for row in csv.DictReader(f):
        try:
            dt = datetime.strptime(row["timestamp_utc"], "%Y-%m-%d %H:%M")
        except ValueError: continue
        ep = int(dt.timestamp() // 60)
        blocks[ep // 5].append((ep % 5, float(row["open"]), float(row["close"])))

# REVERSAL-Kandidaten: M2 < -0.05 in Signal-Richtung
reversals = []
for bk, mins in blocks.items():
    if len(mins) != 5: continue
    mins.sort()
    if [m for m, _, _ in mins] != [0, 1, 2, 3, 4]: continue
    bo = mins[0][1]
    m1c, m2c, m3c, bc = mins[0][2], mins[1][2], mins[2][2], mins[4][2]
    m1 = (m1c - bo) / bo * 100
    if abs(m1) < THRESHOLD: continue
    if bc == bo: continue
    sign = 1 if m1 > 0 else -1
    m2_al = (m2c - bo) / bo * 100 * sign
    if m2_al >= -0.05: continue   # Kein REVERSAL
    m3_al = (m3c - bo) / bo * 100 * sign
    bc_al = (bc  - bo) / bo * 100 * sign

    # Für REVERSAL: Invers-Win = Block endet gegen M1-Richtung
    inv_win = bc_al < 0

    # M3-Klassifikation für REVERSAL:
    # CONF = M3 fällt weiter (bestätigt Reversal)
    # BREAK = M3 bounct stark zurück (Reversal-Signal kaputt)
    # NEUTRAL = dazwischen
    if m3_al <= m2_al - 0.02:
        cls = "CONF"    # Reversal bestätigt
    elif m3_al > m2_al + 0.05:
        cls = "BREAK"   # bounct zurück, schlecht für Invers-Wette
    else:
        cls = "NEUTRAL"

    reversals.append({"inv_win": inv_win, "cls": cls, "m2_al": m2_al, "m3_al": m3_al})

n = len(reversals)
g = defaultdict(list)
for s in reversals: g[s["cls"]].append(s)

print(f"REVERSAL-Kandidaten: {n:,}\n")
for cls in ["CONF", "NEUTRAL", "BREAK"]:
    wr = sum(1 for s in g[cls] if s["inv_win"]) / len(g[cls]) * 100
    print(f"  M3={cls:<8} N={len(g[cls]):>6,} ({len(g[cls])/n*100:5.1f}%)  Inv-WR={wr:.1f}%")
print()

def pnl_leg(bet, buy_price, win):
    shares = bet / buy_price
    fee = bet * FEE_PCT
    if win: return shares * 1.0 * 0.98 - bet   # 2% Redemption-Fee wie im Bot
    else:   return -bet

def simulate(initial, addon):
    total_pnl = 0.0
    total_cap = 0.0
    for s in reversals:
        leg1 = pnl_leg(initial, PRICE_M2_REV, s["inv_win"])
        leg2 = 0.0
        cap  = initial
        if s["cls"] == "CONF":
            leg2 = pnl_leg(addon, PRICE_M3_REV, s["inv_win"])
            cap += addon
        total_pnl += leg1 + leg2
        total_cap += cap
    return total_pnl / n, total_cap / n

print("═══ REVERSAL-PYRAMID vs FLAT ═══\n")
print(f"Preis-Annahmen: M2-Invers ${PRICE_M2_REV}, M3-Invers ${PRICE_M3_REV}\n")
scenarios = [
    ("A) Flat: $5 einmal (Status quo)",              5,  0),
    ("B) Flat: $20 (aggressiv baseline)",            20, 0),
    ("C) PYRAMID $5 + $15 (analog CONFIRM-Var C)",   5,  15),
    ("D) PYRAMID $5 + $10",                          5,  10),
    ("E) PYRAMID $10 + $10",                         10, 10),
    ("F) PYRAMID $5 + $20 (extra aggressiv)",        5,  20),
]
print(f"{'Strategie':<50}{'$/Trade':>12}{'Ø Kapital':>11}{'ROI':>10}")
print("─" * 85)
for name, init, addon in scenarios:
    pnl, cap = simulate(init, addon)
    roi = pnl / cap * 100 if cap else 0
    print(f"{name:<50}{pnl:>+11.4f}{cap:>11.2f}{roi:>+9.2f}%")

# Annahme: ~1500 REVERSAL-Trades/Jahr max (weniger als CONFIRM, selteneres Signal)
# Realistisch: ~200-400 Fills/Jahr
print()
print("─── Realistisch: 300 Reversal-Fills/Jahr ───\n")
print(f"{'Strategie':<50}{'$/Jahr':>12}{'$/Monat':>12}")
for name, init, addon in scenarios:
    pnl, _ = simulate(init, addon)
    annual = pnl * 300
    print(f"{name:<50}${annual:>+10.0f}${annual/12:>+10.2f}")

# ── Sensitivität auf den Invers-Preis ──
print()
print("─── Sensitivität: wie hängt Pyramid C vom Invers-Preis ab ───\n")
print(f"{'M2-Preis':<12}{'M3-Preis':<12}{'$/Trade':>12}{'ROI':>10}")
for p_m2 in [0.45, 0.50, 0.55, 0.60, 0.65]:
    for p_m3 in [p_m2 + 0.05, p_m2 + 0.10]:
        total_pnl = 0.0
        for s in reversals:
            leg1 = (5 / p_m2) * 0.98 - 5 if s["inv_win"] else -5
            leg2 = 0
            if s["cls"] == "CONF":
                leg2 = (15 / p_m3) * 0.98 - 15 if s["inv_win"] else -15
            total_pnl += leg1 + leg2
        avg = total_pnl / n
        cap = 5 + (15 * len(g["CONF"]) / n)
        print(f"${p_m2:<11.2f}${p_m3:<11.2f}{avg:>+11.4f}{avg/cap*100:>+9.2f}%")

# ── Kombination beider Pyramiden (Gesamt-Bot-Schätzung) ──
print()
print("─── Gesamt-Bot mit BEIDEN Pyramiden (CONFIRM + REVERSAL) ───\n")

# Fixe Schätzungen (aus vorher Analyse)
# CONFIRM-Pyramid $5+$15, Preise 0.80/0.87 → +$0.93/Trade, ~3500 fills/jahr = +$3243/jahr
# REVERSAL-Pyramid $5+$15, Preise 0.55/0.60 → pnl aus sim
pnl_rev, _ = simulate(5, 15)
rev_fills = 300   # geschätzt

print(f"CONFIRM-Pyramide (~3500 Fills/Jahr):   +$3.243/Jahr  (Variante C oben)")
print(f"REVERSAL-Pyramide ({rev_fills} Fills/Jahr):     +${pnl_rev*rev_fills:.0f}/Jahr")
print(f"                                      ─────────────")
total = 3243 + pnl_rev * rev_fills
print(f"Gesamt kombiniert:                    +${total:.0f}/Jahr")
print(f"                                     ~${total/12:.0f}/Monat")
