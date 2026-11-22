# Experimente zu Rubine World 3.0 – mit echten Zahlen

Alle Messungen wurden am 21./22.11.2026 in der Entwicklungsumgebung ausgeführt (4 CPU-Kerne, 15 GB RAM, **keine GPU**).
Skripte liegen im Repository (`world2/benchmark.py`) bzw. sind unten beschrieben; Zahlen sind nicht geglättet oder ausgewählt.

## 1. Emergenz oder festes Muster? Fünf Welten × zwei Bedingungen

Gleicher Code, fünf Seeds (101, 202, 303, 404, 505), je **60 Simulationstage**, nur Regeln (kein Sprachmodell, damit reproduzierbar).
Bedingung **V** = normale, individuell verschiedene Persönlichkeiten/Werte/Moral. Bedingung **U** (Ablation) = alle Bewohner
erhalten identische Persönlichkeit, Werte und Moral (0,5) und gleiches Denkvermögen – Startorte, Karte und Zufall bleiben gleich.
Alle 10 Läufe: **0 Fehler, Stoffbilanz exakt ausgeglichen**.

| Seed | Bed. | Regierung(en) | Gesetze | Institutionen | Diebst. / Fälle / Urteile | Freundsch. | Bündn. | Versprechen gehalten/gebrochen | Zieltypen erreicht |
|---|---|---|---|---|---|---|---|---|---|
| 101 | V | Versammlung | – | Gesundheitsamt, Zeitung | 0 / 0 / 0 | 23 | 1 | 59 / 15 | 12 |
| 101 | U | Rat | – | – | 0 / 0 / 0 | 47 | 0 | 114 / 65 | 8 |
| 202 | V | Rat → Rat | Eigentumsschutz (Rückgabe) | – | 1 / 4 / 4 | 11 | 1 | 65 / 13 | 13 |
| 202 | U | Rat → Rat | Ressourcenschutz | Schule | 0 / 0 / 0 | 33 | 0 | 97 / 45 | 8 |
| 303 | V | Versammlung → Versammlung | Eigentumsschutz (doppelte Rückgabe) | Gericht, Gesundheitsamt, Zeitung | 1 / 1 / 1 | 9 | 0 | 50 / 44 | 13 |
| 303 | U | Rat → Rat | – | – | 0 / 0 / 0 | 38 | 0 | 74 / 50 | 6 |
| 404 | V | Rat → Rat → Versammlung | Gesundheitsversorgung | Gesundheitsamt, Schule, Zeitung | 0 / 1 / 1 | 26 | 1 | 63 / 23 | 13 |
| 404 | U | Rat → Rat | – | Schule | 0 / 0 / 0 | 48 | 0 | 116 / 44 | 8 |
| 505 | V | Rat → Versammlung | Ressourcenschutz | Schule, Zeitung | 0 / 13 / 12 | 19 | 0 | 47 / 154 | 12 |
| 505 | U | Rat → Rat | Gesundheitsversorgung | Gericht, Gesundheitsamt, Schule | 0 / 1 / 0 | 49 | 0 | 42 / 259 | 7 |

Mittelwerte (± Standardabweichung über 5 Seeds):

| Messgröße | V (verschieden) | U (identisch) |
|---|---|---|
| Vielfalt der verfolgten Ziele (Entropie, Bit) | **3,00 ± 0,10** | **2,03 ± 0,05** |
| verschiedene erreichte Zieltypen | 12,6 | 7,4 |
| Bündnisse | 0,6 | 0 |
| Freundschaften | 17,6 ± 6,6 | 43 ± 6,4 |
| aufgegebene Ziele | 93 ± 28 | 54 ± 15 |
| Anteil gehaltener Versprechen | 63 % | 56 % |
| Ungleichheit (Gini) | 0,39 ± 0,12 | 0,40 ± 0,10 |
| Bevölkerung nach 60 Tagen | 24,8 | 26,2 |

**Was man daraus ablesen kann**
- Die Welten entwickeln sich bei gleichem Code verschieden: unterschiedliche Regierungsformen und -wechsel, verschiedene oder keine
  Gesetze (Eigentumsschutz mit unterschiedlichen Sanktionen, Ressourcenschutz, Gesundheitsversorgung), verschiedene Institutionen,
  sehr unterschiedliche Konfliktniveaus (Seed 505: 13 Rechtsfälle, 154 gebrochene Versprechen).
- Mit identischen Persönlichkeiten **schrumpft die Vielfalt** in allen fünf Welten: weniger Zieltypen (Laden, Werkstatt, Wohlstand,
  Ruf, Gemeinschaft, Gerechtigkeit verschwinden), keine Bündnisse, weniger Institutionen und Gesetze. Gleichartige Bewohner
  befreunden sich dagegen häufiger. Das spricht dafür, dass das Verhalten aus individuellen Unterschieden und der jeweiligen Lage
  entsteht und nicht aus einem festen Drehbuch.
- Gleichzeitig gibt es **gemeinsame Muster** in allen Welten: die erste Siedlung entsteht am Tag 3, die erste Regierung an Tag 12–18.
  Das sind Folgen der Regeln (Wohnungsbedarf, Abstimmungsschwellen) – also durch die Spielregeln geprägt, nicht „frei erfunden“.

**Ehrliche Einschränkungen**
- In 60 normalen Tagen gab es **keine Gerüchte, keine Fehden, keine Haftstrafen und keine Berufungen** – diese Mechanismen
  benötigen starken persönlichen Ärger plus geringe Ehrlichkeit bzw. ein Gefängnis, das erst gebaut werden muss (Steinbau-Technik).
  Sie sind per Test geprüft (`tests/test_world3.py`), traten in diesen Läufen aber nicht von selbst auf.
- Neuplanungen sind häufig (≈ 15 pro Tag für 25 Personen). Ein Teil davon sind kleine Anpassungen, nicht jede ist bedeutsam.
- 60 Tage sind gut 2 simulierte Jahre; Generationenwechsel liegen außerhalb dieser Läufe.

## 2. Knappheit (natürliche Nahrung auf 15 %)

Drei Seeds, je 84 Tage. **Gefundener und behobener Fehler:** In der ersten Messung gab es trotz Hungertod (17–21 Tote) **keinen
einzigen Diebstahl**. Ursachen: (a) nachts wurden nur Schlaf/Essen/Ruhe erwogen – Wegnahme war genau dann unmöglich, wenn niemand
zusieht; (b) die Not wurde zu schwach gewichtet. Nach der Korrektur (verzweifelte Personen können nachts auch Wegnahme erwägen;
Moral, Angst, Zeugen und Schuldgefühl wiegen weiter) ergaben sich:

| Seed | Überlebende / Tote | Diebstähle | Fälle | Ergebnis |
|---|---|---|---|---|
| 31 | 8 / 19 | 2 | 2 (1 Freispruch, 1 eingestellt) | Bewohner beschließen **Eigentumsschutz (Rückgabe)** |
| 77 | 14 / 11 | 1 | 4 (2 Freisprüche, 2 ungeklärt) | kein Gesetz |
| 505 | 13 / 15 | 2 | 0 | Bewohner beschließen **Eigentumsschutz (Verbannung)** |

Kriminalität bleibt selten und wird nicht erzwungen; auf Diebstähle reagieren Gesellschaften unterschiedlich.

## 3. Bewohner-Test: Wie gut entscheiden Sprachmodelle als Bewohner?

`world2/benchmark.py`: 70 Situationen aus einer eigenen Prüfwelt (Seed 737373, Datensatz-Hash `a58e6740…`), exakt im Format
der Simulation („Wahl: Nummer“), gierige Dekodierung. Die Kategorien **Anpassung** und **Normen** sind in keinem Trainingsdatensatz
enthalten (Transfer-Test). Die Regel-Engine kann nur „Bedürfnisse“ beantworten (dort 100 %).

| Kategorie | Qwen2.5-0.5B (Basis) | rv-0001 (0.5B + LoRA) | Qwen2.5-1.5B (Basis) | Zufall |
|---|---|---|---|---|
| Bedürfnisse | 20 % | 100 % | 40 % | 25 % |
| Planung (nächster Schritt) | 40 % | 40 % | 40 % | 25 % |
| Vertrauen | 70 % | 60 % | 30 % | 50 % |
| Folgen abschätzen | 20 % | 100 % | 100 % | 25 % |
| Ursachen | 40 % | 100 % | 90 % | 33 % |
| Anpassung* | 20 % | 20 % | 80 % | 25 % |
| Normen* | 10 % | 0 % | 100 % | 33 % |
| **Gesamt** | **31,4 %** | **60,0 %** | **68,6 %** | 31 % |
| Sekunden je Entscheidung (CPU) | 1,0 | 0,8 | 3,2 | |

**Deutung**
- Das bisher verwendete 0.5B-Modell entscheidet als Bewohner **auf Zufallsniveau**; es wählte in 67 % der Fälle „3“ (Positionsfehler).
  Deshalb entscheiden in der Simulation weiterhin Regeln den Alltag; das Modell kommt nur bei knappen Abwägungen zum Zug.
- **Training wirkt – aber nur auf Trainiertes:** rv-0001 erreicht in den trainierten Situationstypen 100 %, in den zwei nie
  trainierten Kategorien jedoch keine Verbesserung (20 % / 0 %). Das ist Vorlagenlernen, keine allgemeine Urteilsfähigkeit.
- Das **größere Basismodell (1.5B)** ist ohne jedes Training besser und überträgt auf neue Situationstypen (80 % / 100 %),
  kostet aber das Dreifache an Rechenzeit und ≈ 6 GB RAM. Schwächen: Vertrauen (30 %, unter Zufall) und Planung (40 %).
- Planung „nächster Schritt“ bleibt für alle Modelle schwach (40 %) – Mehrschritt-Pläne werden deshalb von der Planungs-Engine
  erzeugt, nicht vom Sprachmodell.

## 4. Training rv-0001 über die echte Pipeline

Datenpool: 400 synthetische Aufgaben + 368 Bewohner-Entscheidungen aus 8 separaten Trainingswelten (Seeds 900000–900007) + 1
verifiziertes Beispiel → Datensatz ds-0001 (769 Beispiele, Hash `4a4318f7…`). LoRA r = 8 auf q/k/v/o (1,08 Mio. Parameter),
150 Schritte, Batch 4, CPU. Der Lauf wurde durch einen Neustart der Umgebung bei Schritt 75 unterbrochen und **vom Checkpoint
fortgesetzt** (Recovery-Funktion des Job-Managers). Loss 2,24 → 0,19 (Mittel der letzten 10 Schritte 0,09).

Unabhängiger Testdatensatz (eval-v1 + eval-sim-v1, 96 Aufgaben):

| Familie | Basis | rv-0001 |
|---|---|---|
| Gesamt | 22,9 % | **41,7 %** |
| word_problem | 25 % | 88 % |
| ordering_logic | 0 % | 75 % |
| letter_count | 12 % | 50 % |
| sim_trade | 9 % | 36 % |
| **sim_supply** | **30 %** | **0 %** |
| sim_factcheck, string_reverse, weekday_math | 0 % | 0 % |

**Prüftor: nicht bestanden** – trotz höherer Gesamtgenauigkeit wegen des Rückschritts in `sim_supply` (30 % → 0 %).
rv-0001 wurde daher **nicht aktiviert** und darf laut Modellrichtlinie auch keine Bewohner steuern. Die Zahlen in Abschnitt 3
sind eine reine Messung.

## 5. Live-Lauf mit dem 1.5B-Modell als Bewohner-Modell

Server mit Chat-Modell (0.5B) und separat geladenem 1.5B, Welt bei 5× für 4 Minuten (≈ 20 Simulationsstunden):
31 Modellanfragen, 10 beantwortet, 5 Zeitüberschreitungen, 6 veraltet verworfen, 0 ungültig, 0 Fehler. Beantwortet wurden in
diesem Fenster Dialoge (z. B. „Finn, ich freue mich so auf dein Bauwerk! Sei vorsichtig mit dem Holz …“), korrekt als
`Sprachmodell hf:Qwen/Qwen2.5-1.5B-Instruct` gekennzeichnet; Handlungsentscheidungen kamen auf der CPU bei 5× nicht rechtzeitig
und wurden von den Regeln getroffen (so markiert). Bei 1× oder mit GPU bleibt mehr Zeit pro Entscheidung.

Dabei gefundene und behobene Fehler: (1) gleichzeitiges Laden zweier Modelle in einem Prozess ließ das Chat-Modell scheitern
(„meta tensor“) → gemeinsame Ladesperre; (2) das Bewohner-Gespräch meldete das 1.5B, antwortete aber mit dem 0.5B → jetzt
antwortet tatsächlich das zugewiesene Modell oder es kommt eine klare Meldung.
