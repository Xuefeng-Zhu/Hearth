#!/usr/bin/env bash
set -euo pipefail
root=$(cd -L -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -L)
cd -- "$root/current"
export HEARTH_DATA_DIR="$root/data"
export PYTHONDONTWRITEBYTECODE=1
export HEARTH_CJK_FONT="$root/config/fonts/wqy-microhei.ttc"
case "${1:-}" in
  web)
    export HEARTH_CHECKPOINTS=sprite
    export HEARTH_SHARE_CONFIG="$root/config/pages-share.json"
    if [[ -f "$root/config/public-url" ]]; then
      export HEARTH_PUBLIC_URL
      HEARTH_PUBLIC_URL=$(< "$root/config/public-url")
    fi
    export HEARTH_CONNECTOR_CONFIG="$root/config/connectors.local.json"
    exec "$root/.venv/bin/python" -m hearth.server --host 0.0.0.0 --port 8080
    ;;
  scheduler)
    exec "$root/.venv/bin/python" -m hearth.scheduler
    ;;
  *)
    printf '%s\n' 'Expected a Hearth service name.' >&2
    exit 2
    ;;
esac
