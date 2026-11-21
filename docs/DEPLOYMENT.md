# Bereitstellung auf einem Server (GPU, HTTPS, PostgreSQL)

> Status: Der Linux-Pfad (`setup.sh`/`start.sh`) ist getestet (CPU). GPU, PostgreSQL und Reverse-Proxy sind vorbereitet,
> aber nicht auf echter Hardware geprüft – siehe [STATUS.md](STATUS.md).

## 1. Linux-Server mit NVIDIA-GPU

```bash
git clone <repo> rubine && cd rubine
scripts/setup.sh            # erkennt nvidia-smi und installiert CUDA-PyTorch (cu132)
nano .env                   # Passwort prüfen; ggf. größeres Basismodell:
#   RUBINE_BASE_MODEL=Qwen/Qwen2.5-1.5B-Instruct
#   RUBINE_BASE_MODEL_REVISION=        (leer = neueste Revision; für Reproduzierbarkeit eine Commit-ID eintragen)
#   RUBINE_HOST=127.0.0.1               (nur der Reverse-Proxy soll zugreifen)
#   RUBINE_EVAL_SET_SIZE=200
scripts/start.sh
```

Achtung: Ein Wechsel des Basismodells macht bestehende Adapter unbrauchbar (sie gehören zum alten Modell). Nutze dafür ein
eigenes Datenverzeichnis (`RUBINE_DATA_DIR`).

### Als Dienst (systemd)

```ini
# /etc/systemd/system/rubine.service
[Unit]
Description=Rubine AI
After=network-online.target

[Service]
User=rubine
WorkingDirectory=/opt/rubine/backend
ExecStart=/opt/rubine/backend/.venv/bin/python -m rubine
Restart=on-failure
# Beim Stoppen bekommt ein laufendes Training ein Pause-Signal und speichert einen Checkpoint.
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
```

## 2. HTTPS über Reverse-Proxy (Caddy)

```caddyfile
rubine.example.org {
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1      # Server-Sent Events sofort durchreichen
    }
}
```

In `.env`: `RUBINE_ALLOWED_ORIGINS=["https://rubine.example.org"]`. Caddy besorgt automatisch ein Let's-Encrypt-Zertifikat.
Das Session-Cookie wird über `X-Forwarded-Proto: https` als `Secure` gesetzt.

Für nginx: `proxy_buffering off;` für `/api/` setzen, sonst werden Streams gepuffert.

## 3. PostgreSQL

```bash
pip install -r backend/requirements-optional.txt     # psycopg
# .env:
RUBINE_DATABASE_URL=postgresql+psycopg://rubine:PASSWORT@localhost:5432/rubine
```

Die Tabellen werden beim Start angelegt. Modelle, Datensätze und Checkpoints bleiben Dateien unter `RUBINE_DATA_DIR`
(auf schnellen Speicher legen, regelmäßig sichern).

## 4. Getrennte Rollen (später)

Die Architektur erlaubt, Inferenz und Training zu trennen: Mehrere Rubine-Instanzen können dieselbe PostgreSQL-Datenbank
und dasselbe `RUBINE_DATA_DIR` (Netzwerkspeicher) nutzen; auf der Trainingsmaschine `RUBINE_LOAD_MODEL_ON_STARTUP=false`
und `RUBINE_SIM_ENABLED=false`, auf der Chat-Maschine `RUBINE_MAX_CONCURRENT_JOBS=0`.
(Hinweis: Diese Aufteilung ist vorgesehen, aber noch nicht getestet.)
