#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Tests for ensure_tenant_app_secrets: every tenant must get its own JWT_SECRET /
# SECRET_KEY_BASE (never the platform-wide value from the caller's env), and a
# redeploy must reuse the stored keys instead of rotating them.
#
# kubectl is stubbed with an in-memory per-namespace store; this runs anywhere.
# ------------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
nope() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else nope "$1 (expected '$3', got '$2')"; fi; }
differ() { if [ "$2" != "$3" ]; then ok "$1"; else nope "$1 (both '$2')"; fi; }

STORE="$(mktemp -d)"; trap 'rm -rf "${STORE}"' EXIT
GET_ERROR=""   # when set, `kubectl get` fails with this message

# kubectl -n <ns> get secret <name> -o json | kubectl -n <ns> apply -f -
kubectl() {
  local ns="$2" verb="$3"
  case "${verb}" in
    get)
      if [ -n "${GET_ERROR}" ]; then echo "${GET_ERROR}" >&2; return 1; fi
      if [ -f "${STORE}/${ns}.json" ]; then cat "${STORE}/${ns}.json"; return 0; fi
      echo "Error from server (NotFound): secrets \"$5\" not found" >&2; return 1 ;;
    apply)
      local yaml jwt skb
      yaml="$(cat)"
      jwt="$(sed -n 's/^  JWT_SECRET: //p' <<<"${yaml}")"
      skb="$(sed -n 's/^  SECRET_KEY_BASE: //p' <<<"${yaml}")"
      jq -n --arg j "${jwt}" --arg s "${skb}" '{data:{JWT_SECRET:$j,SECRET_KEY_BASE:$s}}' > "${STORE}/${ns}.json" ;;
  esac
}

# shellcheck source=tenant-common.sh
source "${SCRIPT_DIR}/tenant-common.sh"
err() { :; }

PLATFORM_JWT="platform-wide-shared-jwt-secret"
PLATFORM_SKB="platform-wide-shared-secret-key-base"

echo "per-tenant signing keys"

JWT_SECRET="${PLATFORM_JWT}"; SECRET_KEY_BASE="${PLATFORM_SKB}"
ensure_tenant_app_secrets otterworks-alice
A_JWT="${JWT_SECRET}"; A_SKB="${SECRET_KEY_BASE}"
differ "ignores the inherited platform JWT_SECRET" "${A_JWT}" "${PLATFORM_JWT}"
differ "ignores the inherited platform SECRET_KEY_BASE" "${A_SKB}" "${PLATFORM_SKB}"
check "generates a 64-char JWT_SECRET (HS512-sized key)" "${#A_JWT}" "64"
check "persists JWT_SECRET in the tenant namespace" \
  "$(jq -r .data.JWT_SECRET "${STORE}/otterworks-alice.json" | base64 -d)" "${A_JWT}"

JWT_SECRET="${PLATFORM_JWT}"; SECRET_KEY_BASE="${PLATFORM_SKB}"
ensure_tenant_app_secrets otterworks-main
differ "two tenants never share a JWT_SECRET" "${JWT_SECRET}" "${A_JWT}"
differ "two tenants never share a SECRET_KEY_BASE" "${SECRET_KEY_BASE}" "${A_SKB}"

JWT_SECRET="${PLATFORM_JWT}"; SECRET_KEY_BASE="${PLATFORM_SKB}"
ensure_tenant_app_secrets otterworks-alice
check "redeploy reuses the tenant's stored JWT_SECRET" "${JWT_SECRET}" "${A_JWT}"
check "redeploy reuses the tenant's stored SECRET_KEY_BASE" "${SECRET_KEY_BASE}" "${A_SKB}"

GET_ERROR="Error from server (Forbidden): secrets is forbidden"
JWT_SECRET=""
ensure_tenant_app_secrets otterworks-alice; rc=$?
GET_ERROR=""
differ "fails closed when the stored secret cannot be read" "${rc}" "0"
check "does not rotate the stored key on a read error" \
  "$(jq -r .data.JWT_SECRET "${STORE}/otterworks-alice.json" | base64 -d)" "${A_JWT}"

echo
echo "${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
