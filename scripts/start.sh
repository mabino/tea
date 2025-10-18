#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[start.sh] $*" >&2
}

main() {
  log "Launching Tiny Email App runtime"
  exec python -m tea "$@"
}

main "$@"
