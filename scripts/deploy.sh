#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

org=()
if [[ -n "${HEARTH_SPRITE_ORG:-}" ]]; then
  org=(-o "$HEARTH_SPRITE_ORG")
fi

# Ship the tracked runtime at the exact commit displayed by /health.
commit=$(git rev-parse HEAD)
remote_script=$(git show "$commit:scripts/install-sprite.sh")
sprite_url=$(sprite info "${org[@]}" -s hearth | awk '$1 == "URL:" {print $2}')
if [[ ! "$sprite_url" =~ ^https://[a-z0-9-]+\.sprites\.app/?$ ]]; then
  printf '%s\n' 'Could not discover the private Hearth Sprite URL.' >&2
  exit 1
fi
git archive "$commit" hearth web memory config/connectors.json config/catalog.json requirements.txt scripts/run-service.sh scripts/install-office-font.sh |
  gzip -n |
  sprite exec --http-post --no-port-forward --stdin "${org[@]}" -s hearth -- bash -c "$remote_script" hearth-install "$sprite_url" "$commit"
