# Architektur

```
 iPhone (Safari / PWA)                    Windows-PC oder Server
┌───────────────────────┐   HTTP(S)   ┌───────────────────────────────────────────────────────────┐
│ Next.js 16 static     │◄───────────►│ FastAPI (uvicorn, ein Port, z. B. 8000)                     │
│ export (React 19,     │  JSON + SSE │  ├─ /api/auth      Login, HttpOnly-Session-Cookie          │
│ Tailwind 4)           │             │  ├─ /api/chat      Unterhaltungen, Streaming (SSE)         │
│ Chat · World · Lab    │             │  ├─ /api/world     Simulation, Live-Stream (SSE)           │
│ Service Worker (HTTPS)│             │  ├─ /api/lab       Daten, Jobs, Versionen, Live-Stream     │
└───────────────────────┘             │  └─ /*             ausgelieferte PWA (frontend/out)        │
                                      │                                                           │
                                      │  ModelEngine (Thread)   ── Basismodell + LoRA-Adapter       │
                                      │     Chat hat Vorrang vor Agenten-„Gedanken“                 │
                                      │  World (asyncio-Tick + Kognitions-Thread)                   │
                                      │  JobManager (Thread) ──► Worker-Prozesse                   │
                                      │                           python -m rubine.jobs.runner ID   │
                                      │                           (Training / Eval / Daten)         │
                                      │  SQLite (WAL)  ·  data/models · data/datasets · data/eval   │
                                      └───────────────────────────────────────────────────────────┘
```

## Komponenten

| Modul | Aufgabe |
|---|---|
| `rubine/config.py` | Alle Einstellungen über `RUBINE_*`-Umgebungsvariablen bzw. `.env` |
| `rubine/db.py` | SQLAlchemy-2-Modelle. Standard SQLite (WAL, Backups beim Start); `RUBINE_DATABASE_URL` für PostgreSQL |
| `rubine/llm/engine.py` | Lädt Basismodell einmal, hängt LoRA-Adapter pro Version an (PEFT), Streaming via `TextIteratorStreamer`, Prioritäts-Lock (Chat vor Simulation) |
| `rubine/llm/registry.py` | Versionen, Aktivierungshistorie, Aktivieren nur für `passed`, Rollback |
| `rubine/chat/router.py` | Chat-API: CRUD, Senden/Bearbeiten/Neu generieren mit SSE, Feedback, Suche, Zustimmung zum Training |
| `rubine/world/*` | Stadtplan, 25 Personas, Gedächtnis (Recency + Importance + Relevance), Simulation, API |
| `rubine/training/curriculum.py` | 8 Aufgabenfamilien × 3 Schwierigkeiten mit Generator, Musterlösung und programmatischem Prüfer; Curriculum-Stufen |
| `rubine/training/evalset.py` | Eingefrorener, gehashter Testdatensatz aus separatem Seed-Namensraum |
| `rubine/training/data.py` | Beispiel-Pool mit Herkunft, Sicherheitsfilter, Import, versionierte Datensatz-Snapshots |
| `rubine/training/trainer.py` | Eigene reproduzierbare LoRA-Trainingsschleife mit Checkpoints (Pause/Fortsetzen) |
| `rubine/training/evaluate.py` | Batch-Evaluation (greedy), Eval-Loss, Freigabe-Gate |
| `rubine/training/teachers.py` | Lehrer-Schnittstelle: OpenAI-kompatibel (Ollama etc.), lokales HF-Modell, Anthropic API (optional) |
| `rubine/jobs/*` | Job-Warteschlange in der DB, Worker-Prozesse, Steuerung, Wiederherstellung nach Absturz |
| `rubine/security/*` | Auth, Rate-Limit, Prompt-Injection-Filter, Log-Schwärzung |

## Wichtige Entscheidungen

- **Ein Port, gleiche Herkunft.** FastAPI liefert die statisch exportierte Next.js-App aus. Dadurch funktionieren
  HttpOnly-Cookies mit `SameSite=Strict`, und das iPhone braucht nur eine Adresse.
- **Training in eigenen Prozessen.** Ein Trainingsjob kann den Server nicht blockieren und lässt sich sicher beenden.
  Fortschritt, Metriken und Steuersignale (`pause`/`stop`) laufen über die Datenbank.
- **Pausieren = Checkpoint + Prozessende.** Beim Pausieren speichert der Worker Adapter, Optimizer, Scheduler und
  RNG-Zustand und beendet sich (gibt RAM/VRAM frei). Fortsetzen startet einen neuen Prozess ab genau diesem Schritt.
  Stürzt der Server ab, wird ein laufendes Training beim nächsten Start als „pausiert“ markiert, wenn ein Checkpoint existiert.
- **Ein Adapter pro Version.** Jede Version ist ein LoRA-Adapter auf dem fest gepinnten Basismodell (Revision im Code).
  Weitertrainieren initialisiert den neuen Adapter mit den Gewichten der Elternversion.
- **Keine erfundenen Inhalte.** Ist kein Modell geladen, liefert der Chat eine klare Fehlermeldung (HTTP 503), und
  Agenten bewegen sich weiter, sprechen aber nicht.
- **Skalierung.** PostgreSQL über `RUBINE_DATABASE_URL`; GPU automatisch erkannt (`cuda`/`mps`/`cpu`); größere Basismodelle
  über `RUBINE_BASE_MODEL`. Mehrere parallele Jobs über `RUBINE_MAX_CONCURRENT_JOBS` (Standard 1).

## Datenablage (`data/`, nicht im Git)

```
data/rubine.db              SQLite (Chats, Agenten, Gedächtnis, Beispiele, Jobs, Versionen, Audit-Log)
data/secret.key             Signierschlüssel für Sessions (automatisch erzeugt)
data/backups/               automatische Backups beim Start (letzte 10)
data/datasets/ds-XXXX/      train.jsonl + manifest.json (SHA-256, Herkunft, Parameter) – unveränderlich
data/models/rv-XXXX/adapter LoRA-Adapter + training_summary.json
data/eval/eval-v1.jsonl     eingefrorener Testdatensatz; data/eval/runs/ Einzelergebnisse
data/jobs/<job>/            Log und Checkpoints
data/seed/                  mitgelieferte, von Claude Code geschriebene Seed-Daten (im Git)
```
