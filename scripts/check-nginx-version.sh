#!/usr/bin/env bash
# Fail if an image's nginx is older than the NGINX2Root fix: 1.30.7 on the
# stable (even) branch, 1.31.9 on the mainline (odd) branch, and no older line.
#
#   scripts/check-nginx-version.sh <image> [<image>...]
set -euo pipefail

[[ $# -ge 1 ]] || { echo "usage: $0 <image> [<image>...]" >&2; exit 2; }

ver_ge() { [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" == "$2" ]]; }

status=0
for image in "$@"; do
  out="$(docker run --rm --entrypoint nginx "$image" -v 2>&1)"
  version="$(sed -n 's|.*nginx/\([0-9][0-9.]*\).*|\1|p' <<<"$out" | head -n1)"
  if [[ -z "$version" ]]; then
    echo "FAIL $image: could not read nginx version from: $out" >&2
    status=1; continue
  fi
  minor="$(cut -d. -f2 <<<"$version")"
  if (( minor % 2 == 0 )); then min=1.30.7; else min=1.31.9; fi
  if ver_ge "$version" "$min"; then
    echo "OK   $image: nginx $version (>= $min)"
  else
    echo "FAIL $image: nginx $version is affected by NGINX2Root (need >= $min)" >&2
    status=1
  fi
done
exit "$status"
