#!/usr/bin/env bash
# DPDP RAG — one-shot setup + run for Google Colab (or any Linux box with a GPU).
#
# Usage (after cloning the repo):
#   bash scripts/colab_setup.sh
#
# Every stage is idempotent/resumable: sources already downloaded are skipped,
# ingest continues from its checkpoint, and the benchmark skips completed
# cases. Rerun this script any number of times.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

log() { echo -e "\n=== $* ==="; }

# --- 1. Python dependencies -------------------------------------------------
log "[1/6] Python dependencies"
python -m pip install -q -r requirements.txt

# --- 2. Ollama ---------------------------------------------------------------
log "[2/6] Ollama"
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
else
  echo "ollama already installed: $(ollama --version 2>/dev/null || echo '?')"
fi

# --- 3. Server ---------------------------------------------------------------
log "[3/6] Ollama server"
if curl -s --max-time 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  echo "server already running"
else
  OLLAMA_FLASH_ATTENTION=1 \
  OLLAMA_KV_CACHE_TYPE=q8_0 \
  OLLAMA_MAX_LOADED_MODELS=1 \
  OLLAMA_NUM_PARALLEL=1 \
  OLLAMA_KEEP_ALIVE=30m \
    nohup ollama serve > /tmp/ollama_dpdp.log 2>&1 &
  for _ in $(seq 1 30); do
    curl -s --max-time 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
    sleep 2
  done
  curl -s --max-time 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1 \
    && echo "server up (flash-attn + q8 KV + single-model)" \
    || { echo "server FAILED to start — see /tmp/ollama_dpdp.log"; exit 1; }
fi

# --- 4. Models ----------------------------------------------------------------
log "[4/6] Models"
ollama list | grep -q "nomic-embed-text"      || ollama pull nomic-embed-text
ollama list | grep -q "qwen2.5:7b-instruct"   || ollama pull qwen2.5:7b-instruct

# --- 5. Corpus -----------------------------------------------------------------
log "[5/6] Corpus (fetch + extract + ingest, all resumable)"
python scripts/fetch_sources.py
python scripts/extract_text.py
python -m dpdp_rag.ingest

# --- 6. Benchmark ---------------------------------------------------------------
log "[6/7] Benchmark (resumable)"
python scripts/benchmark.py --k 8

# --- 7. Bundle -----------------------------------------------------------------
log "[7/7] Pack dpdp_bundle.zip for local serving"
python scripts/bundle.py

log "DONE — summary:"
python scripts/progress.py
