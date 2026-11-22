# Ehrlicher Projektstatus (Version 0.3.0 „World 3.0“, 22.11.2026)

## Rubine World 3.0 – gemessen in dieser Umgebung (4 CPU-Kerne, keine GPU)

| Prüfung | Ergebnis |
|---|---|
| Automatische Tests | **137 bestanden**, 1 optionaler Echtmodell-Test übersprungen (davon 26 neu für World 3.0: Pläne, Neuplanung, Lernen, Emotionen, Versprechen, Gerüchte, Bündnisse, Fehden, Prozess, Haft, Unschuldsvermutung, Berufung, Spielstand-Upgrade, API, Bewohner-Test) |
| Mobile Web-App | `scripts/mobile-test.js` **31/31 bestanden** in Chromium mit iPhone-Emulation (SE, 14, 14 Pro Max) |
| **Nicht getestet** | **echtes Safari/WebKit auf einem echten iPhone** – in dieser Umgebung nicht verfügbar (siehe [IPHONE.md](IPHONE.md)) |
| Mehrwelten-Experiment | 5 Seeds × (normal / identische Persönlichkeiten), je 60 Tage: 0 Fehler, Stoffbilanz exakt ([EXPERIMENTS.md](EXPERIMENTS.md)) |
| Bewohner-Test | 0.5B 31,4 % (Zufall 31 %), 0.5B+LoRA 60,0 % (kein Transfer), 1.5B 68,6 % (mit Transfer) |
| Training über die Pipeline | rv-0001: 22,9 % → 41,7 % auf dem unabhängigen Testset, aber Rückschritt in `sim_supply` → **Prüftor nicht bestanden, nicht aktiviert** |
| Live mit Sprachmodell | Chat-Modell 0.5B + Bewohner-Modell 1.5B gleichzeitig: Dialoge und Bewohner-Gespräche vom 1.5B beobachtet |

**Was World 3.0 nicht ist:** Die Bewohner haben kein Bewusstsein und kein Erleben. Emotionen, Überzeugungen und Pläne sind
Zustandsgrößen bzw. Modellausgaben. Mehrschrittige Pläne erzeugt eine Planungs-Engine; das Sprachmodell wählt höchstens
zwischen gültigen Optionen und begründet Ziele. Details: [WORLD3.md](WORLD3.md).

**Ehrliche Einschränkungen von World 3.0**
- Gerüchte, Fehden, Haftstrafen und Berufungen sind implementiert und getestet, traten in 60-Tage-Läufen aber nicht von selbst auf.
- Diebstahl war nach Einführung der Moral-/Ziel-Logik praktisch unmöglich geworden (auch bei Hungersnot) – gefunden im
  Knappheitsexperiment und korrigiert; seither selten, aber möglich.
- Das 0.5B-Modell entscheidet als Bewohner auf Zufallsniveau. Das 1.5B ist besser, auf der CPU aber zu langsam, um bei 5× oder
  schneller Handlungsentscheidungen rechtzeitig zu liefern – dann entscheiden die Regeln (gekennzeichnet).
- LoRA-Training auf Bewohner-Entscheidungen lehrte die trainierten Situationstypen, übertrug aber nicht auf neue.
- Langläufe über mehrere Jahre wurden für World 3.0 nur bis 84 Tage gemessen (World 2.0: 12 Jahre).

---

# Status von Rubine World 2.0 (Version 0.2.0, 21.11.2026)

## Rubine World 2.0 – gemessen in dieser Umgebung (4 CPU-Kerne, keine GPU)

| Prüfung | Ergebnis |
|---|---|
| Automatische Tests | **110 bestanden** (davon 31 für World 2.0: Wirtschaft, Gesellschaft, Bewohner, Welt, Persistenz, API, Export), 1 optionaler Echtmodell-Test separat bestanden |
| Engine-Geschwindigkeit (nur Regeln) | 360–380 Ticks/s über 5 Jahre (100× benötigt 6,7 Ticks/s) |
| Langläufe (nur Regeln) | Seeds 21 und 22 je 5 Jahre, Seed 23 über **12 Jahre** (32 256 Ticks in 88 s): **0 Fehler, Stoffbilanz exakt ausgeglichen** |
| Neustart | Snapshot laden und weiterlaufen ist **bitgenau identisch** zum ununterbrochenen Lauf (Test); Server-Neustart setzt die laufende Welt fort |
| Speicherbedarf | nach 5 Jahren ≈ 420 KB komprimierter Snapshot, ≈ 6 600 Ereignisse, ≈ 28 000 Entscheidungen in der Welt-DB |
| Sprachmodell als „Denken“ | echte Entscheidungen, Dialoge, Benennungen mit Qwen2.5-0.5B (Basis) im laufenden Server beobachtet; bei 1× und CPU ≈ 1 Antwort pro 5–10 s |
| iPhone-Ansicht | Karte (Pinch/Pan, Tag-Nacht, Regen/Schnee nur wo es simuliert regnet), Inspektor, Feed, Panels in Chromium mit iPhone-14-Emulation geprüft |

**Beobachtete emergente Verläufe** (nicht vorprogrammiert, gleicher Code, unterschiedliche Seeds):
- Seed 21: zuerst Versammlungsdemokratie, später durch einen gewählten Rat ersetzt; zwei Regionen mit je eigenem Rat und eigener
  Währung; Gesetze zu Eigentumsschutz und Gesundheitsversorgung; ein Ressourcenschutzgesetz wurde beschlossen und wieder aufgehoben;
  Schulen, Gericht, Gesundheitsamt; 16 Rechtsfälle (meist Verstöße gegen den Ressourcenschutz).
- Seed 22: Versammlung → Rat; 5 Jahre **ohne ein einziges Gesetz**; eine Währung; 5 Todesfälle (Krankheit, Kälte, Wassermangel).
- Seed 23: im ersten Jahr ein Rat, der durch eine Versammlungsdemokratie ersetzt wurde, die danach 12 Jahre bestand; Gesetze zu
  Gesundheitsversorgung und Eigentumsschutz; Ungleichheit (Gini) stieg von 0,28 auf bis zu 0,44; 12 Geburten, 11 Todesfälle.
- Knappheitsexperiment (Naturnahrung auf 15 %): 18 von 25 Bewohnern verhungerten in 2 Jahren; ein Diebstahl, danach beschlossen
  die Bewohner einen Eigentumsschutz.

**Ehrliche Einschränkungen von World 2.0**
- In den Langläufen mit normalen Ressourcen kam es zu **keinem Diebstahl und keiner Gewalt** – Not war zu selten. Die Mechanismen
  (Tat, Zeugen, falsche Beschuldigung, Ermittlung, Urteil, Sanktion) sind per Test und im Knappheitsexperiment geprüft.
- Generationen: In 12 Jahren erreichten die ersten Kinder noch nicht das Erwachsenenalter (18 Jahre ≈ 2 Stunden bei 100× bzw. ≈ 2 Minuten im Headless-Lauf ohne Modell).
  Die Übergabe an Erwachsene ist getestet, aber noch nicht in einem Langlauf beobachtet.
- Langläufe liefen **ohne Sprachmodell**. Mit Modell treffen die Bewohner bei knappen, bedeutsamen Entscheidungen Modellwahlen –
  auf der CPU aber nur einen kleinen Teil; der Rest bleibt regelbasiert und ist so markiert.
- Getestet bis ca. 35 Bewohner. Größere Populationen sind konfigurierbar, aber nicht erprobt.
- Details und weitere Grenzen: [WORLD2.md](WORLD2.md).

---

# Status von Rubine 0.1 (Chat, Training, AI Lab)

Diese Datei trennt strikt zwischen **ausgeführt und überprüft**, **implementiert, aber nicht ausgeführt** und **nicht vorhanden**.
Entwickelt und getestet wurde in einer Linux-Umgebung (Python 3.13, 4 CPU-Kerne, 15 GB RAM, **keine GPU**).

## ✅ Ausgeführt und überprüft

| Komponente | Wie überprüft |
|---|---|
| Echtes Basismodell im Chat | Qwen2.5-0.5B-Instruct (Revision `7ae5576…`) über die API geladen, Antworten per SSE gestreamt (≈ 8–12 Tokens/s auf CPU) |
| Chat-Funktionen | Automatisierte API-Tests (Tiny-Modell): Senden, Streaming, Bearbeiten, Neu generieren, Umbenennen, Löschen, Suche, Feedback; UI per Playwright im iPhone-14-Viewport (Chromium) |
| Echte LoRA-Trainingsrunde | Über das AI Lab/API gestartet, Ergebnisse unten |
| Pausieren/Fortsetzen | Echte Trainingsrunde bei Schritt 4 pausiert (Checkpoint gespeichert, Prozess beendet), fortgesetzt ab Schritt 5 bis Schritt 12 |
| Evaluation + Gate | Unabhängiger Testdatensatz, Vergleich gegen Elternversion; Gate hat eine Version korrekt **abgelehnt** (siehe unten) |
| Aktivieren / Rollback / Vergleich | Über die API ausgeführt; nicht bestandene Versionen lassen sich nicht aktivieren (Test) |
| Rubine World | 25 Agenten laufen serverseitig; Gespräche, Pläne und Aufgabenlösungen wurden vom echten Modell erzeugt; Prüflabor verifiziert gegen Musterlösungen |
| Lehrer „lokales HF-Modell“ | Echter Job: 8 Aufgaben gestellt, 3 verifiziert übernommen, 5 falsche verworfen |
| Datenpipeline | Synthetische Daten, Seed-Import (38/38 importiert, alle 19 Rechenaufgaben verifiziert), Datensatz-Versionierung mit SHA-256, Eval-Ausschluss, Eigenanteil-Grenze (Tests) |
| Sicherheit | Tests: alle privaten Endpunkte 401 ohne Login, Login-Rate-Limit (429), Cross-Origin-POST 403, gefälschte Tokens abgelehnt, Prompt-Injection-Filter, Log-Schwärzung, Pfad-Traversal beim Seed-Import |
| PWA | Manifest, Icons, Apple-Meta-Tags ausgeliefert; Service Worker aktiv und Offline-Seite erscheint bei Netzverlust (Chromium, sicherer Kontext `localhost`) |
| Erreichbarkeit im Netzwerk | Server bindet an `0.0.0.0` und war über die LAN-IP der Testmaschine erreichbar (App, Manifest, Icons, API) |
| Linux-Setup | `scripts/setup.sh` + `scripts/start.sh` vollständig durchgelaufen (venv, CPU-PyTorch, `.env` mit Zufallspasswort, Modell-Download, App-Build, Start) |
| Testsuite | `pytest`: 79 bestanden, 1 optionaler Test (echtes Modell) separat ausgeführt und bestanden |

### Gemessene Trainingsergebnisse (CPU, 4 Kerne)

**rv-0001** – Ausgangsversion: Basis; Datensatz ds-0001 mit 403 Beispielen (400 synthetisch, 3 Agenten-verifiziert); 40 Schritte,
Batch 4, Lernrate 2e-4, LoRA r = 8 (1,08 Mio. trainierbare Parameter = 0,22 %), Dauer 254 s.

| Metrik | Basis | rv-0001 |
|---|---|---|
| Trainings-Loss (Mittel erste/letzte 10 Schritte) | 1,270 | 0,267 |
| Genauigkeit eval-v1 (64 Aufgaben) | 20,3 % | **34,4 %** |
| Eval-Loss der Musterlösungen | 1,676 | 0,643 |
| arithmetic / word_problem | 50 % / 25 % | 62,5 % / 100 % |
| letter_count / ordering_logic | 12,5 % / 0 % | 25 % / 25 % |
| sorting / unit_conversion | 50 % / 25 % | 37,5 % / 25 % |
| string_reverse / weekday_math | 0 % / 0 % | 0 % / 0 % |

Gate: bestanden → als Vorschlag markiert, **nicht** automatisch aktiviert (danach manuell aktiviert).

**rv-0002** – weitertrainiert von rv-0001, 12 Schritte, Batch 2: Genauigkeit 39,1 %, aber `letter_count` fiel von 25 % auf 0 % →
Gate **nicht bestanden**, Version nicht aktivierbar.

**Einordnung:** Der Testdatensatz hat 64 Aufgaben (8 pro Familie). Eine einzelne Aufgabe macht 1,6 Prozentpunkte gesamt bzw.
12,5 Punkte pro Familie aus – Unterschiede sind daher verrauscht. Für belastbare Aussagen `RUBINE_EVAL_SET_SIZE` erhöhen
(z. B. 200–500, braucht entsprechend länger) – das erzeugt einen neuen Testdatensatz. Die Verbesserung betrifft eng umrissene,
prüfbare Aufgaben; ein 0,5-B-Modell bleibt im freien Gespräch deutlich schwächer als große Cloud-Modelle.

## ⚠️ Implementiert, aber hier nicht ausgeführt

| Komponente | Grund |
|---|---|
| Windows-Skripte (`Rubine-Setup.bat`, `Rubine-Start.bat`, `scripts/*.ps1`) | Keine Windows-/PowerShell-Umgebung verfügbar. Geschrieben für Windows PowerShell 5.1 (nur ASCII, Exit-Codes geprüft). Logik entspricht dem getesteten `setup.sh`. Bitte melde Fehler. |
| Safari / echtes iPhone | Nur Chromium mit iPhone-14-Emulation getestet. WebKit-spezifische Unterschiede (z. B. Backdrop-Filter, Safe Areas) nicht auf einem Gerät geprüft. |
| CUDA-/GPU-Training | Keine GPU verfügbar. Code wählt `cuda` automatisch und nutzt bf16/fp16; Setup installiert CUDA-PyTorch (cu132), wenn `nvidia-smi` existiert. |
| PostgreSQL | Über `RUBINE_DATABASE_URL` vorgesehen (SQLAlchemy, portable Typen), nicht gegen einen echten Postgres-Server getestet. |
| Lehrer über Ollama/OpenAI-kompatibel | HTTP-Format per Test (gemockter Server) geprüft, nicht gegen echtes Ollama ausgeführt. |
| Anthropic-Lehrer | Kein API-Schlüssel vorhanden; Code nicht gegen die echte API ausgeführt. Optionales Paket. |
| HTTPS mit eigenem Zertifikat | uvicorn-SSL getestet (Secure-Cookie gesetzt). Service Worker unter selbstsigniertem Zertifikat lehnt Chromium ab – für das iPhone wird ein vertrauenswürdiges Zertifikat benötigt (Tailscale, siehe IPHONE.md). |

## ❌ Bewusst (noch) nicht enthalten

- Kein Training auf dem iPhone (nicht Ziel). Kein Vortraining eines eigenen Basismodells von Grund auf.
- Keine Datenbank-Migrationen (Alembic); das Schema wird beim Start angelegt. Bei Schemaänderungen künftiger Versionen
  vorher ein Backup (`data/backups/` wird bei jedem Start automatisch geschrieben).
- Wichtigkeit von Erinnerungen wird heuristisch (pro Art) und nicht per LLM bewertet; Relevanz lexikalisch statt über Embeddings – um CPU-Zeit zu sparen.
- Kein Mehrbenutzersystem (ein Besitzer, ein Passwort).
- QLoRA/4-Bit-Training, verteiltes Training: nicht implementiert.

## Bekannte Schwächen

- Qualität der Agenten-Gespräche entspricht einem 0,5-B-Modell: teils floskelhaft oder unlogisch. Ein größeres Basismodell oder
  `RUBINE_AGENT_BACKEND=openai_compatible` mit einem lokalen 7-B-Modell verbessert das deutlich.
- Der Prüfer-Agent gibt oft keine auswertbare „Wahl“ ab; das ist unkritisch, weil nur der programmatische Prüfer über Trainingsdaten entscheidet.
- Auf der CPU konkurrieren Chat, Simulation und Training um Rechenzeit. Simulation während eines Trainings pausieren beschleunigt das Training.
