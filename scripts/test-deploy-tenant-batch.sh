#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Tests for the batch deploy's capacity preflight and its lifecycle flags.
#
# A batch brings the whole roster up at once, so the fleet is bounded by total
# pod IPs rather than by concurrent use -- permanently so with --always-on,
# where nothing ever scales back to zero. Deploying past that ceiling does not
# fail fast: pods sit Pending and each tenant times out in turn, half the roster
# in and half out. These tests pin the check that stops it, pin that it stays
# out of the way when there is room or when the operator overrides it, and pin
# that staying awake is something the operator asks for.
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
said() { if grep -q -- "$2" "${WORK}/out"; then ok "$1"; else nope "$1 (not in output: '$2')"; fi; }

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
mkdir -p "${WORK}/scripts/lib" "${WORK}/bin"
cp "${SCRIPT_DIR}/deploy-tenant-batch.sh" "${WORK}/scripts/"
cp "${SCRIPT_DIR}/lib/tenant-common.sh" "${WORK}/scripts/lib/"

# Records the tenants a run would have deployed.
cat > "${WORK}/scripts/deploy-tenant.sh" <<'EOS'
#!/usr/bin/env bash
echo "deploy:$1 $*" >> "${DEPLOY_LOG}"
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

# EXISTING_NS is the namespaces the cluster already has, DEPLOYED_NS the subset
# that carries demo/deployed-at. Default: an empty cluster, and a NodePool wide
# enough not to warn.
cat > "${WORK}/bin/kubectl" <<'EOS'
#!/usr/bin/env bash
matches() { for n in $1; do case "$2" in *"${n}"*) return 0 ;; esac; done; return 1; }
case "$*" in
  *"get nodepool"*)                    echo 400; exit 0 ;;
  *"annotations.demo/deployed-at"*)
    matches "${DEPLOYED_NS:-}" "$*" && echo "2026-01-01T00:00:00Z"; exit 0 ;;
  *"get ns"*)                          matches "${EXISTING_NS:-}" "$*"; exit $? ;;
  *)                                   exit 0 ;;
esac
EOS

for stub in helm terraform; do printf '#!/usr/bin/env bash\nexit 0\n' > "${WORK}/bin/${stub}"; done
chmod +x "${WORK}/scripts/deploy-tenant.sh" "${WORK}/bin"/*

export PATH="${WORK}/bin:${PATH}"
export DB_PASSWORD=stub JWT_SECRET=stub SECRET_KEY_BASE=stub
export DEPLOY_LOG="${WORK}/deploy.log"
export FREE_IPS="" EXISTING_NS="" DEPLOYED_NS=""

# Two full-profile tenants: 30 pod IPs.
run_batch() {
  : > "${DEPLOY_LOG}"
  "${WORK}/scripts/deploy-tenant-batch.sh" "$@" "Ada Lovelace" "Grace Hopper" >"${WORK}/out" 2>&1
  echo "$?"
}
# Sorted: the batch deploys concurrently, so completion order is not fixed.
deployed() { sed 's/ .*//' "${DEPLOY_LOG}" | sort | tr '\n' ' ' | sed 's/ $//'; }
deploy_flags() { grep -c -- '--always-on' "${DEPLOY_LOG}"; }

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

# Staying awake is opt-in. Without the flag a tenant idles like any other, which
# is the whole point of it being a flag: the exemption holds its compute and pod
# IPs whether or not anyone opens the URL.
FREE_IPS=4000; rc="$(run_batch)"
check "does not make tenants always-on by default" "$(deploy_flags)" "0"
said "  and says they will idle" "scale to zero after an hour idle"

rc="$(run_batch --always-on)"
check "--always-on succeeds" "${rc}" "0"
check "  passes the flag to every tenant" "$(deploy_flags)" "2"
said "  and says the fleet is permanently reserved" "reserved permanently"

# Resuming a half-finished roster. deploy-tenant.sh creates the namespace in its
# first seconds, so "namespace exists" is also what a deploy that died at the
# database or Helm step leaves behind: skipping on that alone would report the
# roster complete while leaving those people with a shell of a tenant.
FREE_IPS=4000
EXISTING_NS="otterworks-ada-lovelace" DEPLOYED_NS="otterworks-ada-lovelace"
rc="$(run_batch)"
check "skips a tenant that finished deploying" "$(deployed)" "deploy:grace-hopper"
check "  and succeeds" "${rc}" "0"
said "  and counts it as deployed, not attempted" "Skipping 1 deployed tenant"

DEPLOYED_NS=""
rc="$(run_batch)"
check "retries a tenant left half-built by an earlier run" "$(deployed)" \
  "deploy:ada-lovelace deploy:grace-hopper"
said "  and says so" "Retrying 1 incomplete tenant"
EXISTING_NS=""

"${WORK}/scripts/deploy-tenant-batch.sh" --profile >"${WORK}/out" 2>&1; rc="$?"
check "rejects a flag with no value" "${rc}" "1"
said "  and says which flag" "--profile needs a value"

echo ""
echo "  ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
