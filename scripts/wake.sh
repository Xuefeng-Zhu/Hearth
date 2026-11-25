#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${HEARTH_SPRITE_URL:-}" ]]; then
  if [[ ! "$HEARTH_SPRITE_URL" =~ ^https://[a-z0-9-]+\.sprites\.app/?$ ||
        ! "${HEARTH_TICK_TOKEN:-}" =~ ^[A-Za-z0-9_-]{43}$ ||
        ! "${SPRITE_API_TOKEN:-}" =~ ^[A-Za-z0-9._~+/=-]+$ ]]; then
    printf '%s\n' 'Set HEARTH_SPRITE_URL, HEARTH_TICK_TOKEN, and SPRITE_API_TOKEN for HTTP wake.' >&2
    exit 2
  fi
  {
    printf 'url = "%s/api/scheduler/tick"\n' "${HEARTH_SPRITE_URL%/}"
    printf 'header = "X-Hearth-Tick-Token: %s"\n' "$HEARTH_TICK_TOKEN"
    printf 'header = "Authorization: Bearer %s"\n' "$SPRITE_API_TOKEN"
  } | curl --disable --config - --silent --show-error --fail --max-time 150 --request POST
else
  org=()
  if [[ -n "${HEARTH_SPRITE_ORG:-}" ]]; then
    org=(-o "$HEARTH_SPRITE_ORG")
  fi
  sprite exec --http-post --no-stdin --no-port-forward "${org[@]}" \
    -s "${HEARTH_SPRITE_NAME:-hearth}" -- python3 -c '
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

token = (Path.home() / "hearth/data/scheduler-tick.token").read_text().strip()
request = Request("http://127.0.0.1:8080/api/scheduler/tick", method="POST",
                  headers={"X-Hearth-Tick-Token": token})
with build_opener(ProxyHandler({})).open(request, timeout=150) as response:
    print(response.read().decode())
'
fi
