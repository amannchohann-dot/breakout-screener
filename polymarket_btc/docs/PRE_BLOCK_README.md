# Pre-Block Bot — Mean-Reversion auf Polymarket BTC 5min

Komplementär zum existierenden M1-Bot. Tradet 5 Sek **nach Block-Start**
basierend auf den abgeschlossenen 5m-Candles.

## Strategie

Wenn der gerade abgeschlossene 5m-Candle in einer Streak (3-5+ gleichfarbige Candles)
oder einem extrem großen XL-Body endet, ist die nächste 5min-Bewegung
statistisch öfter **gegen die Streak-Richtung** (Mean Reversion).

OOS-Backtest 2025-04 → 2026-04: 33.945 Trades, +$647 bei $1-Bets @ 52¢ Ask.

## Setup

```bash
cd "/Users/Aman/Downloads/📈 Trading/polymarket btc/"

# Paper-Mode (Default): keine echten Orders
python3 pre_block_bot.py

# Live: erst nach 50+ erfolgreichen Paper-Trades!
PRE_DRY_RUN=false python3 pre_block_bot.py
```

## ENV-Variablen (überschreiben Defaults)

| Variable | Default | Beschreibung |
|---|---|---|
| `PRE_DRY_RUN` | `true` | Paper-Mode (kein realer Order) |
| `PRE_BET_SIZE` | `5` | USDC pro Trade |
| `PRE_MIN_EDGE_PP` | `2` | Min Edge in Prozentpunkten (höher = weniger, qualitativ bessere Trades) |
| `PRE_MAX_ASK` | `0.65` | Nicht über 65¢ kaufen (avoid late entries) |
| `PRE_MAX_SLIPPAGE` | `0.02` | Max 2¢ Slippage über Best-Ask |
| `PRE_DAILY_LOSS_LIMIT` | `30` | Pause wenn Tagesverlust ≥ $30 |
| `PRE_MAX_LOSS_STREAK` | `8` | Pause wenn 8 Trades in Folge verloren |

`POLYMARKET_PRIVATE_KEY`, `POLYMARKET_FUNDER` etc. werden aus der bestehenden `.env` übernommen.

## Aktive Setups (alle OOS-validiert)

19 Setups insgesamt, vom häufigsten zum seltensten:

**Häufig (mehrere/Tag):**
- `S3+R_general_UP` — 3+ rote Candles → UP, P_Up=54.2%
- `S3+G_general_DOWN` — 3+ grüne Candles → DOWN, P_Up=46.3%
- `XL_R_UP` / `XL_G_DOWN` — Einzelner XL-Body → revert
- `S2+R_XL_UP` / `S2+G_XL_DOWN` — 2+ Streak + XL-Body → revert

**Stärker:**
- `S3+R_XL_UP` / `S3+G_XL_DOWN` — 3+ Streak + XL-Body, P_Up=55.8%/44.3%
- `S4+R_general_UP` / `S4+G_general_DOWN` — 4+ Streak, P_Up=54.8%/45.1%
- `S5+R/G_general` — 5+ Streak, P_Up=54.9%/45.3%

**Stundenspezifisch (höchster Edge):**
- `S5+R_Europe_UP` — 5+ rot in 07-12 UTC → UP, **P_Up=57.3%** (Top-Setup)
- `S5+G_LateNight_DOWN` — 5+ grün in 22-23 UTC → DOWN, **P_Up=39.6%**
- `S4+G_Europe_DOWN`, `S4+G_LateNight_DOWN`, `S4+R_Europe_UP`, `S4+G_XL_DOWN`

Mehrere können gleichzeitig feuern → nur traden wenn alle dieselbe Richtung sagen (Konsens).

## Wie der Bot arbeitet

```
Block T-Start (z.B. 14:15:00 UTC)
   ↓
  +5s: Bot wacht auf
   ↓
  Hol letzte 5m-Candles von Binance
   ↓
  Berechne: Streak-Länge, Body-Größe, Stunde
   ↓
  Match alle Setups
   ↓
  Konflikt? → Skip
  Konsens? → P_Up bestimmen
   ↓
  Hol Polymarket-Markt + Best Ask
   ↓
  Edge = P_Win - Ask
   ↓
  Edge ≥ 2pp? → Order
  Edge < 2pp? → Skip
```

## Erwartung

- **~30-70 Trades/Tag** bei 2pp-Edge-Threshold
- **Hitrate 53-57%** (Backtest)
- **+$1.50-$3/Tag bei $5-Bets** im Schnitt (linear skalierbar)
- **Loss-Streaks von 5-8 sind normal** bei 53% Hitrate — nicht panicen

## Wichtige Caveats

1. **Polymarket-Resolution**: Mein Backtest = Binance BTCUSDT. Polymarket nutzt eigenen Index. Diskrepanzen bei sehr engen Blocks möglich (~1-2% der Trades).
2. **Hitrate dauert**: Bei 53% Hitrate brauchst du **mindestens 200-300 Trades** für statistische Sicherheit. In den ersten 50 Trades kannst du easy 30 Verluste haben.
3. **Konflikt mit M1-Bot**: Wenn beide Bots gleichzeitig laufen, könnten sie auf den gleichen Block in entgegengesetzte Richtungen wetten. Trennen oder einen pausieren.
4. **Edge-Decay**: Wenn der Markt deinen Edge erkennt, kann er verschwinden. Tracke regelmäßig Live vs. Backtest-Hitrate.

## Monitoring

Trades werden in `pre_block_trades.json` gespeichert. Stats per:

```bash
python3 -c "
from pre_block_bot import PreBlockLog
p = PreBlockLog()
print(p.stats())
"
```

## Troubleshooting

- **`Anderer Bot läuft schon`**: Der M1-Bot benutzt dieselbe `bot.pid`-Lockdatei.
  Stoppe einen oder benenne die Lock-Datei um (siehe `_acquire_lock` in bot.py).
- **`Kein Markt gefunden`**: Polymarket hat den Block-Slug noch nicht aktiviert.
  Normal in den ersten 1-2 Sekunden nach Block-Start. Bot skippt automatisch.
- **`Order Fehler`**: Check `.env`-Credentials und USDC-Balance auf Polymarket.

## Was passiert beim ersten Lauf

```
═══ Pre-Block Mean-Reversion Bot ═══
Modus:        🧪 DRY RUN
Bet:          $5
Min Edge:     2pp
Max Ask:      $0.65
Setups:       19 aktive Pre-Block-Setups
Daily limit:  $30/Tag
Warte 287s bis nächster Trigger 18:00:05
Block 18:00 | letzter Candle ROT streak=2 body=-0.087% normal hour=17
Keine Pre-Block-Setups aktiv für Block 18:00
Warte 295s bis nächster Trigger 18:05:05
Block 18:05 | letzter Candle ROT streak=3 body=-0.156% XL hour=18
🎯 3 Setups aktiv: ['S3+R_general_UP', 'S2+R_XL_UP', 'S3+R_XL_UP']
   → Side: UP | P_Up=0.558 | erwartet: GRÜN
   📝 PAPER: simulierter Ask 0.52
   Ask: 52¢ | Win-Prob: 56% | Edge: +3.8pp
   ✅ TRADE UP $5.00 @ 52¢ | erwarteter Profit $+0.31
   📝 PAPER-Trade gespeichert (kein realer Order)
```
