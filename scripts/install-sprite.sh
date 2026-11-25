#!/usr/bin/env bash
set -euo pipefail
umask 077
root="$HOME/hearth"
mkdir -p -- "$root/config" "$root/releases"
release=$(mktemp -d "$root/releases/release.XXXXXXXX")
tar -xzf - -C "$release"

ln -s "$release" "$release/current"
mv -Tf -- "$release/current" "$root/current"
for service in scheduler web; do
  if sprite-env services get "$service" >/dev/null 2>&1; then
    sprite-env services restart "$service" >/dev/null 2>&1
  else
    flags=()
    if [[ "$service" == web ]]; then
      flags=(--http-port 8080)
    fi
    if ! sprite-env services create "$service" --cmd "$root/current/scripts/run-service.sh" \
        --args "$service" "${flags[@]}" >/dev/null 2>&1; then
      printf 'Could not create Hearth %s service.\n' "$service" >&2
      exit 1
    fi
  fi
done

for attempt in {1..30}; do
  if curl --noproxy '*' --fail --silent --max-time 2 http://127.0.0.1:8080/health; then
    printf '\n'
    exit 0
  fi
  sleep 1
done
printf '%s\n' 'Hearth failed the Sprite health check.' >&2
exit 1
