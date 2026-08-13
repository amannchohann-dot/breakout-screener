# Test: Trendline-Breakout („Trendlines with Breaks“ [LuxAlgo])

**Geprüft am:** 11.08.2026 · Daten: XAUUSD (London Gold, IBKR), 15m–4h

## Umsetzung

Der Pine-Script-Indikator wurde originalgetreu nach Python portiert
(`trendline_breakout.py`):

- Pivot-High/Low mit Lookback 14 (bestätigt erst 14 Kerzen später — kein Lookahead)
- Steigung = ATR(14) / 14 (Methode „Atr“, mult = 1)
- Ab Pivot-High fällt eine Widerstandslinie, ab Pivot-Low steigt eine Unterstützungslinie
- Signal = erster Close jenseits der Linie (Non-Backpainting-Variante, `upos`/`dnos`-Logik)

Trade-Management (im Indikator nicht definiert): Entry am Open der Folgekerze,
SL = 1,5 × ATR(14), TP = RR × SL-Distanz, eine Position gleichzeitig,
SL+TP in derselben Kerze = Verlust, Kosten 0,25 USD/Trade.

## Ergebnis (Gesamt | In-Sample- / Out-of-Sample-Hälfte, EV in R/Trade)

| TF | Periode | RR 1:1 | RR 2:1 | RR 3:1 |
|---|---|---|---|---|
| 15m | 2 Mon. | −8,5 R (+0,02/−0,18) | −7,2 R | +4,0 R (nur IS) |
| 30m | 3,5 Mon. | −2,5 R | +12,6 R (−0,08/+0,28) | +25,8 R (nur OOS) |
| 1h | 7 Mon. | −10,9 R | −6,8 R | −9,7 R |
| **2h** | **14 Mon.** | +8,1 R (+0,06/+0,06) | **+19,2 R (+0,14/+0,21)** | **+22,3 R (+0,19/+0,24)** |
| **4h** | **2,4 Jahre** | **+27,8 R (+0,25/+0,22)** | +18,0 R (+0,23/+0,11) | +22,1 R (+0,29/+0,15) |

**Detail 4h, RR 1:1** (bester Kandidat): 125 Trades, Winrate 61,6 %,
max. Drawdown −4,1 R, längste Verlustserie 3 Trades, t-Statistik ≈ 2,5.

**Detail 2h, RR 2:1:** 100 Trades, Winrate 40 %, max. Drawdown −8,1 R,
längste Verlustserie 8 Trades.

Long/Short-Aufschlüsselung: Longs tragen den Großteil des Gewinns
(4h: +24,3 R long vs. +3,5 R short) — Gold war 2024–2026 in einem starken
Bullenmarkt. Wichtig: Die Shorts sind trotzdem **nicht negativ**, die
Strategie verliert auf der Gegentrendseite also kein Geld.

## Bewertung

1. **Deutlich besser als die Liquidity-Grab-Strategie.** Auf 2h und 4h sind
   *alle* getesteten RR-Varianten in *beiden* Datenhälften positiv — das ist
   kein einzelner Glückstreffer, sondern ein konsistentes Muster.
2. **Klarer Timeframe-Effekt:** Auf 15m/1h funktioniert es nicht (Rauschen),
   ab 2h aufwärts schon. Trendlinien-Breaks auf höheren Timeframes fangen
   echte Trendfortsetzung ein.
3. **Der 4h/RR-1:1-Wert ist als einziger im Test statistisch auffällig**
   (t ≈ 2,5 über 125 Trades). Vorsicht bleibt geboten: 20 Zellen wurden
   getestet (Selektionseffekt), und der Zeitraum ist ein Gold-Bullenmarkt.
4. **Bullenmarkt-Abhängigkeit ist das Hauptrisiko:** Ob die Long-Kante in
   einem Seitwärts-/Bärenmarkt hält, ist aus diesen Daten nicht belegbar.

## Fazit

Als Basis weiterverfolgen lohnt sich — anders als beim Liquidity Grab gibt es
hier ein konsistentes, über zwei unabhängige Timeframes und Datenhälften
stabiles positives Signal. Nächste sinnvolle Schritte: Validierung über einen
längeren Zeitraum inkl. Nicht-Bullenphasen (z. B. Dukascopy-Tickdaten ab 2010)
und ein Test auf anderen Instrumenten, bevor echtes Geld dranhängt.

## Nachtrag v2 (13.08.2026): Kerzen-Stoploss, Exit-Varianten, 13,6 Jahre Daten

**Mehr Daten:** Externe Quellen (Dukascopy, Stooq, Binance, AlphaVantage) sind
von der Netzwerk-Policy der Umgebung blockiert. Der IBKR-Deckel liegt bei
3.500 Kerzen pro Abfrage ohne Datums-Pagination — aber auf Tageskerzen sind
das **13,6 Jahre (Jan 2013 – Aug 2026)**, inkl. Bärenmarkt 2013–2015,
Seitwärtsphasen 2016–2018/2021 und dem (in den 2h-Daten verifizierten)
Spike auf ~5.600 USD mit anschließendem Crash Anfang 2026.

**Getestet** (`trendline_v2.py`, gleiche Signale wie v1): Stop-Loss an der
Ausbruchskerze vs. 1,5×ATR; fixe RR-Ziele 1–3; Breakeven ab +1R; Exit beim
Gegensignal. Auf 2h, 4h und 1d, jeweils mit IS/OOS-Split.

### Bestes Ergebnis: SL an der Ausbruchskerze + RR 3:1

| TF | Periode | Trades | WR | Netto | EV (IS / OOS) |
|---|---|---|---|---|---|
| 2h | 14 Mon. | 88 | 38,6 % | **+46,6 R** | +0,48 / +0,52 |
| 4h | 2,4 J. | 108 | 34,3 % | **+37,8 R** | +0,36 / +0,39 |
| 1d | **13,6 J.** | 110 | 33,6 % | **+35,9 R** | **+0,23 / +0,50** |

Die einzige Variante, die auf **allen drei Timeframes in beiden Datenhälften**
positiv ist. Entscheidend: Die IS-Hälfte der Tagesdaten ist 2013–2019
(Bär + Seitwärts) — auch dort +12,5 R. Auf Tagesbasis sind Shorts (+18,8 R)
so profitabel wie Longs (+17,1 R); 10 von 14 Jahren positiv (schlechtestes
Jahr −5,3 R in 2018). Max. Drawdown 1d: −14,2 R, längste Verlustserie 8.

Der Kerzen-SL schlägt den ATR-SL, weil er strukturbasiert ist: Die
Ausbruchskerze definiert das Invalidierungsniveau, und der oft engere Stop
macht aus demselben Move mehr R.

### Übrige Varianten

- **Breakeven ab +1R:** gut auf 4h (RR3+BE: +43,9 R, konsistent), schwächer
  auf 2h/1d — kein klarer Zusatznutzen.
- **Exit bei Gegensignal:** inkonsistent (2h-OOS und 1d-IS negativ) —
  verworfen.
- **ATR-SL RR 1:1** (v1-Favorit auf 4h) versagt auf Tagesdaten in der
  IS-Hälfte (−0,17 R/Trade) — der v1-Favorit war also periodenabhängig,
  die Kerzen-SL-RR3-Variante ist es nicht.

### Einordnung

t-Statistiken pro Timeframe ≈ 1,8–2,6; 2h/4h überlappen zeitlich, und mit
inzwischen ~30 getesteten Zellen bleibt Selektionsrisiko. Die Konsistenz
über drei Timeframes, sechs Datenhälften und 14 Kalenderjahre ist aber das
robusteste Signal dieser gesamten Untersuchung.

## Reproduzieren

```bash
cd backtest && python3 trendline_breakout.py  # v1: ATR-SL, RR-Varianten
cd backtest && python3 trendline_v2.py        # v2: Kerzen-SL, BE, Gegensignal, 1d
```
