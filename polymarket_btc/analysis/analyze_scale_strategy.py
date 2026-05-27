#!/usr/bin/env python3
"""
Simuliert die 3-Leg-Scale-Strategie:
  1. M2 (XX:X2:05): Initial-Entry mit Teilbetrag
  2. M3 (XX:X3:05): je nach M3 —
       a) Confirm → zweiter BUY (Scale-In)
       b) Bruch   → SELL der Position (Scale-Out / Exit)
       c) Neutral → halten
  3. Block-Ende: resolve

Vergleich gegen:
  - Aktuell (M2-Entry, keine M3-Anpassung)
  - M3-only (warten bis M3 und dann entry)
"""
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

CSV_PATH  = Path(__file__).parent / "footprint_BTCUSDT_1m_2022-01-01_2026-04-13.csv"
THRESHOLD = 0.05

# ── Preis-Annahmen (Polymarket-Modell) ──
# Polymarket preist M1→Confirmation zunehmend ein. Beim M3-Zeitpunkt
# ist der Preis schon näher an der "wahren" Wahrscheinlichkeit.
PRICE_M2_CONFIRM  = 0.80   # Kaufpreis bei M2 wenn wir confirm setzen
PRICE_M3_CONFIRM  = 0.87   # Kaufpreis bei M3 wenn confirm bestätigt (weiter gestiegen)
PRICE_M3_BREAK    = 0.42   # Verkaufspreis bei M3-Bruch (UP-Token ist stark gefallen)
SPREAD            = 0.02   # Bid-Ask-Spread (Sell bekommst du bid, nicht ask)
FEE_PCT           = 0.02   # Polymarket ~2% fee pro Trade

# ── Daten laden ──
blocks = defaultdict(list)
with open(CSV_PATH, newline="") as f:
    for row in csv.DictReader(f):
        try:
            dt = datetime.strptime(row["timestamp_utc"], "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        ep = int(dt.timestamp() // 60)
        blocks[ep // 5].append((ep % 5, float(row["open"]), float(row["close"])))

# Nur CONFIRM-Kandidaten betrachten (M2 hält Continuation)
confirms = []
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
    if m2_al < abs(m1) - 0.01: continue   # Kein CONFIRM
    m3_al = (m3c - bo) / bo * 100 * sign
    bc_al = (bc  - bo) / bo * 100 * sign
    confirms.append({
        "m2_al": m2_al, "m3_al": m3_al, "bc_al": bc_al, "win": bc_al > 0,
    })

n = len(confirms)
print(f"CONFIRM-Trades im Backtest: {n:,}\n")

# ── M3-Klassen ──
def m3_class(s):
    if s["m3_al"] >= s["m2_al"] - 0.01:     return "CONF"   # Confirmation hält
    if s["m3_al"] <  s["m2_al"] - 0.05:     return "BREAK"  # Bruch
    return "NEUTRAL"

m3_groups = defaultdict(list)
for s in confirms:
    m3_groups[m3_class(s)].append(s)

for k in ["CONF", "NEUTRAL", "BREAK"]:
    g = m3_groups[k]
    wr = sum(1 for s in g if s["win"]) / len(g) * 100
    print(f"  M3={k:<8} N={len(g):>7,} ({len(g)/n*100:5.1f}%)  WR={wr:.1f}%")
print()

# ── Strategie-Simulation ──
def sim_baseline(bet):
    """M2-Entry, halten bis Block-Ende."""
    # Gekauft bei PRICE_M2_CONFIRM, Shares = bet / price
    shares = bet / PRICE_M2_CONFIRM
    fees   = bet * FEE_PCT   # Kauf-Fee
    total_pnl = 0.0
    for s in confirms:
        if s["win"]: total_pnl += shares * (1 - PRICE_M2_CONFIRM)
        else:        total_pnl -= bet
        total_pnl -= fees
    return total_pnl / n   # avg per trade

def sim_scale_in(bet_1, bet_2):
    """M2: bet_1 bei 0.80. M3-Confirm: bet_2 bei 0.87. Sonst: nix Zusätzliches.
    Bei M3-Break: halten (kein Sell)."""
    total_pnl = 0.0
    for s in confirms:
        cls = m3_class(s)
        # Leg 1: gekauft bei M2
        sh1  = bet_1 / PRICE_M2_CONFIRM
        fee1 = bet_1 * FEE_PCT
        if s["win"]: pnl1 = sh1 * (1 - PRICE_M2_CONFIRM)
        else:        pnl1 = -bet_1
        pnl1 -= fee1
        # Leg 2: zusätzlicher Kauf nur bei M3-Confirm
        pnl2 = 0.0
        if cls == "CONF":
            sh2  = bet_2 / PRICE_M3_CONFIRM
            fee2 = bet_2 * FEE_PCT
            if s["win"]: pnl2 = sh2 * (1 - PRICE_M3_CONFIRM)
            else:        pnl2 = -bet_2
            pnl2 -= fee2
        total_pnl += pnl1 + pnl2
    return total_pnl / n

def sim_scale_out(bet):
    """M2: Kauf bet bei 0.80. M3-Break: Verkauf bei 0.42-spread=0.40.
    M3-Confirm/Neutral: halten."""
    total_pnl = 0.0
    for s in confirms:
        cls = m3_class(s)
        sh  = bet / PRICE_M2_CONFIRM
        fee_buy = bet * FEE_PCT
        if cls == "BREAK":
            # Verkauf bei M3-Bruch
            sell_price = PRICE_M3_BREAK - SPREAD
            proceeds = sh * sell_price
            fee_sell = proceeds * FEE_PCT
            pnl = proceeds - bet - fee_buy - fee_sell
        else:
            # halten
            if s["win"]: pnl = sh * (1 - PRICE_M2_CONFIRM)
            else:        pnl = -bet
            pnl -= fee_buy
        total_pnl += pnl
    return total_pnl / n

def sim_full(bet_1, bet_2):
    """Kombi: Scale-In bei Confirm + Scale-Out bei Break.
    bet_1 = Initial M2. bet_2 = zusätzlicher M3-Confirm-Kauf."""
    total_pnl = 0.0
    for s in confirms:
        cls = m3_class(s)
        sh1 = bet_1 / PRICE_M2_CONFIRM
        fee1 = bet_1 * FEE_PCT
        if cls == "BREAK":
            proceeds = sh1 * (PRICE_M3_BREAK - SPREAD)
            fee_sell = proceeds * FEE_PCT
            pnl = proceeds - bet_1 - fee1 - fee_sell
        elif cls == "CONF":
            sh2 = bet_2 / PRICE_M3_CONFIRM
            fee2 = bet_2 * FEE_PCT
            if s["win"]:
                pnl = sh1 * (1 - PRICE_M2_CONFIRM) + sh2 * (1 - PRICE_M3_CONFIRM)
            else:
                pnl = -bet_1 - bet_2
            pnl -= (fee1 + fee2)
        else:  # NEUTRAL: halten
            if s["win"]: pnl = sh1 * (1 - PRICE_M2_CONFIRM)
            else:        pnl = -bet_1
            pnl -= fee1
        total_pnl += pnl
    return total_pnl / n

# ── Vergleich ──
print("═══ SIMULATION (avg P&L pro CONFIRM-Trade) ═══\n")
print(f"Annahmen: M2-buy @ ${PRICE_M2_CONFIRM}, M3-confirm-buy @ ${PRICE_M3_CONFIRM}, "
      f"M3-break-sell @ ${PRICE_M3_BREAK} (minus {SPREAD} spread), fee {FEE_PCT*100}%\n")

print(f"{'Strategie':<55}{'Avg $/Trade':>15}{'Annualized*':>15}")
print("─" * 85)

baseline = sim_baseline(5.0)
scalein_25_25 = sim_scale_in(2.5, 2.5)
scalein_40_10 = sim_scale_in(4.0, 1.0)
scaleout = sim_scale_out(5.0)
full_25_25 = sim_full(2.5, 2.5)
full_40_10 = sim_full(4.0, 1.0)

# Annualized: ~17,500 CONFIRM-Trades/Jahr laut Backtest
ANNUAL_TRADES = 17500
print(f"{'A) Baseline ($5 M2-buy, halten bis Block-Ende)':<55}{baseline:>+14.4f}{baseline*ANNUAL_TRADES:>+14.0f}")
print(f"{'B) Scale-IN 2.5 + 2.5 (nur bei M3-Confirm)':<55}{scalein_25_25:>+14.4f}{scalein_25_25*ANNUAL_TRADES:>+14.0f}")
print(f"{'C) Scale-IN 4 + 1 (kleiner Top-up)':<55}{scalein_40_10:>+14.4f}{scalein_40_10*ANNUAL_TRADES:>+14.0f}")
print(f"{'D) Scale-OUT ($5 M2, Exit bei M3-Break)':<55}{scaleout:>+14.4f}{scaleout*ANNUAL_TRADES:>+14.0f}")
print(f"{'E) Full (2.5 M2, +2.5 Confirm, Exit Break)':<55}{full_25_25:>+14.4f}{full_25_25*ANNUAL_TRADES:>+14.0f}")
print(f"{'F) Full (4 M2, +1 Confirm, Exit Break)':<55}{full_40_10:>+14.4f}{full_40_10*ANNUAL_TRADES:>+14.0f}")

print()
print("* Annualized-Schätzung basiert auf ~17.500 CONFIRM-Trades/Jahr (theoretisch max)")
print("  Real ca. 5-10× weniger wegen Edge-Filter & Fill-Rate.")
print()

# ── Sensitivität: wie stark hängt Scale-Out vom Sell-Preis ab? ──
print("─── Sensitivität Scale-Out: Sell-Preis bei M3-Break ───")
print(f"{'Sell-Preis':<15}{'Avg $/Trade':>15}{'vs Baseline':>15}")
for sp in [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]:
    sp_eff = sp - SPREAD
    total = 0.0
    for s in confirms:
        cls = m3_class(s)
        sh = 5.0 / PRICE_M2_CONFIRM
        fee_buy = 5.0 * FEE_PCT
        if cls == "BREAK":
            proceeds = sh * sp_eff
            fee_sell = proceeds * FEE_PCT
            pnl = proceeds - 5.0 - fee_buy - fee_sell
        else:
            if s["win"]: pnl = sh * (1 - PRICE_M2_CONFIRM)
            else:        pnl = -5.0
            pnl -= fee_buy
        total += pnl
    avg = total / n
    diff = avg - baseline
    print(f"${sp:.2f}           {avg:>+14.4f}{diff:>+14.4f}")
