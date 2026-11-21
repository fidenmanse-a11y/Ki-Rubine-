# Entwicklung

## Struktur

```
backend/
  rubine/            Python-Paket (FastAPI-App, Engine, World, Training, Jobs, Security)
  tests/             pytest (Tiny-Modell; optional echter Modelltest)
  requirements*.txt  gepinnte, gemeinsam getestete Versionen
frontend/
  app/               Next.js App Router: / (Chat), /world, /lab, /settings, /login
  components/        UI-Bausteine, Markdown, Charts, Icons
  lib/               API-Client (fetch + SSE), Typen
  public/            Manifest, Service Worker, Offline-Seite, Icons
scripts/             Setup/Start für Windows (PowerShell) und Linux/macOS
data/seed/           Seed-Trainingsdaten (von Claude Code geschrieben)
docs/                Dokumentation
```

## Getestete Versionen (21.11.2026)

Python 3.13 · torch 2.15.0 · transformers 5.24.0 · peft 0.22.0 · accelerate 1.16.0 · FastAPI 0.165.0 · uvicorn 0.54.0 ·
SQLAlchemy 2.1.9 · Node 22 · Next.js 16.4.6 · React 19.3.1 · Tailwind CSS 4.3.5 · TypeScript 5.9.3

## Entwicklungsmodus

```bash
# Terminal 1 – Backend (Port 8000)
cd backend && .venv/bin/python -m rubine          # Windows: .venv\Scripts\python -m rubine
# Terminal 2 – Frontend mit Hot Reload (Port 3000, leitet /api an :8000 weiter)
cd frontend && npm run dev
```

## Tests

```bash
cd backend
.venv/bin/python -m pytest -q                      # ~80 Tests, ca. 1 Minute, nutzt ein winziges Zufallsmodell
RUBINE_TEST_REAL_MODEL=1 .venv/bin/python -m pytest -q -k real_model   # echtes Qwen2.5-0.5B, ~2 Minuten
cd ../frontend && npx tsc --noEmit && npm run build
```

Das Tiny-Modell in den Tests erzeugt Zufallstext: Es prüft Mechanik (Streaming, Training, Checkpoints, Gates), nicht Qualität.
Test-Doubles für das Sprachmodell existieren **nur** in `tests/`.

## Neue Aufgabenfamilie hinzufügen

```python
# backend/rubine/training/curriculum.py
@register_family("meine_familie")
def gen_meine(rng, d):
    ...
    return Task("meine_familie", d, f"{prompt} {ANSWER_INSTRUCTION}", answer, f"...\nAntwort: {answer}", "exact")
```

Achtung: Neue Familien ändern den Testdatensatz nur, wenn ein neuer erzeugt wird (`data/eval/eval-v1.jsonl` löschen oder
`EVAL_SET_ID` erhöhen). Alte Eval-Ergebnisse sind dann nicht mehr vergleichbar – Versionen danach neu evaluieren.

## CLI

```bash
cd backend
.venv/bin/python -m rubine.cli status
.venv/bin/python -m rubine.cli import-data meine_daten.jsonl            # Beispiele landen als "pending"
.venv/bin/python -m rubine.cli import-seed claude_authored_v1.jsonl
.venv/bin/python -m rubine.cli synthetic 500 --seed 7
.venv/bin/python -m rubine.cli build-dataset
.venv/bin/python -m rubine.cli backup
```
