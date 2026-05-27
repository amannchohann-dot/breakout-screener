# Polymarket BTC 5-Min Prediction Bot

## Strategie

Late-Entry nach Minute 1: Wenn die erste Minute eines 5-Min-Blocks stark genug in eine Richtung geht (|M1| ≥ 0.05%), wette auf diese Richtung.

**Backtest-Ergebnisse (Jan 2024 – Apr 2026):**
- 74.849 Trades, 74.8% Accuracy
- 0 Verlustmonate in 28 Monaten
- ~$63/Tag bei $5 Bet (konservatives Odds-Modell)

## Setup

```bash
# 1. Dependencies installieren
pip install py-clob-client python-dotenv requests

# 2. .env erstellen
cp .env.template .env
# → Private Key und Wallet-Adresse eintragen

# 3. Paper-Trading starten (empfohlen!)
python bot.py

# 4. Nach 50+ erfolgreichen Paper Trades: Live schalten
# In .env: DRY_RUN=false
```

## Konfiguration (.env)

| Variable | Default | Beschreibung |
|----------|---------|-------------|
| `M1_THRESHOLD` | 0.05 | Min. M1-Move in % (0.03=aggressiv, 0.10=konservativ) |
| `BET_SIZE` | 5 | USDC pro Trade |
| `DAILY_LOSS_LIMIT` | 50 | Max Tagesverlust bevor Bot pausiert |
| `MAX_LOSS_STREAK` | 5 | Max Verlust-Serie bevor Pause |
| `DRY_RUN` | true | Paper-Modus (keine echten Orders) |

## Dateien

- `bot.py` — Hauptskript
- `.env.template` — Konfigurationsvorlage
- `trades_log.json` — Wird automatisch erstellt (Trade-History)
- `logs/` — Tägliche Log-Dateien
