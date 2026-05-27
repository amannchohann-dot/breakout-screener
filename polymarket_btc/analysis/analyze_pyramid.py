#!/usr/bin/env python3
"""
Pyramid-Sizing: kleine Initial-Wette, dann bei M3-Confirm MASSIV nachlegen.

Die eigentliche Idee des Users:
  - Minute 2: $5 Einstieg  (Schutz gegen Fehltrade)
  - Minute 3 Confirm: auf $20 nachlegen (95%+ Win-Rate rechtfertigt größere Position)
  - Minute 3 Break/Neutral: nur $5 halten (kein Upsize)
  - Optional Exit bei Break: meist nicht profitabel (siehe vorige Simulation)
"""
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

CSV_PATH  = Path(__file__).parent / "footprint_BTCUSDT_1m_2022-01-01_2026-04-13.csv"
THRESHOLD = 0.05

# Preis-Annahmen
PRICE_M2   = 0.80   # M2-Entry
PRICE_M3   = 0.87   # M3-Confirm-Nachkauf (höher, weil Markt gesehen hat)
PRICE_BREAK_SELL = 0.40   # bei M3-Break + Spread
SPREAD = 0.02
FEE_PCT = 0.02

blocks = defaultdict(list)
with open(CSV_PATH, newline="") as f:
    for row in csv.DictReader(f):
        try:
            dt = datetime.strptime(row["timestamp_utc"], "%Y-%m-%d %H:%M")
        except ValueError: continue
        ep = int(dt.timestamp() // 60)
        blocks[ep // 5].append((ep % 5, float(row["open"]), float(row["close"])))

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
    if m2_al < abs(m1) - 0.01: continue
    m3_al = (m3c - bo) / bo * 100 * sign
    bc_al = (bc  - bo) / bo * 100 * sign
    if m3_al >= m2_al - 0.01:   cls = "CONF"
    elif m3_al <  m2_al - 0.05: cls = "BREAK"
    else:                        cls = "NEUTRAL"
    confirms.append({"win": bc_al > 0, "cls": cls})

n = len(confirms)
wr_conf  = sum(1 for s in confirms if s["cls"]=="CONF"    and s["win"]) / sum(1 for s in confirms if s["cls"]=="CONF")
wr_neut  = sum(1 for s in confirms if s["cls"]=="NEUTRAL" and s["win"]) / sum(1 for s in confirms if s["cls"]=="NEUTRAL")
wr_brk   = sum(1 for s in confirms if s["cls"]=="BREAK"   and s["win"]) / sum(1 for s in confirms if s["cls"]=="BREAK")

print(f"CONFIRM-Trades: {n:,}\n")
print(f"M3=CONF    WR={wr_conf*100:.1f}%   ({sum(1 for s in confirms if s['cls']=='CONF'):,}/n)")
print(f"M3=NEUTRAL WR={wr_neut*100:.1f}%   ({sum(1 for s in confirms if s['cls']=='NEUTRAL'):,}/n)")
print(f"M3=BREAK   WR={wr_brk*100 :.1f}%   ({sum(1 for s in confirms if s['cls']=='BREAK'):,}/n)\n")

def pnl_leg(bet, buy_price, win):
    """P&L eines einzelnen BUY-Legs (Kauf und halten bis Ende)."""
    shares = bet / buy_price
    fee = bet * FEE_PCT
    if win: return shares * (1 - buy_price) - fee
    else:   return -bet - fee

def pnl_sell(bet, buy_price, sell_price):
    """P&L wenn gekauft bei buy_price, verkauft bei sell_price (mit Spread+Fees)."""
    shares   = bet / buy_price
    fee_buy  = bet * FEE_PCT
    proceeds = shares * (sell_price - SPREAD)
    fee_sell = proceeds * FEE_PCT
    return proceeds - bet - fee_buy - fee_sell

def simulate(initial_bet, addon_bet, exit_on_break=False):
    """Initial bei M2, nach M3 entscheiden:
       - CONF   → nachkaufen addon_bet bei PRICE_M3
       - NEUT   → halten
       - BREAK  → halten oder exit (Parameter)"""
    total_pnl = 0.0
    avg_capital = 0.0
    for s in confirms:
        leg1 = pnl_leg(initial_bet, PRICE_M2, s["win"])
        leg2 = 0.0
        cap  = initial_bet
        if s["cls"] == "CONF":
            leg2 = pnl_leg(addon_bet, PRICE_M3, s["win"])
            cap += addon_bet
        elif s["cls"] == "BREAK" and exit_on_break:
            leg1 = pnl_sell(initial_bet, PRICE_M2, PRICE_BREAK_SELL)
        total_pnl   += leg1 + leg2
        avg_capital += cap
    return total_pnl / n, avg_capital / n

print("═══ VERGLEICH: PYRAMID-SIZING vs. FLAT-SIZING ═══\n")
print(f"Annahmen: M2-Preis ${PRICE_M2}, M3-Confirm-Preis ${PRICE_M3}, "
      f"Sell@Break ${PRICE_BREAK_SELL}, Fees {FEE_PCT*100}%\n")

scenarios = [
    ("A) Flat: $5 einmal (Status quo)",           5,  0,  False),
    ("B) Flat: $20 einmal (aggressive baseline)", 20, 0,  False),
    ("C) PYRAMID: $5 M2 + $15 Nachkauf bei CONF", 5,  15, False),
    ("D) PYRAMID: $5 M2 + $15 CONF + Exit BREAK", 5,  15, True),
    ("E) PYRAMID: $5 M2 + $10 CONF",              5,  10, False),
    ("F) PYRAMID: $10 M2 + $10 CONF",             10, 10, False),
    ("G) PYRAMID: $5 M2 + $5 CONF",               5,  5,  False),
]

print(f"{'Strategie':<55}{'Avg $/Trade':>13}{'Ø Kapital':>11}{'ROI/Trade':>11}{'Jahr*':>10}")
print("─" * 100)
for name, init, addon, exit_b in scenarios:
    pnl, cap = simulate(init, addon, exit_b)
    roi = pnl / cap * 100 if cap > 0 else 0
    annual = pnl * 17500
    print(f"{name:<55}{pnl:>+12.4f}{cap:>11.2f}{roi:>+10.2f}%{annual:>+9.0f}")

print()
print("* Jährlich basierend auf ~17.500 CONFIRM-Trades/Jahr (theoretisch max)")
print("  Real ca. 5-10× weniger wegen Edge-Filter & Fill-Rate.")
print()

# Sensitivität bei echten Live-Fills (~10/Tag = ~3500/Jahr)
print("─── Realistisch (3.500 Fills/Jahr) ───\n")
print(f"{'Strategie':<55}{'$/Tag':>12}{'$/Monat':>12}{'$/Jahr':>12}")
for name, init, addon, exit_b in scenarios:
    pnl, _ = simulate(init, addon, exit_b)
    annual = pnl * 3500
    daily  = annual / 365
    monthly = annual / 12
    print(f"{name:<55}${daily:>+10.2f}${monthly:>+10.2f}${annual:>+10.0f}")

# Kelly-optimal Sizing
print()
print("─── Kelly-ähnliche Größen: was wenn Preise anders sind? ───\n")
print("Alle mit Pyramid $5 M2 + $15 CONF (keine Exit):\n")
print(f"{'M2-Preis':<12}{'M3-Preis':<12}{'Avg $/Trade':>14}{'Ø Kapital':>12}{'ROI%':>10}")
for p2 in [0.75, 0.78, 0.80, 0.82, 0.85]:
    for p3 in [p2 + 0.05, p2 + 0.07, p2 + 0.10]:
        # simuliere mit diesen Preisen
        total = 0.0; avg_cap = 0.0
        for s in confirms:
            sh1 = 5 / p2
            pnl1 = sh1 * (1 - p2) - 5 * FEE_PCT if s["win"] else -5 - 5 * FEE_PCT
            if s["cls"] == "CONF":
                sh2 = 15 / p3
                pnl2 = sh2 * (1 - p3) - 15 * FEE_PCT if s["win"] else -15 - 15 * FEE_PCT
                cap = 20
            else:
                pnl2 = 0
                cap = 5
            total += pnl1 + pnl2
            avg_cap += cap
        pnl = total / n
        c   = avg_cap / n
        print(f"${p2:<11.2f}${p3:<11.2f}${pnl:>+13.4f}${c:>11.2f}{pnl/c*100:>+9.2f}%")
