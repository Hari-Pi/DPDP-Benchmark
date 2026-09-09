#!/usr/bin/env bash
# Open a persistent interactive shell on the Droidian server.
#
# Usage:
#   ./scripts/droidian-shell.sh

set -euo pipefail

readonly DROIDIAN_HOST="dazai@droidian"

# Use macOS's normal SSH agent/Keychain integration. exec preserves a single,
# continuous interactive terminal session.
exec ssh -tt "$DROIDIAN_HOST"
