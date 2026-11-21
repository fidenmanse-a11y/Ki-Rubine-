# Training: Wie Rubine besser wird

> Wichtig: Gespräche der Agenten in Rubine World verändern **keine** Modellgewichte. Gewichte ändern sich nur durch
> eine Trainingsrunde im AI Lab (echtes LoRA-Fine-Tuning mit PyTorch + PEFT).

## Pipeline

```
 Aufgaben (Curriculum)  ──►  Lösungen  ──►  Prüfung  ──►  Beispiel-Pool  ──►  Datensatz ds-XXXX  ──►  LoRA-Training
   synthetisch                Agenten-Teams      Musterlösung     (Herkunft,         (Snapshot, SHA-256,      rv-XXXX
   Lehrer-Modelle             Lehrer             + Sicherheits-   Status)            Eval-Ausschluss,             │
   Import (Claude Code)       Import             filter                              Eigenanteil ≤ 50 %)          ▼
                                                                                                    Evaluation auf eval-v1
                                                                                                    (vs. Elternversion)
                                                                                                              │
                                                                                     bestanden ──► „Bestanden“ (Vorschlag)
                                                                                     sonst     ──► „Test nicht bestanden“
                                                                                     Aktivieren nur manuell · Rollback jederzeit
```

1. **Aufgaben.** `training/curriculum.py` erzeugt prüfbare Aufgaben aus 8 Familien (Arithmetik, Textaufgaben,
   Einheiten, Sortieren, Buchstaben zählen, Reihenfolge-Logik, Wochentage, Wörter umkehren) in 3 Schwierigkeitsstufen.
   Die Curriculum-Stufe (Grundlagen → Aufbau → Fortgeschritten) richtet sich nach der Eval-Genauigkeit der aktiven Version.
2. **Lösungen** kommen aus vier Quellen:
   - `synthetic_gold` – per Code erzeugte Musterlösung (korrekt durch Konstruktion).
   - `agent_verified` – Agenten in Rubine World lösen Aufgaben **mit dem aktiven Rubine-Modell** unabhängig voneinander,
     ein Prüfer-Agent vergleicht, das Prüflabor verifiziert gegen die Musterlösung.
   - `teacher_local` / `teacher_api` – Lehrer-Modelle (siehe unten), ebenfalls gegen die Musterlösung geprüft.
   - `manual_import` – JSONL-Dateien, z. B. von Claude Code erstellt.
   - `user_chat` – nur mit ausdrücklicher Zustimmung pro Chat und 👍, landet als *ausstehend* in der Prüfwarteschlange.
3. **Aussortieren.** Ohne Antwortzeile, falsches Ergebnis, Steuer-Tokens, Prompt-Injection-Phrasen, Duplikate → verworfen.
   Nicht prüfbare Beispiele (freie Lehrer-Antworten, Importe, Nutzer-Chats) bleiben `pending`, bis du sie im AI Lab freigibst.
4. **Datensatz.** Ein Build nimmt alle freigegebenen Beispiele, entfernt jede Aufgabe, die im Testdatensatz vorkommt,
   begrenzt selbst erzeugte Beispiele auf höchstens 50 % (`RUBINE_MAX_SELF_GENERATED_FRACTION`) und **verweigert** einen
   Datensatz, der nur aus selbst erzeugten Beispielen bestünde. Ergebnis: `data/datasets/ds-XXXX/train.jsonl` +
   `manifest.json` mit SHA-256. Beim Training wird der Hash geprüft.
5. **LoRA-Training.** Eigene Trainingsschleife (`training/trainer.py`): Seed, deterministische Datenreihenfolge,
   Loss nur auf der Antwort, AdamW + Warmup/linearer Abfall, Gradient-Clipping, Checkpoints. Ergebnis: Adapter in
   `data/models/rv-XXXX/adapter` + `training_summary.json`. Basismodell-Revision ist gepinnt.
6. **Evaluation.** Greedy-Generierung auf dem eingefrorenen Testdatensatz `eval-v1` (Standard 64 Aufgaben, alle Familien),
   programmatische Prüfung, plus Eval-Loss der Musterlösungen. Gleiche Aufgaben für Kandidat und Elternversion.
7. **Gate.** Bestanden, wenn Genauigkeit ≥ Eltern + `RUBINE_GATE_MIN_DELTA` **und** keine Familie mehr als
   `RUBINE_GATE_MAX_FAMILY_DROP` (15 Prozentpunkte) verliert. Auch dann wird nur **vorgeschlagen**.

## Warum sich Rubine nicht „im Kreis“ selbst trainiert

- Selbst erzeugte Antworten zählen nur, wenn ein **Programm** (nicht ein Modell) sie gegen die Musterlösung bestätigt.
- Ihr Anteil pro Datensatz ist begrenzt; unabhängige Quellen (synthetisch, Lehrer, Import) sind Pflicht.
- Der Testdatensatz ist getrennt erzeugt, gehasht und wird beim Datensatz-Build aktiv ausgeschlossen.
- Das Urteil des Prüfer-Agenten wird angezeigt (Statistik), aber nie als Wahrheit für Trainingsdaten verwendet.

## Lehrer-Modelle

| Lehrer | Einrichtung | Kosten |
|---|---|---|
| Lokales Open-Weight-Modell über **Ollama**/llama.cpp/LM Studio/vLLM | z. B. `ollama pull qwen2.5:7b-instruct`, dann in `.env`: `RUBINE_TEACHER_OPENAI_BASE_URL=http://localhost:11434/v1`, `RUBINE_TEACHER_OPENAI_MODEL=qwen2.5:7b-instruct` | lokal, kostenlos |
| Lokales Hugging-Face-Modell | `RUBINE_TEACHER_LOCAL_HF_MODEL=Qwen/Qwen2.5-1.5B-Instruct` | lokal; braucht RAM |
| Anthropic API (optional) | `pip install -r backend/requirements-optional.txt`, `RUBINE_ANTHROPIC_API_KEY=...` (eigener API-Schlüssel von console.anthropic.com) | kostenpflichtig pro Token |
| Manueller Import | JSONL im AI Lab hochladen oder `python -m rubine.cli import-data datei.jsonl` | – |

Ein Claude-Abo (claude.ai) enthält **keinen** API-Zugang; Rubine versucht nicht, das zu umgehen. Die App funktioniert
vollständig ohne Anthropic-API. Beim Anthropic-Lehrer ist der serverseitige Refusal-Fallback aktiviert
(`fallbacks: "default"`), damit eine abgelehnte Anfrage automatisch auf einem Fallback-Modell beantwortet wird.

## Datenformat für Importe (z. B. von Claude Code erstellt)

Eine JSON-Zeile pro Beispiel:

```json
{"prompt": "Erkläre LoRA kurz.", "response": "LoRA ist ...", "author": "claude-code"}
{"messages": [{"role": "user", "content": "Hallo"}, {"role": "assistant", "content": "Hallo! Wie kann ich helfen?"}]}
{"prompt": "Berechne 125 · 8. Denke kurz Schritt für Schritt und schreibe am Ende genau eine Zeile 'Antwort: <Ergebnis>'.",
 "response": "125 · 8 = 1000.\nAntwort: 1000", "task": {"kind": "number", "answer": "1000"}, "family": "arithmetic"}
```

Zeilen mit `task` werden beim Import geprüft; falsche werden verworfen. Mitgeliefert: `data/seed/claude_authored_v1.jsonl`
(38 Beispiele, von Claude Code während der Entwicklung geschrieben: Identität/Ehrlichkeit, Erklärungen, Code, 19 geprüfte Rechenaufgaben).

## Empfohlene erste Trainingsrunde (CPU)

1. AI Lab → Daten hinzufügen → 400 synthetische Aufgaben, Seed-Datensatz importieren.
2. Training starten: 40–60 Schritte, Batch 4, Lernrate 2e-4, r = 8. Dauer auf 4 CPU-Kernen ≈ 5–7 Minuten + ≈ 5 Minuten Evaluation.
3. Ergebnis in „Modellversionen“ ansehen (Loss, Genauigkeit pro Familie, Gate-Begründung), ggf. aktivieren.

Mit GPU: mehr Schritte (300–1000), größere Batches, `RUBINE_EVAL_SET_SIZE=200` für belastbarere Messungen.
