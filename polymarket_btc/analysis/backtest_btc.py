#!/usr/bin/env python3
"""
Unabhängiger Backtest der Late-Entry-Strategie aus README:
  - Pro 5-Min-Block: M1 = (close_min1 - open_min0) / open_min0 * 100
  - Wenn |M1| >= THRESHOLD% → wette auf M1-Richtung
  - Block-Outcome: close_min4 vs open_min0 (UP wenn close > open)
  - Trade ist "correct" wenn Signal == Outcome

Berechnet: Anzahl Trades, Accuracy, Monats-Statistik, Magnitude-Buckets.
Nutzt nur die 1m-OHLC aus footprint CSV — keine Polymarket-Preise nötig
(Pure Signal-Güte, P&L hängt zusätzlich vom Marktpreis ab).
"""
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

CSV_PATH  = Path(__file__).parent / "footprint_BTCUSDT_1m_2022-01-01_2026-04-13.csv"
THRESHOLD = 0.05   # % — Bot-Default (M1_THRESHOLD in .env)

# ── 1m-Daten lesen, nach 5-min-Block gruppieren ──
# Block-Key = epoch_min // 5 (UTC, aligned)
print(f"Lese {CSV_PATH.name} …")
blocks = defaultdict(list)   # block_key -> list of (minute_in_block, open, close)
n_rows = 0
ts_min = ts_max = None

with open(CSV_PATH, newline="") as f:
    r = csv.DictReader(f)
    for row in r:
        n_rows += 1
        # timestamp_utc Format: "2021-12-31 23:01"
        try:
            dt = datetime.strptime(row["timestamp_utc"], "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        ep_min   = int(dt.timestamp() // 60)
        block_k  = ep_min // 5
        min_in_b = ep_min %  5
        blocks[block_k].append((min_in_b, float(row["open"]), float(row["close"])))
        if ts_min is None or dt < ts_min: ts_min = dt
        if ts_max is None or dt > ts_max: ts_max = dt

print(f"  {n_rows:,} Rows, {len(blocks):,} Blocks, Zeitraum {ts_min} → {ts_max}")

# ── Backtest: nur Blöcke mit 5/5 Minuten verwenden ──
trades        = 0
wins          = 0
ties          = 0       # Block-Close exakt = Block-Open (selten)
no_signal     = 0
incomplete    = 0
by_month      = defaultdict(lambda: {"trades": 0, "wins": 0})
by_magnitude  = defaultdict(lambda: {"trades": 0, "wins": 0})

# Bot's Konfidenz-Modell (aus bot.py _evaluate_signal)
def confidence(m1_abs):
    if   m1_abs >= 0.20: return 0.85
    elif m1_abs >= 0.15: return 0.83
    elif m1_abs >= 0.10: return 0.80
    elif m1_abs >= 0.08: return 0.78
    elif m1_abs >= 0.05: return 0.75
    elif m1_abs >= 0.03: return 0.71
    else:                return 0.67

def mag_bucket(m1_abs):
    if   m1_abs >= 0.20: return ">=0.20"
    elif m1_abs >= 0.15: return "0.15-0.20"
    elif m1_abs >= 0.10: return "0.10-0.15"
    elif m1_abs >= 0.08: return "0.08-0.10"
    elif m1_abs >= 0.05: return "0.05-0.08"
    return "<0.05"

for block_k, mins in blocks.items():
    if len(mins) != 5:
        incomplete += 1
        continue
    mins.sort()                                  # nach minute_in_block
    if [m for m, _, _ in mins] != [0, 1, 2, 3, 4]:
        incomplete += 1
        continue

    block_open  = mins[0][1]
    m1_close    = mins[0][2]
    block_close = mins[4][2]

    m1_move = (m1_close - block_open) / block_open * 100
    m1_abs  = abs(m1_move)
    if m1_abs < THRESHOLD:
        no_signal += 1
        continue

    signal_dir = "UP" if m1_move > 0 else "DOWN"
    if   block_close > block_open: actual = "UP"
    elif block_close < block_open: actual = "DOWN"
    else:
        ties += 1
        continue

    trades += 1
    correct = (signal_dir == actual)
    if correct: wins += 1

    # Monats-Statistik (aus block_k berechenbar)
    block_dt = datetime.utcfromtimestamp(block_k * 300)
    mkey = block_dt.strftime("%Y-%m")
    by_month[mkey]["trades"] += 1
    if correct: by_month[mkey]["wins"] += 1

    bucket = mag_bucket(m1_abs)
    by_magnitude[bucket]["trades"] += 1
    if correct: by_magnitude[bucket]["wins"] += 1

# ── Output ──
print()
print("═══ BACKTEST ERGEBNIS ═══")
print(f"Threshold:           |M1| >= {THRESHOLD}%")
print(f"Blöcke total:        {len(blocks):,}")
print(f"  davon unvollst.:   {incomplete:,}")
print(f"  davon kein Signal: {no_signal:,}")
print(f"  davon Tie (0%):    {ties:,}")
print(f"Trades (Signal):     {trades:,}")
print(f"Wins:                {wins:,}")
print(f"Accuracy:            {wins/trades*100:.2f}%   (Backtest-Behauptung: 74.8%)")
print()

print("─── Accuracy nach M1-Magnitude ───")
print(f"{'Bucket':<12}{'Trades':>10}{'Wins':>10}{'Acc':>10}{'Bot-Konf':>12}")
order = [">=0.20", "0.15-0.20", "0.10-0.15", "0.08-0.10", "0.05-0.08"]
conf_for_bucket = {">=0.20": 0.85, "0.15-0.20": 0.83, "0.10-0.15": 0.80,
                    "0.08-0.10": 0.78, "0.05-0.08": 0.75}
for bk in order:
    s = by_magnitude[bk]
    if s["trades"] == 0: continue
    acc = s["wins"]/s["trades"]*100
    print(f"{bk:<12}{s['trades']:>10,}{s['wins']:>10,}{acc:>9.2f}%{conf_for_bucket[bk]*100:>10.0f}%")
print()

print("─── Monats-Übersicht (Top 5 best/worst) ───")
months = sorted(by_month.items())
print(f"Anzahl Monate: {len(months)}")
month_data = [(m, d["wins"], d["trades"], d["wins"]/d["trades"]*100 if d["trades"] else 0)
              for m, d in months if d["trades"] >= 50]
profitable = sum(1 for _, w, t, a in month_data if a > 50)   # > 50 % = profitable wenn 1:1 Odds
print(f"Monate mit >50% Acc: {profitable}/{len(month_data)}   "
      f"(Backtest-Behauptung: 28/28 profitabel)")
print()
print("Top 5 beste Monate:")
for m, w, t, a in sorted(month_data, key=lambda x: -x[3])[:5]:
    print(f"  {m}: {a:5.2f}% ({w:,}/{t:,})")
print("Top 5 schlechteste Monate:")
for m, w, t, a in sorted(month_data, key=lambda x: x[3])[:5]:
    print(f"  {m}: {a:5.2f}% ({w:,}/{t:,})")

# ── Threshold-Sweep ──
print()
print("─── Accuracy bei verschiedenen Thresholds ───")
for thr in [0.03, 0.05, 0.08, 0.10, 0.15, 0.20]:
    n_t, n_w = 0, 0
    for block_k, mins in blocks.items():
        if len(mins) != 5: continue
        mins_s = sorted(mins)
        if [m for m, _, _ in mins_s] != [0, 1, 2, 3, 4]: continue
        bo, m1c = mins_s[0][1], mins_s[0][2]
        bc      = mins_s[4][2]
        mv = (m1c - bo) / bo * 100
        if abs(mv) < thr: continue
        if bc == bo: continue
        sig = "UP" if mv > 0 else "DOWN"
        act = "UP" if bc > bo else "DOWN"
        n_t += 1
        if sig == act: n_w += 1
    if n_t:
        print(f"  thr={thr:>5.2f}%  →  {n_t:,} Trades, Acc {n_w/n_t*100:5.2f}%")
