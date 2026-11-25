#!/usr/bin/env bash
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
org=xuefeng-zhu
private=hearth
public=hearth-pages
remote=(--http-post --no-port-forward -o "$org")

if ! sprite info -o "$org" -s "$public" >/dev/null 2>&1; then
  sprite -o "$org" create "$public" --skip-console
fi
origin=$(sprite info -o "$org" -s "$public" | awk '$1 == "URL:" {print $2}')
if [[ ! "$origin" =~ ^https://hearth-pages-[a-z0-9]+\.sprites\.app/?$ ]]; then
  printf '%s\n' 'Could not discover the dedicated Pages Sprite URL.' >&2
  exit 1
fi

config=$(mktemp)
trap 'rm -f -- "$config"' EXIT
sprite exec "${remote[@]}" --no-stdin -s "$private" -- python3 -c '
import json, os, secrets, sys
from pathlib import Path

os.umask(0o077)
target = Path.home() / "hearth/config/pages-share.json"
origin = sys.argv[1].rstrip("/")
if target.exists():
    config = json.loads(target.read_text())
    if config["origin"] != origin:
        sys.exit("The existing Pages publisher uses a different host.")
else:
    config = {"origin": origin, "secret": secrets.token_urlsafe(32)}
    staging = target.with_suffix(".tmp")
    staging.write_text(json.dumps(config))
    staging.replace(target)
print(json.dumps(config))
' "$origin" > "$config"

install='
set -euo pipefail
umask 077
root="$HOME/hearth-pages"
mkdir -p "$root/releases" "$root/data"
staging=$(mktemp -d "$root/releases/.incoming.XXXXXXXX")
trap '\''rm -rf -- "$staging"'\'' EXIT
tar xzf - -C "$staging"
if [[ -f "$root/data/secret" ]] && ! cmp -s "$staging/secret" "$root/data/secret"; then
  printf "%s\n" "The public Pages server uses a different publishing key." >&2
  exit 1
fi
mv -Tf -- "$staging/secret" "$root/data/secret"
ln -s "$staging" "$root/current.next"
mv -Tf -- "$root/current.next" "$root/current"
trap - EXIT
if sprite-env services get pages >/dev/null 2>&1; then
  sprite-env services restart pages >/dev/null
else
  sprite-env services create pages --cmd "$root/current/run" --no-stream --http-port 8080 >/dev/null
fi
for attempt in {1..20}; do
  if [[ "$(curl --noproxy "*" --silent --max-time 2 -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/)" == 404 ]]; then
    exit 0
  fi
  sleep 1
done
exit 1
'
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"; rm -f -- "$config"' EXIT
mkdir "$stage/hearth"
cp -- hearth/{__init__,page_public,page_policy,storage}.py "$stage/hearth/"
python3 -c 'import json,sys; print(json.load(sys.stdin)["secret"])' < "$config" > "$stage/secret"
cat > "$stage/run" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export HEARTH_SHARE_DATA="$HOME/hearth-pages/data"
exec python3 -m hearth.page_public --port 8080
EOF
chmod +x "$stage/run"
tar -C "$stage" -czf - hearth run secret |
  sprite exec "${remote[@]}" --stdin -s "$public" -- bash -c "$install"
sprite config update -o "$org" -s "$public" --url-auth public
printf 'Share-only origin %s\n' "$origin"
