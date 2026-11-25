#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# Only ship runtime sources and the tracked, credential-free connector defaults.
remote_script=$(< scripts/install-sprite.sh)
tar --exclude='__pycache__' -czf - hearth web memory config/connectors.json scripts/run-service.sh |
  sprite exec --http-post --no-port-forward --stdin -o xuefeng-zhu -s hearth -- bash -c "$remote_script"
