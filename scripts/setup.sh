#!/usr/bin/env bash
# Rubine AI setup for Linux/macOS (and GPU servers).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if (3,11)<=sys.version_info[:2]<=(3,13) else 1)'; then PY="$c"; break; fi
  done
fi
[ -n "$PY" ] || { echo "Python 3.11-3.13 wird benötigt."; exit 1; }
command -v node >/dev/null || { echo "Node.js >= 20.9 wird benötigt."; exit 1; }
echo "==> Python: $($PY --version), Node: $(node --version)"

[ -d backend/.venv ] || "$PY" -m venv backend/.venv
VPY="backend/.venv/bin/python"
"$VPY" -m pip install --upgrade pip -q
if command -v nvidia-smi >/dev/null; then INDEX="https://download.pytorch.org/whl/cu132"; echo "==> NVIDIA-GPU erkannt (CUDA-PyTorch)";
elif [ "$(uname)" = "Darwin" ]; then INDEX=""; echo "==> macOS (MPS/CPU)";
else INDEX="https://download.pytorch.org/whl/cpu"; echo "==> Keine NVIDIA-GPU: CPU-PyTorch"; fi
if [ -n "$INDEX" ]; then "$VPY" -m pip install -q "torch==2.15.0" --index-url "$INDEX"; else "$VPY" -m pip install -q "torch==2.15.0"; fi
"$VPY" -m pip install -q -r backend/requirements-dev.txt

if [ ! -f .env ]; then
  cp .env.example .env
  PW="$("$VPY" -c 'import secrets; print(secrets.token_urlsafe(12))')"
  sed -i.bak "s|^RUBINE_ADMIN_PASSWORD=.*|RUBINE_ADMIN_PASSWORD=$PW|" .env && rm -f .env.bak
  chmod 600 .env
  echo "==> .env erstellt. Dein Rubine-Passwort: $PW"
fi

echo "==> Lade Basismodell (einmalig, ca. 1 GB) ..."
"$VPY" -c "from huggingface_hub import snapshot_download as d; d('Qwen/Qwen2.5-0.5B-Instruct', revision='7ae557604adf67be50417f59c2c2f167def9a775')"

echo "==> Baue Web-App ..."
(cd frontend && npm ci --no-audit --no-fund && npm run build)
echo
echo "Fertig. Starten mit: scripts/start.sh"
