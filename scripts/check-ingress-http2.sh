#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# NGINX2Root check for the live shared ingress-nginx controller.
#
# NGINX2Root is five bugs in nginx's HTTP/2 module (nginx 1.9.5-1.31.8; fixed
# in 1.30.7 stable / 1.31.9 mainline). Every ingress-nginx controller release
# bundles nginx 1.27.1, so the controller is safe only while HTTP/2 is off.
# Passes when the controller's nginx is a fixed version, or when HTTP/2 is
# absent from its rendered nginx.conf (and, with --url, not negotiated by ALPN).
#
# Usage: scripts/check-ingress-http2.sh [--url https://<ingress-host>[:port]]
# Env:   INGRESS_NAMESPACE (default ingress-nginx), KUBECTL_CONTEXT (optional)
# ------------------------------------------------------------------------------
set -euo pipefail

INGRESS_NAMESPACE="${INGRESS_NAMESPACE:-ingress-nginx}"
URL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --url) URL="${2:?--url needs a value}"; shift 2 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

kc() { kubectl ${KUBECTL_CONTEXT:+--context "$KUBECTL_CONTEXT"} -n "$INGRESS_NAMESPACE" "$@"; }
in_controller() { kc exec deploy/ingress-nginx-controller -c controller -- "$@"; }

nginx_fixed() {  # <major.minor.patch>: fixed in 1.30.7+ (even minor) / 1.31.9+ (odd minor)
  local maj min pat
  IFS=. read -r maj min pat <<<"$1"
  [ "$maj" -gt 1 ] && return 0
  [ "$min" -gt 31 ] && return 0
  if [ "$min" -eq 30 ]; then [ "$pat" -ge 7 ]; return; fi
  if [ "$min" -eq 31 ]; then [ "$pat" -ge 9 ]; return; fi
  return 1
}

version="$(in_controller /usr/local/nginx/sbin/nginx -v 2>&1 | sed -n 's|.*nginx/\([0-9.]*\).*|\1|p')"
[ -n "$version" ] || { echo "FAIL could not read the controller's nginx version" >&2; exit 1; }
if nginx_fixed "$version"; then
  echo "OK controller nginx ${version} is a fixed NGINX2Root version"
  exit 0
fi
echo "controller nginx ${version} is affected by NGINX2Root; HTTP/2 must be off"

conf="$(in_controller cat /etc/nginx/nginx.conf)" \
  || { echo "FAIL could not read the controller's nginx.conf" >&2; exit 1; }
fail=0
if hits="$(grep -nE '^[[:space:]]*http2[[:space:]]+on;|listen[^;]*[[:space:]]http2' <<<"$conf")"; then
  echo "FAIL HTTP/2 is enabled in the controller's nginx.conf:" >&2
  echo "$hits" >&2
  fail=1
else
  echo "ok   no HTTP/2 listener in the controller's nginx.conf"
fi

if [ -n "$URL" ]; then
  hostport="${URL#https://}"; hostport="${hostport%%/*}"
  case "$hostport" in *:*) ;; *) hostport="${hostport}:443" ;; esac
  alpn="$(openssl s_client -connect "$hostport" -servername "${hostport%:*}" -alpn h2,http/1.1 </dev/null 2>/dev/null \
    | sed -n 's/^ALPN protocol: //p')"
  if [ "$alpn" = "h2" ]; then
    echo "FAIL ${hostport} negotiates h2 over ALPN" >&2
    fail=1
  else
    echo "ok   ${hostport} negotiates ${alpn:-no ALPN protocol} (h2 offered and refused)"
  fi
fi

[ "$fail" -eq 0 ] && echo "OK shared ingress is not exposed to NGINX2Root"
exit "$fail"
