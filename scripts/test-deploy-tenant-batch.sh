#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Tests for the batch deploy's capacity preflight.
#
# Persistent tenants never scale to zero, so a roster's pods hold their VPC
# addresses for as long as the tenants exist and the fleet is bounded by total
# pod IPs rather than by concurrent use. Deploying past that ceiling does not
# fail fast -- pods sit Pending and each tenant times out in turn, half the
# roster in and half out. These tests pin the check that stops it, and pin that
# it stays out of the way when there is room or when the operator overrides it.
#
# The batch script is run for real, from a copy whose deploy-tenant.sh, aws and
# kubectl are stubs; nothing here touches an account or a cluster.
# ------------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
nope() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else nope "$1 (expected '$3', got '$2')"; fi; }
said() { if grep -q "$2" "${WORK}/out"; then ok "$1"; else nope "$1 (not in output: '$2')"; fi; }

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
mkdir -p "${WORK}/scripts/lib" "${WORK}/bin"
cp "${SCRIPT_DIR}/deploy-tenant-batch.sh" "${WORK}/scripts/"
cp "${SCRIPT_DIR}/lib/tenant-common.sh" "${WORK}/scripts/lib/"

# Records the tenants a run would have deployed.
cat > "${WORK}/scripts/deploy-tenant.sh" <<'EOS'
#!/usr/bin/env bash
echo "deploy:$1" >> "${DEPLOY_LOG}"
EOS

# FREE_IPS is what EC2 reports across the karpenter.sh/discovery subnets; the
# sum() JMESPath expression the script uses returns a float, hence the ".0".
cat > "${WORK}/bin/aws" <<'EOS'
#!/usr/bin/env bash
case "$*" in
  *describe-subnets*) [ -n "${FREE_IPS}" ] && printf '%s.0\n' "${FREE_IPS}"; exit 0 ;;
  *) exit 0 ;;
esac
EOS

# No namespace exists yet (rc 1), and the NodePool is wide enough not to warn.
cat > "${WORK}/bin/kubectl" <<'EOS'
#!/usr/bin/env bash
case "$*" in
  *"get nodepool"*) echo 400; exit 0 ;;
  *"get ns"*)       exit 1 ;;
  *)                exit 0 ;;
esac
EOS

for stub in helm terraform; do printf '#!/usr/bin/env bash\nexit 0\n' > "${WORK}/bin/${stub}"; done
chmod +x "${WORK}/scripts/deploy-tenant.sh" "${WORK}/bin"/*

export PATH="${WORK}/bin:${PATH}"
export DB_PASSWORD=stub JWT_SECRET=stub SECRET_KEY_BASE=stub
export DEPLOY_LOG="${WORK}/deploy.log"
export FREE_IPS=""

# Two full-profile tenants: 30 pod IPs.
run_batch() {
  : > "${DEPLOY_LOG}"
  "${WORK}/scripts/deploy-tenant-batch.sh" "$@" "Ada Lovelace" "Grace Hopper" >"${WORK}/out" 2>&1
  echo "$?"
}
# Sorted: the batch deploys concurrently, so completion order is not fixed.
deployed() { sort "${DEPLOY_LOG}" | tr '\n' ' ' | sed 's/ $//'; }

echo "batch deploy capacity preflight"

FREE_IPS=12; rc="$(run_batch)"
check "refuses a roster the node subnets cannot hold" "${rc}" "1"
check "deploys nothing when it refuses" "$(deployed)" ""
said "says which limit was hit" "Not enough pod IPs"

FREE_IPS=4000; rc="$(run_batch)"
check "deploys when there is room" "${rc}" "0"
check "deploys every tenant" "$(deployed)" "deploy:ada-lovelace deploy:grace-hopper"

FREE_IPS=12; rc="$(run_batch --no-preflight)"
check "--no-preflight overrides the refusal" "${rc}" "0"
check "--no-preflight still deploys everyone" "$(deployed)" "deploy:ada-lovelace deploy:grace-hopper"

# An unreadable subnet count must not become an outage of the deploy path: the
# check is advisory when it cannot measure.
FREE_IPS=""; rc="$(run_batch)"
check "proceeds when EC2 capacity cannot be read" "${rc}" "0"
said "warns that it could not measure" "Could not read subnet capacity"

# core tenants are 7 pods, not 15, so the same subnet holds more of them.
FREE_IPS=20; rc="$(run_batch --profile core)"
check "sizes the roster by profile" "${rc}" "0"

echo ""
echo "  ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
