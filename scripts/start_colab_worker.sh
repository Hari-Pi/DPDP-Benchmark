#!/usr/bin/env bash
# Start the outbound Colab worker. No ngrok or inbound Colab port is needed.

set -Eeuo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="$(command -v python || command -v python3)"
export DPDP_WORKER_KIND="${DPDP_WORKER_KIND:-colab}"

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

# Tune parallel contexts to the accelerator visible in this runtime. Ollama's
# memory use grows with parallelism × context length, so these profiles leave
# headroom for the embedding model and GPU-resident retrieval matrix.
gpu_name="none"
vram_mib=0
if command -v nvidia-smi >/dev/null 2>&1; then
  gpu_name="$(nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1 | xargs)"
  vram_mib="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits \
    | head -n 1 | xargs)"
elif [[ "$(uname -s)" == "Darwin" ]]; then
  gpu_name="Apple Metal (unified memory)"
  vram_mib="$(( $(sysctl -n hw.memsize) / 1024 / 1024 ))"
fi

if (( vram_mib >= 32768 )); then
  detected_parallel=4; detected_context=8192
elif (( vram_mib >= 20000 )); then
  detected_parallel=3; detected_context=6144
elif (( vram_mib >= 12000 )); then
  detected_parallel=2; detected_context=5120
else
  detected_parallel=1; detected_context=4096
fi

export DPDP_WORKER_CONCURRENCY="${DPDP_WORKER_CONCURRENCY:-$detected_parallel}"
export DPDP_NUM_CTX="${DPDP_NUM_CTX:-$detected_context}"
export DPDP_MAX_OUTPUT_TOKENS="${DPDP_MAX_OUTPUT_TOKENS:-800}"
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-$DPDP_WORKER_CONCURRENCY}"
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-2}"
export OLLAMA_MAX_QUEUE="${OLLAMA_MAX_QUEUE:-64}"
export OLLAMA_CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH:-$DPDP_NUM_CTX}"
export OLLAMA_FLASH_ATTENTION="${OLLAMA_FLASH_ATTENTION:-1}"
export OLLAMA_KV_CACHE_TYPE="${OLLAMA_KV_CACHE_TYPE:-q8_0}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:--1}"
export DPDP_GPU_RETRIEVAL="${DPDP_GPU_RETRIEVAL:-1}"
echo "GPU: $gpu_name; memory=${vram_mib}MiB; workers=$DPDP_WORKER_CONCURRENCY; context=$DPDP_NUM_CTX; output_tokens=$DPDP_MAX_OUTPUT_TOKENS"

if ! command -v ollama >/dev/null 2>&1; then
  if [[ "$(uname -s)" == "Darwin" ]]; then
    command -v brew >/dev/null 2>&1 \
      || { echo "Install Homebrew from https://brew.sh first." >&2; exit 1; }
    brew install ollama
  else
    # Ollama's Linux installer extracts a zstd-compressed archive. Fresh Colab
    # runtimes may not include the decoder.
    if ! command -v zstd >/dev/null 2>&1; then
      if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq zstd
      else
        echo "zstd is required; install it with your package manager." >&2
        exit 1
      fi
    fi
    curl -fsSL https://ollama.com/install.sh | sh
  fi
fi
if ! curl -fsS --max-time 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
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

# Load both models once and keep them resident. This eliminates repeated model
# disk reads and CPU-to-GPU weight transfers during normal requests.
curl -fsS http://127.0.0.1:11434/api/embed \
  -d '{"model":"nomic-embed-text","input":"warmup","keep_alive":-1}' >/dev/null
curl -fsS http://127.0.0.1:11434/api/generate \
  -d '{"model":"qwen2.5:7b-instruct","prompt":"","keep_alive":-1}' >/dev/null
ollama ps

if [[ "${DPDP_SKIP_INGEST:-0}" != "1" ]]; then
  "$PYTHON_BIN" scripts/fetch_sources.py
  "$PYTHON_BIN" scripts/extract_text.py
  "$PYTHON_BIN" -m dpdp_rag.ingest
fi

exec "$PYTHON_BIN" -m dpdp_rag.worker
