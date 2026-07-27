#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Unit tests for the idle-suspend decision logic.
#
# The suspend path is the platform's main cost control, and its failure mode is
# silence: a tenant that is simply never examined looks identical to one that is
# correctly kept awake. Two real bugs here (a control-table key mismatch, and a
# scan that skipped tenants with no metrics) were invisible for exactly that
# reason, so the branches are exercised directly.
#
# kubectl / aws / the control table are stubbed; this runs anywhere.
# ------------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
nope() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else nope "$1 (expected '$3', got '$2')"; fi; }

# ---- stubs -------------------------------------------------------------------
declare -A ITEM_COUNT ITEM_SINCE
declare -A NS_RUNNING NS_CHAOS METRIC
SUSPENDED=""

ctl_tenant_exists() { [ -n "${ITEM_COUNT[$1]+x}" ] || [ -n "${NS_RUNNING[otterworks-$1]+x}" ]; }
ctl_get() {
  local id="${1#TENANT#}"
  jq -n --arg c "${ITEM_COUNT[$id]:-}" --arg s "${ITEM_SINCE[$id]:-}" \
    '{Item: ({} + (if $c=="" then {} else {req_count:{N:$c}} end)
                + (if $s=="" then {} else {idle_since:{N:$s}} end))}'
}
ctl_audit() { :; }
record_activity() { ITEM_COUNT["$1"]="$2"; ITEM_SINCE["$1"]="$3"; }
running_deployments() { echo "${NS_RUNNING[$1]:-0}"; }
tenant_has_chaos() { [ "${NS_CHAOS[$1]:-no}" = "yes" ]; }
ingress_request_counts() { for ns in "${!METRIC[@]}"; do echo "${ns} ${METRIC[$ns]}"; done; }
suspend_tenant() { SUSPENDED="${SUSPENDED} $1"; NS_RUNNING["$2"]=0; }

# tenant_namespaces is the real implementation (its exclusion list is under
# test), so kubectl is stubbed at the boundary instead.
kubectl() {
  [ "${1:-}" = "get" ] && [ "${2:-}" = "ns" ] || return 0
  for ns in "${!NS_RUNNING[@]}"; do echo "${ns}"; done
}

# Load the scan and namespace enumeration; every collaborator above is stubbed.
eval "$(sed -n '/^tenant_namespaces()/,/^}/p;/^suspend_idle_tenants()/,/^}/p' "${SCRIPT_DIR}/idle-suspend.sh")"

reset_state() {
  unset ITEM_COUNT ITEM_SINCE NS_RUNNING NS_CHAOS METRIC
  declare -gA ITEM_COUNT=() ITEM_SINCE=() NS_RUNNING=() NS_CHAOS=() METRIC=()
  SUSPENDED=""
}
NOW="$(date -u +%s)"
STALE=$(( NOW - 7200 ))   # idle well past the 3600s threshold
FRESH=$(( NOW - 60 ))

echo "idle-suspend decision logic"

# The regression that made the whole feature inert: ingress-nginx exports no
# counter series for a namespace it has never routed to.
reset_state
NS_RUNNING[otterworks-never]=13; ITEM_COUNT[never]=0; ITEM_SINCE[never]=${STALE}
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "suspends a tenant that has no metric series at all" "${SUSPENDED# }" "never"

reset_state
NS_RUNNING[otterworks-busy]=13; METRIC[otterworks-busy]=500
ITEM_COUNT[busy]=100; ITEM_SINCE[busy]=${STALE}
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "leaves a tenant serving traffic running" "${SUSPENDED# }" ""
check "  and resets its idle clock" "$([ "${ITEM_SINCE[busy]}" -ge "${NOW}" ] && echo reset)" "reset"

reset_state
NS_RUNNING[otterworks-quiet]=13; METRIC[otterworks-quiet]=100
ITEM_COUNT[quiet]=100; ITEM_SINCE[quiet]=${STALE}
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "suspends a tenant whose counter has not moved" "${SUSPENDED# }" "quiet"

reset_state
NS_RUNNING[otterworks-recent]=13; METRIC[otterworks-recent]=100
ITEM_COUNT[recent]=100; ITEM_SINCE[recent]=${FRESH}
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "waits while the tenant is under the threshold" "${SUSPENDED# }" ""

# A restarted controller resets counters to zero. Treating that as traffic would
# keep every tenant awake forever on Spot capacity.
reset_state
NS_RUNNING[otterworks-restart]=13; METRIC[otterworks-restart]=5
ITEM_COUNT[restart]=900; ITEM_SINCE[restart]=${STALE}
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "still suspends after an ingress counter reset" "${SUSPENDED# }" "restart"

reset_state
NS_RUNNING[otterworks-lab]=13; METRIC[otterworks-lab]=100
ITEM_COUNT[lab]=100; ITEM_SINCE[lab]=${STALE}; NS_CHAOS[otterworks-lab]=yes
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "never suspends a tenant with an injected scenario" "${SUSPENDED# }" ""

reset_state
NS_RUNNING[otterworks-asleep]=0; ITEM_COUNT[asleep]=100; ITEM_SINCE[asleep]=${STALE}
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "skips a tenant that is already suspended" "${SUSPENDED# }" ""

reset_state
NS_RUNNING[otterworks-new]=13
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "starts the clock on first sight, suspends nothing yet" "${SUSPENDED# }" ""
check "  and persists a baseline" "${ITEM_COUNT[new]:-unset}" "0"

reset_state
NS_RUNNING[otterworks-platform]=3; NS_RUNNING[otterworks-system]=2
ITEM_COUNT[platform]=0; ITEM_SINCE[platform]=${STALE}
ITEM_COUNT[system]=0; ITEM_SINCE[system]=${STALE}
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "never suspends the platform's own namespaces" "${SUSPENDED# }" ""

echo "${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
