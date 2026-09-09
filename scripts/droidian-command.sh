#!/usr/bin/env bash
# Run one command on the Droidian server.
#
# Usage:
#   ./scripts/droidian-command.sh 'uname -a'

set -euo pipefail

if [[ "$#" -eq 0 ]]; then
  echo "Usage: $0 '<command>'" >&2
  exit 2
fi

readonly DROIDIAN_HOST="dazai@droidian"

exec ssh "$DROIDIAN_HOST" "$@"
