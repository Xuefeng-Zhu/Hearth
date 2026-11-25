#!/usr/bin/env bash
set -euo pipefail
root=$(cd -L -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -L)
cd -- "$root/current"
export HEARTH_DATA_DIR="$root/data"
export PYTHONDONTWRITEBYTECODE=1
case "${1:-}" in
  web)
    export HEARTH_CHECKPOINTS=sprite
    export HEARTH_CONNECTOR_CONFIG="$root/config/connectors.local.json"
    exec python3 -m hearth.server --host 0.0.0.0 --port 8080
    ;;
  scheduler)
    exec python3 -m hearth.scheduler
    ;;
  *)
    printf '%s\n' 'Expected a Hearth service name.' >&2
    exit 2
    ;;
esac
