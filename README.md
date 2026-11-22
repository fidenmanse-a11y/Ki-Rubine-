# 💎 Rubine AI

**Eine eigene, selbst trainierbare KI – mit Chat, einer autonomen Simulationsgesellschaft aus 25 KI-Agenten und einem AI Lab für echtes LoRA-Fine-Tuning. Läuft auf deinem PC, bedienbar vom iPhone (PWA).**

Rubine ist **keine** Oberfläche für ChatGPT oder Claude. Jede Antwort im Chat stammt von einem lokal laufenden Open-Weight-Modell
(Basis: [Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct), Apache-2.0), das über eigene LoRA-Adapter
Version für Version weitertrainiert wird.

| Bereich | Was es tut |
|---|---|
| **Chat** | Mehrere Unterhaltungen, Umbenennen/Löschen, Bearbeiten, Neu generieren, Streaming, Markdown + Code mit Kopieren, Suche, Modellversion wählen |
| **Rubine World 2.0** | Persistente KI-Gesellschaft: 25 simulierte Bewohner ohne vorgegebene Regierung, Gesetze, Geld oder Gebäude. Sie bauen, handeln, gründen Familien, Regierungen, Gerichte, Schulen und Währungen, erkranken, altern und sterben – alles über eine prüfbare World Engine. Interaktive Karte mit Tag/Nacht und Wetter, Bewohner-Inspektor, Live-Feed, Chronik, Steuerung ([Details](docs/WORLD2.md)) |
| **World 3.0** | Bewohner mit eigenen Zielen, mehrschrittigen Plänen mit erwarteten Folgen, Neuplanung bei Unerwartetem, simulierten Emotionen, Überzeugungen (auch Irrtümern), Lektionen, Moral und Geheimnissen; Freundschaften, Versprechen, Überzeugen, Gerüchte, Bündnisse, Fehden; Justiz mit Ermittlung, Unschuldsvermutung, Falschaussagen, Haft, Entlassung, Fehlurteilen und Berufung; Bewohner-Test für Sprachmodelle ([Details](docs/WORLD3.md), [Experimente](docs/EXPERIMENTS.md)) |
| **Klassische Welt (v0.1)** | Die ursprüngliche Smallville-Stadt bleibt optional erhalten (`RUBINE_SIM_ENABLED=true`, Seite `/world/classic`) |
| **AI Lab** | Trainingsdaten erzeugen/importieren/prüfen, versionierte Datensätze, echtes LoRA-Training (Start/Pause/Stopp), Live-Loss, Evaluation, Modellvergleich, Aktivierung, Rollback, Ressourcen-Monitor |
| **iPhone** | Installierbare PWA (OLED-Schwarz, Liquid Glass, Safe Areas/Dynamic Island), 5 Bereiche Welt · Menschen · Gesellschaft · AI Lab · Chat, Gespräche mit Bewohnern, „Zum Home-Bildschirm“ |

➡️ **Was tatsächlich läuft und was gemessen wurde: [docs/STATUS.md](docs/STATUS.md)**

---

## Schnellstart (Windows)

Voraussetzungen: **Python 3.11–3.13** ([python.org](https://www.python.org/downloads/), Haken bei „Add to PATH“) und **Node.js 20+ LTS** ([nodejs.org](https://nodejs.org/)). Ca. 5 GB freier Speicher, 8 GB RAM (16 GB empfohlen).

1. Repository herunterladen (ZIP entpacken oder `git clone`).
2. **`Rubine-Setup.bat`** doppelklicken. Das Skript installiert alles, lädt das Basismodell (~1 GB), baut die App und zeigt dir dein **Passwort** (steht danach in `.env`).
3. **`Rubine-Start.bat`** doppelklicken. Im Fenster erscheinen die Adressen, z. B.
   ```
   Lokal:       http://localhost:8000
   iPhone/WLAN: http://192.168.178.23:8000
   ```
4. Am PC `http://localhost:8000` öffnen und mit dem Passwort anmelden.

Mit NVIDIA-Grafikkarte installiert das Setup automatisch die CUDA-Version von PyTorch. Ohne GPU läuft alles auf der CPU – Chat und Training funktionieren, Training ist aber langsam (≈ 6–7 s pro Schritt auf 4 CPU-Kernen).

Linux/macOS/GPU-Server: `scripts/setup.sh` und `scripts/start.sh`.

## Auf dem iPhone öffnen

1. PC und iPhone im **selben WLAN**.
2. Einmalig die Windows-Firewall für das private Netzwerk öffnen: PowerShell **als Administrator** →
   `powershell -ExecutionPolicy Bypass -File scripts\allow-firewall.ps1`
3. Auf dem iPhone in **Safari** die „iPhone/WLAN“-Adresse aus dem Startfenster öffnen (z. B. `http://192.168.178.23:8000`).
4. Teilen-Symbol → **„Zum Home-Bildschirm“**. Rubine startet danach wie eine App im Vollbild.

Details, Fehlersuche und sicherer Zugriff von unterwegs (HTTPS über Tailscale): **[docs/IPHONE.md](docs/IPHONE.md)**

## Die KI verbessern – der Ablauf

1. **AI Lab → Daten hinzufügen**: z. B. 300 synthetische Aufgaben erzeugen, den Seed-Datensatz `claude_authored_v1.jsonl` importieren
   und „Aus Rubine World“ verifizierte Aufgaben aus echten Simulationsereignissen exportieren.
2. **Training starten** (z. B. 60 Schritte). Rubine baut einen versionierten Datensatz, trainiert einen LoRA-Adapter und
   evaluiert ihn gegen die Ausgangsversion auf einem **unabhängigen, eingefrorenen Testdatensatz**.
3. Besteht die Version die Prüfung, wird sie **vorgeschlagen** – du aktivierst sie selbst. Rollback ist jederzeit möglich.

Wie das Training gegen Selbstbestätigung abgesichert ist: **[docs/TRAINING.md](docs/TRAINING.md)**

## Dokumentation

- [docs/STATUS.md](docs/STATUS.md) – ehrlicher Stand, Messergebnisse, Grenzen
- [docs/WORLD3.md](docs/WORLD3.md) – World 3.0: Ziele, Pläne, Innenzustand, soziale Mechanik, Justiz, Bewohner-Test, App
- [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md) – Mehrwelten-Experimente, Ablation, Bewohner-Test, Training – mit echten Zahlen
- [docs/WORLD2.md](docs/WORLD2.md) – Rubine World 2.0: Regeln der Welt, Agentenarchitektur, Persistenz, Training, Grenzen
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) – Aufbau, Komponenten, Datenfluss
- [docs/TRAINING.md](docs/TRAINING.md) – Trainingspipeline, Lehrer-Modelle, Datenformat für Claude-Importe
- [docs/IPHONE.md](docs/IPHONE.md) – iPhone, PWA, WLAN, HTTPS
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) – GPU-Server, PostgreSQL, HTTPS-Bereitstellung
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) – Entwicklung, Tests, Projektstruktur

## Lizenzhinweise

Code dieses Repositories: siehe Repository-Einstellungen des Eigentümers. Basismodell Qwen2.5-0.5B-Instruct: Apache License 2.0
(Alibaba Cloud). Trainierte Adapter sind abgeleitete Werke des Basismodells.
