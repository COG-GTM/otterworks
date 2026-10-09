#!/usr/bin/env bash
# Unit tests for the per-tenant JWT key + token binding in tenant-common.sh.
# kubectl is stubbed with a file-backed fake so no cluster is needed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

mkdir -p "${WORK}/bin" "${WORK}/store"
cat > "${WORK}/bin/kubectl" <<'STUB'
#!/usr/bin/env bash
# kubectl -n NS get secret NAME -o jsonpath=...  |  kubectl -n NS create secret generic NAME --from-literal=K=V
ns="$2"; verb="$3"
case "$verb" in
  get)    f="${KSTORE}/${ns}.$5"; [ -f "$f" ] || { echo "NotFound" >&2; exit 1; }; base64 < "$f" | tr -d '\n' ;;
  create) f="${KSTORE}/${ns}.$6"; [ ! -f "$f" ] || { echo "AlreadyExists" >&2; exit 1; }; printf '%s' "${7#--from-literal=JWT_SECRET=}" > "$f" ;;
esac
STUB
chmod +x "${WORK}/bin/kubectl"
export PATH="${WORK}/bin:${PATH}" KSTORE="${WORK}/store"

# shellcheck source=../lib/tenant-common.sh
source "${ROOT}/scripts/lib/tenant-common.sh"

fail=0
check() { if [ "$2" = "$3" ]; then echo "ok   - $1"; else echo "FAIL - $1: got '$2' want '$3'"; fail=1; fi; }

export JWT_SECRET="platform-wide-shared-secret"
a1="$(ensure_tenant_jwt_secret otterworks-alice)"
b1="$(ensure_tenant_jwt_secret otterworks-bob)"
a2="$(ensure_tenant_jwt_secret otterworks-alice)"

check "tenant key is 32 random bytes (hex)" "$(printf '%s' "$a1" | grep -cE '^[0-9a-f]{64}$')" "1"
check "tenant key is not the platform JWT_SECRET" "$([ "$a1" != "$JWT_SECRET" ] && echo yes)" "yes"
check "tenants get distinct keys" "$([ "$a1" != "$b1" ] && echo yes)" "yes"
check "redeploy reuses the stored tenant key" "$a2" "$a1"
check "tenant audience is derived from the tenant id" "$(tenant_jwt_audience Alice_01)" "otterworks-alice-01"
check "audiences differ per tenant" "$([ "$(tenant_jwt_audience alice)" != "$(tenant_jwt_audience bob)" ] && echo yes)" "yes"

# build_helm_args wires the key plus iss/aud into every token-validating service.
JWT_SECRET="$a1" T_JWT_AUDIENCE="$(tenant_jwt_audience alice)"
T_REDIS_HOST=redis T_MEILI_URL=http://meilisearch:7700 T_DB_NAME=db T_WIRE_EVENTING=false
DB_ENDPOINT_HOST=db DB_ENDPOINT_PORT=5432 DB_PASSWORD=x SECRET_KEY_BASE=y AWS_REGION=us-east-1
irsa_arn() { :; }
# Infra outputs (DB_USER, buckets, ...) come from Terraform in a real deploy.
set +u
for svc in api-gateway auth-service document-service collab-service admin-service; do
  EXTRA_ARGS=(); SECRET_KV=()
  build_helm_args "$svc" >/dev/null || true
  args=" ${EXTRA_ARGS[*]} "
  check "$svc gets tenant JWT_AUDIENCE" "$([[ "$args" == *"config.JWT_AUDIENCE=otterworks-alice "* ]] && echo yes)" "yes"
  check "$svc gets JWT_ISSUER" "$([[ "$args" == *"config.JWT_ISSUER=otterworks-auth-service "* ]] && echo yes)" "yes"
  check "$svc gets the tenant key" "$([[ " ${SECRET_KV[*]} " == *" JWT_SECRET $a1 "* ]] && echo yes)" "yes"
done

exit "$fail"
