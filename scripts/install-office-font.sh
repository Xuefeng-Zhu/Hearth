#!/usr/bin/env bash
set -euo pipefail
target=${1:?Pass the directory where Hearth should install its PDF font}
if [[ -s "$target/wqy-microhei.ttc" ]]; then
  exit 0
fi
mkdir -p -- "$target"
stage=$(mktemp -d "$target/.font.XXXXXXXX")
trap 'rm -rf -- "$stage"' EXIT
# WenQuanYi Micro Hei, Apache-2.0 or GPL-3+ with the font embedding exception.
curl -fsSL --retry 2 https://deb.debian.org/debian/pool/main/f/fonts-wqy-microhei/fonts-wqy-microhei_0.2.0-beta-3.1_all.deb -o "$stage/font.deb"
printf '%s  %s\n' 239163df984eea5c9da3b551aee374936222cdbd67f1a1be3cdcf3d76143ad66 "$stage/font.deb" | sha256sum --check --status
dpkg-deb -x "$stage/font.deb" "$stage/package"
install -m 644 "$stage/package/usr/share/doc/fonts-wqy-microhei/copyright" "$target/wqy-microhei-LICENSE"
mv -f -- "$stage/package/usr/share/fonts/truetype/wqy/wqy-microhei.ttc" "$target/wqy-microhei.ttc"
