# Trendline-Breakout-Strategie — Komplette Übergabe

Dieses Dokument ist selbsterklärend: Es enthält alle Regeln, Testkonventionen
und bisherigen Ergebnisse, sodass die Strategie in jeder Umgebung (anderer
Chat, eigener Code, TradingView) exakt reproduziert und weitergetestet werden
kann. Referenz-Implementierung: GitHub-Repo `amannchohann-dot/breakout-screener`,
Branch `claude/uberprufung-erforderlich-cofjt1`, Ordner `backtest/`.

---

## 1. Die Strategie (finale, validierte Fassung)

**Basis:** TradingView-Indikator „Trendlines with Breaks [LuxAlgo]“,
Standard-Einstellungen (Swing Detection Lookback = 14, Slope = 1.0,
Methode „Atr“), **Backpainting AUS** (wichtig — sonst Lookahead!).

**Signal-Logik (falls selbst implementiert):**
1. Pivot-High = Hoch, das höher ist als die 14 Kerzen davor UND danach
   (dadurch erst 14 Kerzen später bestätigt — kein Blick in die Zukunft).
   Pivot-Low analog mit Tiefs.
2. Steigung s = ATR(14, Wilder-RMA) / 14.
3. Ab einem bestätigten Pivot-High fällt eine Widerstandslinie: Startwert =
   Pivot-Hoch, pro Kerze −s. Ab Pivot-Low steigt eine Unterstützungslinie
   analog (+s). Es gilt jeweils die zuletzt bestätigte Linie.
4. **Long-Signal:** erster Schlusskurs ÜBER der fallenden Widerstandslinie.
   **Short-Signal:** erster Schlusskurs UNTER der steigenden
   Unterstützungslinie. (Nur der erste Bruch zählt, bis ein neues Pivot die
   Linie erneuert — entspricht upos/dnos 0→1 im LuxAlgo-Script.)

**Trade-Management (die validierte Konfiguration):**
- Entry: Open der Kerze NACH der Signalkerze.
- **Stop-Loss: Tief der Ausbruchskerze (Long) bzw. Hoch (Short).**
- **Take-Profit: 3× Stop-Distanz (RR 3:1).**
- Eine Position gleichzeitig; kein Nachziehen, kein Breakeven (beides getestet,
  bringt nichts Konsistentes).
- Timeframes mit Edge: **2h, 4h, 1d**. Auf 15m–1h funktioniert es NICHT.

**Position Sizing (5.000er-Konto):** 1–2 % Risiko pro Trade
(Positionsgröße = Risikobetrag / Stop-Distanz). Effektiver Hebel ergibt sich
automatisch (Median ~1,6–3x, 1:20-Konto reicht). 5 % Risiko führt mit ~34 %
Wahrscheinlichkeit zur zwischenzeitlichen Kontohalbierung — nicht machbar.

## 2. Test-Konventionen (für faire Reproduktion zwingend)

- Kein Lookahead: Pivots erst nach `length` Kerzen verwenden.
- Konservative Ausführung: Treffen SL und TP in derselben Kerze, zählt der
  Trade als VERLUST.
- Kosten: ~0,6 Basispunkte des Kurses pro Trade (bei Gold ~4000 USD:
  0,25 USD) — deckt Spread/Slippage.
- Validierung: Daten in zwei Hälften teilen (In-Sample/Out-of-Sample);
  nur was in BEIDEN Hälften positiv ist, zählt. Ergebnisse in R
  (Vielfache des Risikos), nicht in %.

## 3. Bisherige Ergebnisse (IBKR-Daten, Stand 13.08.2026)

| Markt | TF | Periode | Trades | Winrate | Netto | EV (IS/OOS) |
|---|---|---|---|---|---|---|
| Gold (XAUUSD) | 2h | 14 Mon. | 88 | 38,6 % | +46,6 R | +0,48/+0,52 |
| Gold | 4h | 2,4 J. | 108 | 34,3 % | +37,8 R | +0,36/+0,39 |
| Gold | 1d | 13,6 J. | 110 | 33,6 % | +35,9 R | +0,23/+0,50 |
| Silber (XAGUSD) | 4h | 2,4 J. | 94 | 33,0 % | +29,1 R | +0,12/+0,60 |
| Silber | 1d | 13,6 J. | 88 | 40,9 % | +55,7 R | +0,94/+0,46 |

Kontext: Gold-1d enthält Bärenmarkt 2013–2015, Seitwärtsphasen 2016–2018 und
2021, Spike/Crash Anfang 2026. 10 von 14 Jahren positiv (schlechtestes Jahr
−5,3 R). Auf Tagesbasis Shorts ≈ Longs (+18,8 vs. +17,1 R) — kein reiner
Bullenmarkt-Effekt. Silber lief mit der UNVERÄNDERTEN Gold-Konfiguration
(echter Out-of-Instrument-Test). t-Statistiken 1,8–2,6 pro Markt/TF.

Verworfene Varianten (getestet, kein konsistenter Edge): Liquidity-Grab-Setup
mit Pivot-1/1-Levels (Twitter-Strategie, Ausgangspunkt der Untersuchung),
ATR-Stop auf 1d, Breakeven-Verschiebung, Exit per Gegensignal, alles auf
15m/30m/1h.

## 4. Offene Punkte (nächste Schritte für den anderen Chat)

1. **BTC testen** — gleiche Regeln, gleiche Konventionen (4h + 1d, IS/OOS).
   Datenquelle frei wählbar (Binance-API: lückenlos ab 2017; oder vorhandene
   eigene Dateien, z. B. Footprint-Exporte — OHLC pro Bar genügt).
2. **SPY testen** (Signal auf dem Basiswert; Optionen erst danach als reines
   Ausführungsvehikel betrachten — für echten Options-Backtest bräuchte man
   historische Optionspreise inkl. IV/Theta).
3. Andere Trendmärkte (Indizes, Öl, weitere Metalle) als zusätzliche
   Out-of-Instrument-Validierung.
4. Vor Live-Einsatz: einige Wochen Demo-Betrieb parallel zum
   TradingView-Indikator (Alerts „Upward/Downward Breakout“), um die
   Implementierung zu verifizieren.

## 5. Ehrliche Einordnung

Konsistent über 2 Instrumente × 3 Timeframes × alle Datenhälften × 14 Jahre —
das robusteste Ergebnis der gesamten Untersuchung. Aber: t ≈ 2 pro Zelle ist
Evidenz, kein Beweis; ~30 Varianten wurden insgesamt getestet
(Selektionsrisiko); Edelmetalle waren 2024–2026 stark trendend. Kein
Live-Einsatz ohne Demo-Phase. Keine Anlageberatung.
