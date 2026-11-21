# Ehrlicher Projektstatus (Version 0.1.0, 21.11.2026)

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
