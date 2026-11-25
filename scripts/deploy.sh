#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# Only ship runtime sources and the tracked, credential-free connector defaults.
remote_script=$(< scripts/install-sprite.sh)
sprite_url=$(sprite info -o xuefeng-zhu -s hearth | awk '$1 == "URL:" {print $2}')
if [[ ! "$sprite_url" =~ ^https://[a-z0-9-]+\.sprites\.app/?$ ]]; then
  printf '%s\n' 'Could not discover the private Hearth Sprite URL.' >&2
  exit 1
fi
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner --exclude='__pycache__' -czf - hearth web memory config/connectors.json config/catalog.json requirements.txt scripts/run-service.sh scripts/install-office-font.sh |
  sprite exec --http-post --no-port-forward --stdin -o xuefeng-zhu -s hearth -- bash -c "$remote_script" hearth-install "$sprite_url"
