#!/usr/bin/env bash
# Start this computer as the preferred DPDP worker. Colab automatically takes
# over queued work when this worker is unavailable or returns an error.

set -Eeuo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DPDP_WORKER_KIND=pc
export DPDP_WORKER_ID="${DPDP_WORKER_ID:-pc-$(hostname)}"

exec "$ROOT/scripts/start_colab_worker.sh"
