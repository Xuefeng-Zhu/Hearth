#!/usr/bin/env bash
set -euo pipefail
umask 077
root="$HOME/hearth"
commit="${2:-}"
if [[ ! "$commit" =~ ^[a-f0-9]{40}$ ]]; then
  printf '%s\n' 'The release needs a valid Git commit.' >&2
  exit 1
fi
mkdir -p -- "$root/config" "$root/releases"
staging=$(mktemp -d "$root/releases/.incoming.XXXXXXXX")
trap 'rm -rf -- "$staging"' EXIT
printf '%s\n' "${1%/}" > "$staging/public-url"
mv -Tf -- "$staging/public-url" "$root/config/public-url"
cat > "$staging/bundle.tgz"
read -r bundle_id _ < <(sha256sum "$staging/bundle.tgz")
release="$root/releases/$commit-$bundle_id"
if [[ ! -d "$release" ]]; then
  mkdir "$staging/source"
  tar -xzf "$staging/bundle.tgz" -C "$staging/source"
  printf '%s\n' "$commit" > "$staging/source/.deployed-commit"
  mv -T -- "$staging/source" "$release"
fi

# Install into an isolated environment and only resolve dependencies when the lock changes.
venv="$root/.venv"
if [[ ! -x "$venv/bin/python" ]]; then
  python3 -m venv "$venv"
fi
if ! cmp -s "$release/requirements.txt" "$venv/.hearth-requirements"; then
  "$venv/bin/python" -m pip --disable-pip-version-check install -q -r "$release/requirements.txt"
  cp -- "$release/requirements.txt" "$venv/.hearth-requirements"
fi
"$release/scripts/install-office-font.sh" "$root/config/fonts"

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
      "$venv/bin/python" -c 'import json,sys; d=json.load(sys.stdin); sys.exit(not (
        d.get("ok") is True and d.get("checkpoints") == "sprite" and d.get("version") == sys.argv[1]))' "$commit" <<< "$reply"; then
    printf '%s\n' "$reply"
    exit 0
  fi
  sleep 1
done
printf '%s\n' 'Hearth failed the Sprite health check.' >&2
exit 1
