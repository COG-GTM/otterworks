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

# Records the tenants a run would have deployed. Like the real script it clears
# demo/deployed-at on the way in and stamps it on the way out, withholding it --
# while still exiting 0 -- for a tenant named in INCOMPLETE, which is what a
# failed Helm install leaves.
cat > "${WORK}/scripts/deploy-tenant.sh" <<'EOS'
#!/usr/bin/env bash
echo "deploy:$1 $*" >> "${DEPLOY_LOG}"
rm -f "${MARKER_DIR}/otterworks-$1"
case " ${INCOMPLETE:-} " in *" $1 "*) exit 0 ;; esac
: > "${MARKER_DIR}/otterworks-$1"
EOS

# What EC2 reports across the karpenter.sh/discovery subnets: the number matched
# and the free addresses in them. Both come back from JMESPath as floats, hence
# the ".0"; N_SUBNETS unset means the call itself produced nothing.
cat > "${WORK}/bin/aws" <<'EOS'
#!/usr/bin/env bash
case "$*" in
  *describe-subnets*)
    [ -n "${N_SUBNETS-}" ] || { [ -n "${FREE_IPS}" ] || exit 0; N_SUBNETS=2; }
    printf '%s.0 %s.0\n' "${N_SUBNETS}" "${FREE_IPS:-0}"; exit 0 ;;
  *) exit 0 ;;
esac
EOS

# EXISTING_NS is the namespaces the cluster already has, and MARKER_DIR holds a
# file per namespace carrying demo/deployed-at -- a file rather than a variable
# because the child deploy adds and removes them as a run progresses. Default:
# an empty cluster, and a NodePool wide enough not to warn.
cat > "${WORK}/bin/kubectl" <<'EOS'
#!/usr/bin/env bash
matches() { for n in $1; do case "$2" in *"${n}"*) return 0 ;; esac; done; return 1; }
case "$*" in
  *"get nodepool"*)                    echo 400; exit 0 ;;
  *"annotations.demo/deployed-at"*)
    for f in "${MARKER_DIR}"/*; do
      [ -e "${f}" ] || continue
      case "$*" in *"${f##*/}"*) echo "2026-01-01T00:00:00Z"; exit 0 ;; esac
    done
    exit 0 ;;
  *"get ns"*)                          matches "${EXISTING_NS:-}" "$*"; exit $? ;;
  *)                                   exit 0 ;;
esac
EOS

for stub in helm terraform; do printf '#!/usr/bin/env bash\nexit 0\n' > "${WORK}/bin/${stub}"; done
chmod +x "${WORK}/scripts/deploy-tenant.sh" "${WORK}/bin"/*

export PATH="${WORK}/bin:${PATH}"
export DB_PASSWORD=stub JWT_SECRET=stub SECRET_KEY_BASE=stub
export DEPLOY_LOG="${WORK}/deploy.log"
export MARKER_DIR="${WORK}/markers"; mkdir -p "${MARKER_DIR}"
export FREE_IPS="" EXISTING_NS="" DEPLOYED_NS="" INCOMPLETE=""

# Two full-profile tenants: 30 pod IPs.
run_batch() {
  : > "${DEPLOY_LOG}"
  rm -f "${MARKER_DIR}"/*
  # The state an earlier run left on the cluster.
  for n in ${DEPLOYED_NS:-}; do : > "${MARKER_DIR}/otterworks-${n}"; done
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

# JMESPath sum([]) is 0, not null, so a cluster whose subnets carry no discovery
# tag measures "0 free" -- a number, and one no roster fits in. Refusing on it
# blames capacity for what is a tagging or EKS_CLUSTER mismatch.
export N_SUBNETS=0; FREE_IPS=0; rc="$(run_batch)"
check "does not refuse a roster when no subnet carries the discovery tag" "${rc}" "0"
said "  and says the tag is what is missing" "No subnet is tagged karpenter.sh/discovery"
unset N_SUBNETS

# core tenants are 7 pods, not 15, so the same subnet holds more of them.
FREE_IPS=20; rc="$(run_batch --profile core)"
check "sizes the roster by profile" "${rc}" "0"

# deploy-tenant.sh reads TENANT_PROFILE as its own default, so sizing that ignored
# it would refuse a roster the tenants it goes on to deploy would have fitted in.
FREE_IPS=20; rc="$(TENANT_PROFILE=core run_batch)"
check "sizes by TENANT_PROFILE when --profile is not given" "${rc}" "0"

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
EXISTING_NS="otterworks-ada-lovelace" DEPLOYED_NS="ada-lovelace"
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

# A tenant whose services did not all install is not deployed, however the child
# script exited: it is the one a re-run has to pick up, so the batch cannot call
# the roster complete over it.
INCOMPLETE="ada-lovelace"; rc="$(run_batch)"
check "fails a tenant that came back without every service" "${rc}" "1"
said "  and names it as incomplete" "services missing, tenant incomplete"
said "  and reports the other one deployed" "1 deployed"

# ...including when the tenant deployed cleanly once before. The marker is set
# with `kubectl annotate`, so the namespace re-apply does not prune it: if the
# child did not clear it, this run would be judged complete on the strength of
# the previous one and the roster would report a service-less tenant as fine.
DEPLOYED_NS="ada-lovelace grace-hopper"; rc="$(run_batch --redeploy)"
check "a redeploy that loses a service is not covered by the old marker" "${rc}" "1"
said "  and still names it incomplete" "services missing, tenant incomplete"
DEPLOYED_NS=""; INCOMPLETE=""

"${WORK}/scripts/deploy-tenant-batch.sh" --profile >"${WORK}/out" 2>&1; rc="$?"
check "rejects a flag with no value" "${rc}" "1"
said "  and says which flag" "--profile needs a value"

echo ""
echo "  ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
