#!/usr/bin/env bash
# Bootstrap and expose the DPDP RAG backend from an ephemeral Colab runtime.
#
# Required environment variable:
#   NGROK_AUTHTOKEN       ngrok token used to publish the Colab API
#
# Optional environment variables:
#   DROIDIAN_SSH_TARGET   e.g. dazai@droidian (auto-registers the ngrok URL)
#   DROIDIAN_SSH_KEY      private-key path when SSH needs an explicit key
#   DPDP_SKIP_INGEST=1    require an existing chroma_db instead of ingesting
#   DPDP_PORT=8000        local FastAPI port
#
# The process intentionally stays in the foreground. Stop it with Ctrl-C.

set -Eeuo pipefail

readonly PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly BACKEND_PORT="${DPDP_PORT:-8000}"
readonly OLLAMA_URL="http://127.0.0.1:11434"
readonly BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
readonly RUN_DIR="$(mktemp -d)"
readonly PUBLIC_URL_FILE="$RUN_DIR/public-url"
readonly NGROK_LOG="$RUN_DIR/ngrok.log"
readonly UVICORN_LOG="$RUN_DIR/uvicorn.log"

backend_pid=""
ngrok_pid=""
registered="false"

log() {
  printf '\n=== %s ===\n' "$*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

install_base_dependencies() {
  if command -v curl >/dev/null 2>&1 \
     && { command -v python >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1; }; then
    return
  fi
  command -v apt-get >/dev/null 2>&1 \
    || die "curl/Python is missing and apt-get is unavailable"
  local elevate=()
  if [[ "$(id -u)" -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || die "sudo is required to install base packages"
    elevate=(sudo)
  fi
  "${elevate[@]}" apt-get update -qq
  "${elevate[@]}" apt-get install -y -qq curl ca-certificates python3 python3-pip
}

droidian_ssh() {
  local ssh_args=(-o BatchMode=yes -o ConnectTimeout=8)
  if [[ -n "${DROIDIAN_SSH_KEY:-}" ]]; then
    ssh_args+=(-i "$DROIDIAN_SSH_KEY" -o IdentitiesOnly=yes)
  fi
  ssh "${ssh_args[@]}" "$DROIDIAN_SSH_TARGET" "$@"
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM

  if [[ "$registered" == "true" ]]; then
    droidian_ssh '~/bin/dpdp-colab-target' off >/dev/null 2>&1 || true
  fi
  [[ -z "$ngrok_pid" ]] || kill "$ngrok_pid" >/dev/null 2>&1 || true
  [[ -z "$backend_pid" ]] || kill "$backend_pid" >/dev/null 2>&1 || true
  wait "$ngrok_pid" "$backend_pid" >/dev/null 2>&1 || true
  find "$RUN_DIR" -type f -delete 2>/dev/null || true
  rmdir "$RUN_DIR" 2>/dev/null || true
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

cd "$PROJECT_ROOT"
install_base_dependencies
readonly PYTHON_BIN="$(command -v python || command -v python3)"

[[ -n "${NGROK_AUTHTOKEN:-}" ]] || die \
  "set NGROK_AUTHTOKEN (use a Colab secret; do not put it in this file)"

log "Python dependencies"
"$PYTHON_BIN" -m pip install -q --upgrade pip
"$PYTHON_BIN" -m pip install -q -r requirements.txt pyngrok

log "Ollama"
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi

if ! curl -fsS --max-time 3 "$OLLAMA_URL/api/version" >/dev/null 2>&1; then
  OLLAMA_FLASH_ATTENTION=1 \
  OLLAMA_KV_CACHE_TYPE=q8_0 \
  OLLAMA_MAX_LOADED_MODELS=1 \
  OLLAMA_NUM_PARALLEL=1 \
  OLLAMA_KEEP_ALIVE=30m \
    nohup ollama serve > "$RUN_DIR/ollama.log" 2>&1 &

  for _ in $(seq 1 45); do
    curl -fsS --max-time 3 "$OLLAMA_URL/api/version" >/dev/null 2>&1 && break
    sleep 2
  done
fi
curl -fsS --max-time 3 "$OLLAMA_URL/api/version" >/dev/null \
  || die "Ollama failed to start; inspect $RUN_DIR/ollama.log"

ollama list | awk '{print $1}' | grep -qx 'nomic-embed-text:latest' \
  || ollama pull nomic-embed-text
ollama list | awk '{print $1}' | grep -qx 'qwen2.5:7b-instruct' \
  || ollama pull qwen2.5:7b-instruct

log "DPDP corpus and vector index"
if [[ "${DPDP_SKIP_INGEST:-0}" == "1" ]]; then
  [[ -d chroma_db ]] || die "DPDP_SKIP_INGEST=1 but chroma_db is missing"
else
  "$PYTHON_BIN" scripts/fetch_sources.py
  "$PYTHON_BIN" scripts/extract_text.py
  "$PYTHON_BIN" -m dpdp_rag.ingest
fi

log "FastAPI backend"
if curl -fsS --max-time 3 "$BACKEND_URL/health" >/dev/null 2>&1; then
  echo "Using the healthy backend already listening on port $BACKEND_PORT"
else
  nohup "$PYTHON_BIN" -m uvicorn dpdp_rag.server:app \
    --host 127.0.0.1 --port "$BACKEND_PORT" \
    > "$UVICORN_LOG" 2>&1 &
  backend_pid=$!

  for _ in $(seq 1 30); do
    curl -fsS --max-time 3 "$BACKEND_URL/health" >/dev/null 2>&1 && break
    kill -0 "$backend_pid" >/dev/null 2>&1 \
      || die "backend exited; inspect $UVICORN_LOG"
    sleep 1
  done
fi
curl -fsS --max-time 3 "$BACKEND_URL/health" >/dev/null \
  || die "backend health check failed; inspect $UVICORN_LOG"

log "ngrok tunnel"
nohup "$PYTHON_BIN" - "$BACKEND_PORT" "$PUBLIC_URL_FILE" > "$NGROK_LOG" 2>&1 <<'PY' &
import os
import signal
import sys
import time
from pathlib import Path

from pyngrok import ngrok

port = int(sys.argv[1])
url_file = Path(sys.argv[2])
ngrok.set_auth_token(os.environ["NGROK_AUTHTOKEN"])
tunnel = ngrok.connect(addr=port, bind_tls=True)
url_file.write_text(tunnel.public_url, encoding="utf-8")

def stop(*_args):
    ngrok.disconnect(tunnel.public_url)
    ngrok.kill()
    raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
while True:
    time.sleep(3600)
PY
ngrok_pid=$!

for _ in $(seq 1 60); do
  [[ -s "$PUBLIC_URL_FILE" ]] && break
  kill -0 "$ngrok_pid" >/dev/null 2>&1 \
    || die "ngrok exited; inspect $NGROK_LOG"
  sleep 1
done
[[ -s "$PUBLIC_URL_FILE" ]] || die "ngrok URL was not ready; inspect $NGROK_LOG"
readonly PUBLIC_URL="$(<"$PUBLIC_URL_FILE")"
curl -fsS --max-time 15 "$PUBLIC_URL/health" >/dev/null \
  || die "public backend health check failed at $PUBLIC_URL"

log "Droidian registration"
if [[ -n "${DROIDIAN_SSH_TARGET:-}" ]] \
   && droidian_ssh true >/dev/null 2>&1; then
  droidian_ssh '~/bin/dpdp-colab-target' "$PUBLIC_URL"
  registered="true"
  curl -fsS --max-time 20 https://dpdp.hari-pi.com/health >/dev/null \
    || die "dpdp.hari-pi.com did not pass its health check"
  echo "Connected: https://dpdp.hari-pi.com -> $PUBLIC_URL"
else
  echo "Colab backend is ready at: $PUBLIC_URL"
  echo
  echo "To attach the stable subdomain, run on Droidian:"
  printf '  dpdp-colab-target %q\n' "$PUBLIC_URL"
  echo
  echo "For automatic registration, provide DROIDIAN_SSH_TARGET and, if needed,"
  echo "DROIDIAN_SSH_KEY in an environment that can reach Droidian."
fi

log "Serving continuously; press Ctrl-C to stop"
wait "$ngrok_pid"
