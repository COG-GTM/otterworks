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
declare -A ITEM_COUNT ITEM_SINCE ITEM_RUNNING
declare -A NS_RUNNING NS_CHAOS METRIC NS_ALWAYS_ON
SUSPENDED=""

# The scan does not care which backend holds a tenant's counters (control-table
# item or namespace annotations), so one store models both; state_read's own
# two branches are covered by the contract tests at the bottom.
ctl_audit() { :; }
state_read() {
  printf '%s %s %s\n' "${ITEM_COUNT[$1]:--}" "${ITEM_SINCE[$1]:--}" "${ITEM_RUNNING[$1]:--}"
}
record_activity() { ITEM_COUNT["$1"]="$2"; ITEM_SINCE["$1"]="$3"; }
record_running() { ITEM_RUNNING["$1"]="$2"; }
tenant_always_on() { [ "${NS_ALWAYS_ON[$1]:-no}" = "yes" ]; }
running_deployments() { echo "${NS_RUNNING[$1]:-0}"; }
tenant_has_chaos() { [ "${NS_CHAOS[$1]:-no}" = "yes" ]; }
# METRICS_UP=false models an unreachable metrics endpoint, which is distinct
# from a reachable one reporting no series for any tenant.
METRICS_UP=true
ingress_request_counts() {
  [ "${METRICS_UP}" = "true" ] || return 1
  for ns in "${!METRIC[@]}"; do echo "${ns} ${METRIC[$ns]}"; done
}
# SUSPEND_RC=1 models the real function's failure return: the scale-down was
# attempted and refused, so the tenant is still running afterwards.
SUSPEND_RC=0
suspend_tenant() {
  SUSPENDED="${SUSPENDED} $1"
  [ "${SUSPEND_RC}" -eq 0 ] || return "${SUSPEND_RC}"
  NS_RUNNING["$2"]=0
}

# tenant_namespaces is the real implementation (its exclusion list is under
# test), so kubectl is stubbed at the boundary instead.
kubectl() {
  [ "${1:-}" = "get" ] && [ "${2:-}" = "ns" ] || return 0
  for ns in "${!NS_RUNNING[@]}"; do echo "${ns}"; done
}

# Load the scan and namespace enumeration; every collaborator above is stubbed.
eval "$(sed -n '/^tenant_namespaces()/,/^}/p;/^suspend_idle_tenants()/,/^}/p' "${SCRIPT_DIR}/idle-suspend.sh")"
# Kept for the contract tests at the bottom, which run the real implementation.
real_src="$(sed -n '/^ingress_request_counts()/,/^}/p' "${SCRIPT_DIR}/idle-suspend.sh")"

reset_state() {
  unset ITEM_COUNT ITEM_SINCE ITEM_RUNNING NS_RUNNING NS_CHAOS METRIC NS_ALWAYS_ON
  declare -gA ITEM_COUNT=() ITEM_SINCE=() ITEM_RUNNING=() NS_RUNNING=() NS_CHAOS=() METRIC=() NS_ALWAYS_ON=()
  SUSPENDED=""
  SUSPEND_RC=0
}
# A tenant the reaper has already seen up. Without this the first pass just
# records the run state, which is not what most cases below are exercising.
seen_running() { ITEM_RUNNING["$1"]=1; }
NOW="$(date -u +%s)"
STALE=$(( NOW - 7200 ))   # idle well past the 3600s threshold
FRESH=$(( NOW - 60 ))

echo "idle-suspend decision logic"

# A metrics outage means traffic is unknown, not absent. Reading it as "nobody
# used anything" would scale every attendee's environment to zero at once.
reset_state
NS_RUNNING[otterworks-busy]=13
ITEM_COUNT[busy]=500; ITEM_SINCE[busy]=${STALE}
seen_running busy
METRICS_UP=false
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "suspends nothing when ingress metrics are unreachable" "${SUSPENDED# }" ""
check "  and leaves the stored counter untouched" "${ITEM_COUNT[busy]}" "500"
METRICS_UP=true

# The regression that made the whole feature inert: ingress-nginx exports no
# counter series for a namespace it has never routed to.
reset_state
NS_RUNNING[otterworks-never]=13; ITEM_COUNT[never]=0; ITEM_SINCE[never]=${STALE}
seen_running never
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "suspends a tenant that has no metric series at all" "${SUSPENDED# }" "never"

reset_state
NS_RUNNING[otterworks-busy]=13; METRIC[otterworks-busy]=500
ITEM_COUNT[busy]=100; ITEM_SINCE[busy]=${STALE}
seen_running busy
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "leaves a tenant serving traffic running" "${SUSPENDED# }" ""
check "  and resets its idle clock" "$([ "${ITEM_SINCE[busy]}" -ge "${NOW}" ] && echo reset)" "reset"

reset_state
NS_RUNNING[otterworks-quiet]=13; METRIC[otterworks-quiet]=100
ITEM_COUNT[quiet]=100; ITEM_SINCE[quiet]=${STALE}
seen_running quiet
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "suspends a tenant whose counter has not moved" "${SUSPENDED# }" "quiet"

reset_state
NS_RUNNING[otterworks-recent]=13; METRIC[otterworks-recent]=100
ITEM_COUNT[recent]=100; ITEM_SINCE[recent]=${FRESH}
seen_running recent
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "waits while the tenant is under the threshold" "${SUSPENDED# }" ""

# A restarted controller resets counters to zero. Treating the restart itself as
# traffic would keep every tenant awake forever on Spot capacity, so an idle
# tenant with no series after the restart is still suspended.
reset_state
NS_RUNNING[otterworks-restart]=13
ITEM_COUNT[restart]=900; ITEM_SINCE[restart]=${STALE}
seen_running restart
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "still suspends after an ingress counter reset" "${SUSPENDED# }" "restart"

# But a non-zero counter after a reset is traffic served since the restart,
# however small next to the pre-restart total.
reset_state
NS_RUNNING[otterworks-served]=13; METRIC[otterworks-served]=5
ITEM_COUNT[served]=900; ITEM_SINCE[served]=${STALE}
seen_running served
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "treats post-restart requests as activity" "${SUSPENDED# }" ""
check "  and restarts the idle clock" "$([ "${ITEM_SINCE[served]}" -ge "${NOW}" ] && echo reset)" "reset"

# A restart re-baselines to the real (low) count. Persisting the stale-high
# value instead would keep matching the reset branch after the tenant woke,
# so a tenant in active use would be suspended out from under its user.
reset_state
NS_RUNNING[otterworks-woken]=13; METRIC[otterworks-woken]=5
ITEM_COUNT[woken]=900; ITEM_SINCE[woken]=${STALE}
seen_running woken
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "  and persists the real count, not the stale one" "${ITEM_COUNT[woken]}" "5"
# Woken and now serving traffic: must be seen as active, not re-suspended.
NS_RUNNING[otterworks-woken]=13; METRIC[otterworks-woken]=60; SUSPENDED=""
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "  so a woken, busy tenant is not immediately re-suspended" "${SUSPENDED# }" ""

# The full check-out story, which is what makes suspension safe to leave on:
# a tenant sleeps past the idle window, someone checks it out, and the wake
# path touches only Kubernetes. If the reaper did not treat the tenant being up
# again as activity, the stale clock would scale it straight back down and the
# attendee would find a dead environment minutes after opening it.
reset_state
NS_RUNNING[otterworks-nap]=0
ITEM_COUNT[nap]=100; ITEM_SINCE[nap]=${STALE}
seen_running nap
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "records a sleeping tenant as scaled down" "${ITEM_RUNNING[nap]}" "0"

NS_RUNNING[otterworks-nap]=13     # checked out; no traffic yet
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "  does not re-suspend it the moment it is woken" "${SUSPENDED# }" ""
check "  restarts the idle clock on wake" "$([ "${ITEM_SINCE[nap]}" -ge "${NOW}" ] && echo reset)" "reset"

# ...and it must still be suspendable once it goes idle again, or the wake
# exemption would simply disable the cost control.
ITEM_SINCE[nap]=${STALE}
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "  and is suspended again once it goes idle" "${SUSPENDED# }" "nap"

# A refused scale-down must not be recorded as a suspension. Writing
# was_running=0 for a tenant that is still up makes the next pass read it as a
# wake, reset the idle clock and wait the whole window again -- so a tenant
# whose scale-down keeps failing would never be suspended, and the cost control
# would be off for it with nothing but a warning line to say so.
reset_state
NS_RUNNING[otterworks-stuck]=13; METRIC[otterworks-stuck]=100
ITEM_COUNT[stuck]=100; ITEM_SINCE[stuck]=${STALE}
seen_running stuck
SUSPEND_RC=1
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "tried to suspend the tenant whose scale-down fails" "${SUSPENDED# }" "stuck"
check "  but does not record it as scaled down" "${ITEM_RUNNING[stuck]}" "1"
check "  and leaves its idle clock alone" "${ITEM_SINCE[stuck]}" "${STALE}"

# ...so the next pass retries the suspend instead of treating it as a wake.
SUSPENDED=""
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "  and retries on the next pass" "${SUSPENDED# }" "stuck"
SUSPEND_RC=0
SUSPENDED=""
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "  until it succeeds, which is then recorded" "${ITEM_RUNNING[stuck]}" "0"

# Exemption is opt-in and explicit: the label is what deploy-tenant.sh
# --always-on writes, and it is the only thing that keeps an idle tenant up.
reset_state
NS_RUNNING[otterworks-standing]=13; METRIC[otterworks-standing]=100
ITEM_COUNT[standing]=100; ITEM_SINCE[standing]=${STALE}; NS_ALWAYS_ON[otterworks-standing]=yes
seen_running standing
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "never suspends an always-on tenant" "${SUSPENDED# }" ""

# ...and the same tenant without the label is suspended, so the flag is doing
# the work rather than something incidental about how it was deployed. This is
# the regression that mattered: script-deployed tenants had no control-table
# item, the scan skipped every one of them, and they were all silently exempt.
NS_ALWAYS_ON[otterworks-standing]=no
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "  suspends it once the label is gone" "${SUSPENDED# }" "standing"

reset_state
NS_RUNNING[otterworks-lab]=13; METRIC[otterworks-lab]=100
ITEM_COUNT[lab]=100; ITEM_SINCE[lab]=${STALE}; NS_CHAOS[otterworks-lab]=yes
seen_running lab
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
seen_running platform
ITEM_COUNT[system]=0; ITEM_SINCE[system]=${STALE}
seen_running system
IDLE_AFTER_SECONDS=3600 suspend_idle_tenants >/dev/null 2>&1
check "never suspends the platform's own namespaces" "${SUSPENDED# }" ""

# ---- contract of the real ingress_request_counts -----------------------------
# The scan cases above stub this function, and that stub is precisely what hid a
# pipefail bug: it returned success on empty output while the real pipeline
# returned failure, so "no traffic anywhere" read as a metrics outage. Exercise
# the real implementation against real metrics bodies.
eval "${real_src/ingress_request_counts()/real_counts()}"

# shellcheck disable=SC2034  # both are read by real_counts from the sourced script
INGRESS_METRICS_URL="http://ingress-metrics.test/metrics"
# shellcheck disable=SC2034
INGRESS_NAMESPACE="ingress-nginx"
CURL_BODY=""; CURL_RC=0
curl() { [ "${CURL_RC}" -eq 0 ] || return "${CURL_RC}"; printf '%s' "${CURL_BODY}"; }

CURL_BODY='nginx_ingress_controller_requests{namespace="otterworks-a",path="/"} 12
nginx_ingress_controller_requests{namespace="otterworks-a",path="/api"} 8
nginx_ingress_controller_requests{namespace="otterworks-b",path="/"} 3
some_other_metric{namespace="otterworks-a"} 999'
out="$(real_counts)"; rc=$?
check "sums every series for a namespace" "$(printf '%s\n' "${out}" | sort | tr '\n' ',')" "otterworks-a 20,otterworks-b 3,"
check "  and succeeds" "${rc}" "0"

# A controller that has proxied nothing yet exports no request series at all.
# That is zero traffic, not an outage -- the distinction the whole scan rests on.
CURL_BODY='# HELP nginx_ingress_controller_build_info Build info
nginx_ingress_controller_build_info{version="1.11"} 1'
out="$(real_counts)"; rc=$?
check "reports no traffic when the body carries no request series" "${out}" ""
check "  without claiming the scrape failed" "${rc}" "0"

# A genuine outage: the endpoint is unreachable and there is no controller pod
# to fall back to (the kubectl stub returns nothing for a pod lookup).
CURL_RC=7; CURL_BODY=""
real_counts >/dev/null 2>&1
check "still reports failure when the scrape cannot be made" "$?" "1"

# ---- contract of the real state backend --------------------------------------
# Which store a tenant's counters live in is invisible to the scan, and getting
# it wrong is silent in the worst way: writes that go nowhere mean the tenant
# never accumulates idle time and is never suspended. Run the real functions
# against both backends. Evaluated last, replacing the stubs above.
eval "$(sed -n '/^idle_ns()/,/^}/p;/^tenant_has_item()/,/^}/p;/^state_read()/,/^}/p;/^record_activity()/,/^}/p;/^record_running()/,/^}/p' "${SCRIPT_DIR}/idle-suspend.sh")"
# shellcheck disable=SC2034  # read by the real tenant_has_item / state_read
declare -A TENANT_HAS_ITEM=() NS_ANNOT=()
# These two record writes from inside `out="$(...)"`, i.e. from a subshell, so
# they land in files rather than variables the parent would never see.
WRITES="$(mktemp -d)"; trap 'rm -rf "${WRITES}"' EXIT
HAS_ITEM=no
# shellcheck disable=SC2034  # both are read by the real record_* implementations
CONTROL_TABLE="otterworks-demo-control"
# shellcheck disable=SC2034
AWS_REGION="us-east-1"
idle_warn() { echo "WARN: $*" >&2; }
ctl_tenant_exists() { [ "${HAS_ITEM}" = "yes" ]; }
ctl_get() { jq -n '{Item:{req_count:{N:"7"},idle_since:{N:"123"},was_running:{N:"1"}}}'; }
aws() { echo "$2" >> "${WRITES}/aws"; printf '{}'; }
kubectl() {
  case "$*" in
    *annotate*)         for a in "$@"; do case "${a}" in *=*) echo "${a}" >> "${WRITES}/annotate" ;; esac; done ;;
    *demo/req-count*)   printf '%s' "${NS_ANNOT[req-count]:-}" ;;
    *demo/idle-since*)  printf '%s' "${NS_ANNOT[idle-since]:-}" ;;
    *demo/was-running*) printf '%s' "${NS_ANNOT[was-running]:-}" ;;
  esac
  return 0
}
wrote() { [ -f "${WRITES}/$1" ] || return 0; tr '\n' ' ' < "${WRITES}/$1" | sed 's/ $//'; }
# TENANT_HAS_ITEM is the real tenant_has_item's cache; clearing it is what makes
# a case's HAS_ITEM setting take effect.
reset_backend() {
  # shellcheck disable=SC2034  # the cache is read by the real tenant_has_item
  TENANT_HAS_ITEM=(); NS_ANNOT=(); rm -f "${WRITES}/aws" "${WRITES}/annotate"
}

reset_backend; HAS_ITEM=yes
check "reads a dashboard tenant's counters from its control item" "$(state_read dash)" "7 123 1"
record_activity dash 42 555; record_running dash 0
check "  and writes them back to DynamoDB" "$(wrote aws)" "update-item update-item"
check "  never touching the namespace" "$(wrote annotate)" ""

# A tenant deployed straight from the script has no item at all. Before the
# namespace fallback existed this case was simply skipped by the scan.
reset_backend; HAS_ITEM=no
check "reports an unmeasured script tenant as unset, not zero" "$(state_read solo)" "- - -"
record_activity solo 42 555
record_running solo 0
check "  records its counters on the namespace" "$(wrote annotate)" \
  "demo/req-count=42 demo/idle-since=555 demo/was-running=0"
check "  without writing to the control table" "$(wrote aws)" ""

reset_backend; HAS_ITEM=no
NS_ANNOT[req-count]=42; NS_ANNOT[idle-since]=555; NS_ANNOT[was-running]=1
check "  and reads them back on the next pass" "$(state_read solo)" "42 555 1"

echo "${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
