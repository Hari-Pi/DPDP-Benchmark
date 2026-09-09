#!/usr/bin/env bash
# Start the outbound Colab worker. No ngrok or inbound Colab port is needed.

set -Eeuo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="$(command -v python || command -v python3)"

# The repository and Colab runtime are private, so the shared worker credential
# intentionally lives here to keep startup one-command. The coordinator still
# validates it on every worker connection; public browser access uses separate
# username/password authentication.
readonly DEFAULT_DPDP_WORKER_TOKEN="5ecd4ade12ee5be628977b535b77a9a90f2205d980cd5fb8a9629ffd4d6b3abc"

# In Colab, automatically read the token from the private Secrets panel. This
# keeps the normal invocation down to one command and avoids putting the token
# in notebook output, shell history, or Git.
if [[ -z "${DPDP_WORKER_TOKEN:-}" ]] && "$PYTHON_BIN" -c \
  'import importlib.util; raise SystemExit(0 if importlib.util.find_spec("google.colab") else 1)' \
  >/dev/null 2>&1; then
  DPDP_WORKER_TOKEN="$("$PYTHON_BIN" - <<'PY'
from google.colab import userdata

try:
    print(userdata.get("DPDP_WORKER_TOKEN") or "", end="")
except Exception:
    pass
PY
)"
  export DPDP_WORKER_TOKEN
fi

DPDP_WORKER_TOKEN="${DPDP_WORKER_TOKEN:-$DEFAULT_DPDP_WORKER_TOKEN}"
export DPDP_WORKER_TOKEN

[[ -n "${DPDP_WORKER_TOKEN:-}" ]] || {
  echo "DPDP_WORKER_TOKEN is missing." >&2
  echo "Colab: add it under the key icon (Secrets), enable notebook access, and rerun." >&2
  echo "Linux: export DPDP_WORKER_TOKEN before starting this script." >&2
  exit 2
}

"$PYTHON_BIN" -m pip install -q -r requirements.txt websockets requests

# Ollama's Linux installer extracts a zstd-compressed archive. Fresh Colab
# runtimes may not include the decoder, so install it before invoking Ollama.
if ! command -v zstd >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq zstd
  else
    echo "zstd is required; install it with your system package manager." >&2
    exit 1
  fi
fi

if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
if ! curl -fsS --max-time 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 \
    OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NUM_PARALLEL=1 \
    nohup ollama serve >/tmp/ollama_dpdp_worker.log 2>&1 &
  for _ in $(seq 1 45); do
    curl -fsS --max-time 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
    sleep 2
  done
fi
curl -fsS --max-time 3 http://127.0.0.1:11434/api/version >/dev/null \
  || { echo "Ollama did not start; see /tmp/ollama_dpdp_worker.log" >&2; exit 1; }

ollama list | awk '{print $1}' | grep -qx 'nomic-embed-text:latest' \
  || ollama pull nomic-embed-text
ollama list | awk '{print $1}' | grep -qx 'qwen2.5:7b-instruct' \
  || ollama pull qwen2.5:7b-instruct

if [[ "${DPDP_SKIP_INGEST:-0}" != "1" ]]; then
  "$PYTHON_BIN" scripts/fetch_sources.py
  "$PYTHON_BIN" scripts/extract_text.py
  "$PYTHON_BIN" -m dpdp_rag.ingest
fi

exec "$PYTHON_BIN" -m dpdp_rag.worker
