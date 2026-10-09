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
RACE=""        # when set, a concurrent deploy creates this JWT just before our create

store_secret() { # <ns> <jwt-b64> <skb-b64>
  jq -n --arg j "$2" --arg s "$3" '{data:{JWT_SECRET:$j,SECRET_KEY_BASE:$s}}' > "${STORE}/$1.json"
}
b64() { printf '%s' "$1" | base64 | tr -d '\n'; }
stored_jwt() { jq -r .data.JWT_SECRET "${STORE}/$1.json" | base64 -d; }

# kubectl -n <ns> get secret <name> -o json | kubectl -n <ns> create -f -
kubectl() {
  local ns="$2" verb="$3"
  case "${verb}" in
    get)
      if [ -n "${GET_ERROR}" ]; then echo "${GET_ERROR}" >&2; return 1; fi
      if [ -f "${STORE}/${ns}.json" ]; then cat "${STORE}/${ns}.json"; return 0; fi
      echo "Error from server (NotFound): secrets \"$5\" not found" >&2; return 1 ;;
    create)
      local yaml; yaml="$(cat)"
      if [ -n "${RACE}" ]; then store_secret "${ns}" "$(b64 "${RACE}")" "$(b64 race-skb)"; RACE=""; fi
      if [ -f "${STORE}/${ns}.json" ]; then
        echo "Error from server (AlreadyExists): secrets \"tenant-app-secrets\" already exists" >&2; return 1
      fi
      store_secret "${ns}" "$(sed -n 's/^  JWT_SECRET: //p' <<<"${yaml}")" \
        "$(sed -n 's/^  SECRET_KEY_BASE: //p' <<<"${yaml}")" ;;
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
check "persists JWT_SECRET in the tenant namespace" "$(stored_jwt otterworks-alice)" "${A_JWT}"

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
check "does not rotate the stored key on a read error" "$(stored_jwt otterworks-alice)" "${A_JWT}"

RACE="key-from-concurrent-deploy"
ensure_tenant_app_secrets otterworks-bob; rc=$?
check "concurrent first deploy succeeds" "${rc}" "0"
check "concurrent first deploy adopts the winning persisted key" "${JWT_SECRET}" "key-from-concurrent-deploy"
check "concurrent first deploy does not overwrite the winner" "$(stored_jwt otterworks-bob)" "key-from-concurrent-deploy"

store_secret otterworks-carol "$(b64 good-jwt)" ""
JWT_SECRET=""
ensure_tenant_app_secrets otterworks-carol; rc=$?
differ "fails closed when a stored key is missing" "${rc}" "0"
check "does not rotate a partially stored secret" "$(stored_jwt otterworks-carol)" "good-jwt"
check "leaves JWT_SECRET unset on failure" "${JWT_SECRET}" ""

store_secret otterworks-dave "%%%not-base64%%%" "$(b64 skb)"
ensure_tenant_app_secrets otterworks-dave; rc=$?
differ "fails closed when a stored key is undecodable" "${rc}" "0"

echo
echo "${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
