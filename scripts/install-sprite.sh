#!/usr/bin/env bash
set -euo pipefail
umask 077
root="$HOME/hearth"
mkdir -p -- "$root/config" "$root/releases"
staging=$(mktemp -d "$root/releases/.incoming.XXXXXXXX")
trap 'rm -rf -- "$staging"' EXIT
cat > "$staging/bundle.tgz"
read -r bundle_id _ < <(sha256sum "$staging/bundle.tgz")
release="$root/releases/$bundle_id"
if [[ ! -d "$release" ]]; then
  mkdir "$staging/source"
  tar -xzf "$staging/bundle.tgz" -C "$staging/source"
  mv -T -- "$staging/source" "$release"
fi

ln -s "$release" "$staging/current"
mv -Tf -- "$staging/current" "$root/current"
for service in scheduler web; do
  if sprite-env services get "$service" >/dev/null 2>&1; then
    if ! sprite-env services restart "$service" >/dev/null 2>&1; then
      printf 'Could not restart Hearth %s service.\n' "$service" >&2
      exit 1
    fi
  else
    flags=()
    if [[ "$service" == web ]]; then
      flags=(--http-port 8080)
    fi
    if ! sprite-env services create "$service" --cmd "$root/current/scripts/run-service.sh" \
        --args "$service" --no-stream "${flags[@]}" >/dev/null 2>&1; then
      printf 'Could not create Hearth %s service.\n' "$service" >&2
      exit 1
    fi
  fi
done

for attempt in {1..30}; do
  if reply=$(curl --noproxy '*' --fail --silent --max-time 2 http://127.0.0.1:8080/health) &&
      [[ "$reply" == '{"ok": true, "checkpoints": "sprite"}' ]]; then
    printf '%s\n' "$reply"
    exit 0
  fi
  sleep 1
done
printf '%s\n' 'Hearth failed the Sprite health check.' >&2
exit 1
