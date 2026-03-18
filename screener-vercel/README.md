# Breakout Intelligence Terminal — Vercel Backend

## Setup in 5 Schritten (kein Terminal nötig)

### Schritt 1: Vercel Account
1. Gehe auf https://vercel.com
2. Klicke "Sign Up" → "Continue with GitHub" (oder E-Mail)
3. Bestätige deine E-Mail

### Schritt 2: Neues Projekt erstellen
1. Im Vercel Dashboard: "Add New Project"
2. Klicke "Browse" oder ziehe den Ordner `screener-vercel` rein
3. Wähle "Deploy" — keine weiteren Einstellungen nötig

### Schritt 3: Finnhub Key als Environment Variable
1. Nach dem Deploy: "Settings" → "Environment Variables"
2. Name: `FINNHUB_TOKEN`
3. Value: dein Finnhub API Key (z.B. `d6t7ed9r01...`)
4. Klicke "Save" → dann "Redeploy"

### Schritt 4: Deine API URL
Nach dem Deploy bekommst du eine URL wie:
`https://screener-vercel-xyz.vercel.app`

Deine API Endpoints sind dann:
- `GET /api/quote?symbol=NVDA` — Single Quote
- `GET /api/scan` — Vollständiger S&P500/Nasdaq Scan

### Schritt 5: Im Screener eintragen
Im Claude Artifact den Screener öffnen,
deine Vercel URL eingeben — fertig!

---

## API Reference

### GET /api/quote?symbol=TICKER
```json
{
  "symbol": "NVDA",
  "price": 118.50,
  "changePercent": -0.8,
  "week52High": 153.13,
  "week52Low": 86.00,
  "consolidationWeeks": 10
}
```

### GET /api/scan
```json
{
  "results": [...],
  "scanned": 80,
  "total": 100,
  "timestamp": 1234567890
}
```

---

## Kostenlos?
Ja. Vercel Free Plan:
- 100 GB Bandwidth/Monat
- 100 Serverless Function Invocations/Tag kostenlos
- Für deinen persönlichen Screener mehr als genug

## Finnhub Free Tier
- 60 API Calls/Minute
- Echtzeit-Quotes
- Historische Daten (für 52W High/Low)
- Kein Volume auf Free (nur Quote)
