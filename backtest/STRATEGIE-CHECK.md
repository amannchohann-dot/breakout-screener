# Überprüfung: „Liquidity Grab“-Strategie (XAU/USD, 15min)

**Geprüft am:** 11.08.2026
**Quelle der Strategie:** Twitter-Thread (Screenshots): 30 EMA als Trendfilter + LuxAlgo
„Support and Resistance Levels with Breaks“ (Left/Right Bars = 1), Einstieg nach
Liquidity Grab, Stop-Loss am Setup-Tief, 1:1 Risk-Reward.

## Testaufbau

- **Daten:** London Gold (XAUUSD Spot) via Interactive Brokers, 3.501 15-Minuten-Kerzen,
  **18.06.2026 – 11.08.2026** (ca. 8 Handelswochen), inkl. Nebenzeiten.
- **Regeln exakt wie im Thread:**
  - Support = letztes Pivot-Low, Resistance = letztes Pivot-High (Left/Right Bars = 1,
    Pivot erst 1 Kerze später bestätigt — kein Lookahead).
  - Long: Kerze bricht Support (Low < Support), schließt darüber, Close > EMA30.
    Buy-Stop am Kerzenhoch, SL am Kerzentief, TP = 1:1. Short spiegelbildlich.
  - Konservative Ausführung: SL+TP in derselben Kerze = Verlust (nur 3 Fälle);
    Pending-Order verfällt bei Riss des Setup-Tiefs oder nach 20 Kerzen.

## Ergebnis

| Szenario | Trades | Winrate | Netto | Erwartungswert |
|---|---|---|---|---|
| Ohne Kosten | 116 | 48,3 % | **−4,0 R** | −0,034 R/Trade |
| Spread 0,25 USD/Trade | 116 | 48,3 % | **−7,9 R** | −0,068 R/Trade |
| Spread 0,50 USD/Trade | 116 | 48,3 % | **−11,8 R** | −0,102 R/Trade |

**Sensitivitätsanalyse** (jeweils ohne Kosten):

| Variante | Trades | Winrate | Netto |
|---|---|---|---|
| Nur Longs | 49 | 42,9 % | −7,0 R |
| Nur Shorts | 67 | 52,2 % | +3,0 R |
| SL+TP gleiche Kerze als Gewinn gewertet (Best Case) | 116 | 50,9 % | +2,0 R |
| Order-Gültigkeit 3 statt 20 Kerzen | 120 | 48,3 % | −4,0 R |
| Order-Gültigkeit 100 Kerzen | 116 | 48,3 % | −4,0 R |

## Bewertung

1. **Die Kernbehauptung hält nicht.** „Low RR = Higher Win Rate“ stimmt zwar prinzipiell,
   aber bei 1:1 braucht man **über 50 % Winrate plus Kosten** — die Strategie liefert
   im Test nur **48,3 %**. Ergebnis: Coin-Flip minus Gebühren.
2. **Selbst der Best Case trägt die Kosten nicht.** Die optimistischste Auswertung ergibt
   +0,017 R/Trade. Ein üblicher Retail-Spread auf Gold (0,25–0,40 USD) kostet bei
   durchschnittlich 9,4 USD Stop-Distanz ca. 0,03–0,04 R pro Trade — der minimale
   Vorteil ist damit weg.
3. **Left/Right Bars = 1 erzeugt Rauschen, keine Levels.** Damit ist praktisch jede
   lokale 3-Kerzen-Schwankung ein „Support/Resistance“. Der Indikator markiert dann
   keine echten Liquiditätszonen mehr, sondern Zufallspunkte — daher die vielen
   Signale (116 Trades in 8 Wochen) ohne Kante.
4. **Die Screenshots sind selektiert.** Ohne Backtest-Zahlen, ohne Zeitraum, ohne
   Kosten. Genau die Trades, die funktioniert haben.
5. **Fehlende Filter:** keine Session-Regel (Asien-Seitwärtsphasen), kein News-Filter
   (Gold reagiert extrem auf Fed/CPI/NFP), keine Mindest-Stop-Distanz.

## Fazit

**In der beschriebenen Form nicht handelbar.** Über 8 Wochen und 116 Trades ist die
Erwartung vor Kosten leicht negativ und nach Kosten klar negativ. Das Liquidity-Grab-
Konzept (Sweep + Close zurück über das Level) ist als Baustein legitim, aber diese
Regelfassung — jedes Mini-Pivot als Level, jede Kerze als Signal, 1:1 RR — hat im
Test keinen Edge. Einschränkung: 8 Wochen sind ein kurzes Fenster; ein längerer Test
könnte anders ausfallen, aber die Beweislast liegt bei der Strategie, nicht beim Zweifel.

## Nachtrag: Multi-Timeframe-Test über längere Perioden (11.08.2026)

Da IBKR max. ~3.500 Kerzen pro Abfrage liefert, deckt jeder höhere Timeframe
automatisch eine längere Periode ab. Getestet: Original + die zwei besten
Varianten aus dem 15m-Test, auf 15m/30m/1h/2h/4h (`multi_timeframe.py`).

| TF | Periode | Original | RR 2:1 | Pivot 5 + RR 2 |
|---|---|---|---|---|
| 15m | 2 Monate | −7,9 R | **+9,7 R** | +2,6 R |
| 30m | 3,5 Monate | −0,8 R | −8,2 R | +10,7 R (nur IS) |
| 1h | 7 Monate | −14,6 R | −13,4 R | +0,8 R |
| 2h | **14 Monate** | **+7,6 R** (IS und OOS positiv) | +13,9 R (OOS flat) | −4,3 R |
| 4h | **2,4 Jahre** | +8,3 R (IS flat) | −7,4 R | −5,3 R |

**Zentrale Erkenntnis:** Die auf 15m gefundenen „Verbesserungen“ **halten auf
anderen Timeframes nicht** — RR 2:1 ist auf 30m/1h/4h negativ. Was auf einem
kurzen Fenster wie ein Edge aussah, war Periodenanpassung. Keine Variante ist
über alle Timeframes konsistent profitabel.

Einziger Kandidat mit Konsistenz: **Original-Regeln auf 2h** (105 Trades über
14 Monate, in beiden Datenhälften positiv). Aber: +0,072 R/Trade liegt bei
diesem Stichprobenumfang innerhalb einer Standardabweichung vom Zufall
(t ≈ 0,7) — statistisch nicht belastbar.

**Gesamtfazit nach 5 Timeframes und bis zu 2,4 Jahren Daten:** Kein robuster,
statistisch signifikanter Edge in keiner getesteten Regelfassung.

## Reproduzieren

```bash
python3 backtest/liquidity_grab_backtest.py backtest/xauusd_15m.json  # Basistest 15m
python3 backtest/improvement_variants.py backtest/xauusd_15m.json     # Varianten 15m
cd backtest && python3 multi_timeframe.py                             # alle Timeframes
```

(`xauusd_*.json` = IBKR-Rohdaten, im Repo enthalten.)
