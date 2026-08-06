#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# OtterWorks Demo Platform — idle tenant suspend (scale to zero)
#
# The economics of 100 tenants only work if a provisioned tenant that nobody is
# using costs nothing. A full tenant reserves ~1.5 vCPU / 3.5GiB; 100 of those
# is ~$3,600/month of nodes. Suspended, a tenant costs only its database rows
# and its DNS record, so spend tracks *active* tenants rather than provisioned
# ones -- roughly a 10x reduction at realistic workshop utilization.
#
# Idleness is measured from real HTTP traffic, not from a timer: ingress-nginx
# exports a per-namespace request counter on its metrics port, and every tenant
# is reached exclusively through that controller. Each run walks every tenant
# namespace and compares its counter against the value the last run stored:
#
#   labelled demo/always-on  -> exempt; never suspended, and scaled back up if
#                               found asleep (deploy-tenant.sh --always-on), for
#                               standing environments someone must be able to
#                               open cold
#   counter increased        -> tenant is in use; record it and reset the clock
#   counter unchanged/absent -> tenant took zero requests since the last run
#   counter decreased to >0  -> controller restarted, but has served this tenant
#                               since; that is real traffic, reset the clock
#   counter decreased to 0   -> controller restarted and served nothing; keep
#                               the clock, or a cycling controller would keep
#                               idle tenants awake forever
#   scaled up since last run -> just woken; reset the clock (see was_running)
#   idle for IDLE_AFTER      -> scale every Deployment in the namespace to zero
#
# Suspending preserves the namespace, config, secrets and the tenant's database
# (RDS is external), so waking is `tenant-scale.sh <id> up` (which the dashboard
# calls on check-out) and takes seconds.
#
# It does NOT preserve the tenant's in-cluster Redis or MeiliSearch: both run
# without persistence, so scaling them to zero discards sessions, the search
# index (rebuilt on use) and any injected chaos flag. Because a cleared chaos
# flag would silently un-plant the bug an attendee is hunting, a tenant with an
# active scenario is never auto-suspended -- see tenant_has_chaos below.
#
# Sourced by reaper.sh; also runnable standalone.
# ------------------------------------------------------------------------------
set -uo pipefail

CONTROL_TABLE="${CONTROL_TABLE:-otterworks-demo-control}"
AWS_REGION="${AWS_REGION:-us-east-1}"
INGRESS_NAMESPACE="${INGRESS_NAMESPACE:-ingress-nginx}"
# Metrics endpoint of the shared ingress controller. Exposed by the controller
# itself, so this needs no Prometheus deployment.
INGRESS_METRICS_URL="${INGRESS_METRICS_URL:-http://ingress-nginx-controller-metrics.${INGRESS_NAMESPACE}.svc:10254/metrics}"
# How long a tenant must take zero requests before it is suspended.
IDLE_AFTER_SECONDS="${IDLE_AFTER_SECONDS:-3600}"

idle_log()  { echo "[idle-suspend] $*"; }
idle_warn() { echo "[idle-suspend] WARN: $*" >&2; }

# Total ingress requests per tenant namespace, as "<namespace> <count>" lines.
# Uses the reaper pod's own network; falls back to exec-ing the controller pod
# when the metrics Service is not exposed.
#
# Returns non-zero if the scrape itself failed. That is NOT the same as a scrape
# that succeeded and contained no tenant series: the first means traffic is
# unknown, the second means there was none. Conflating them would let a metrics
# outage read as "every tenant is idle" and suspend the whole workshop at once.
ingress_request_counts() {
  local raw=""
  raw="$(curl -sf --max-time 10 "${INGRESS_METRICS_URL}" 2>/dev/null)"
  if [ -z "${raw}" ]; then
    local pod
    pod="$(kubectl -n "${INGRESS_NAMESPACE}" get pod \
             -l app.kubernetes.io/component=controller \
             -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)"
    [ -n "${pod}" ] || return 1
    raw="$(kubectl -n "${INGRESS_NAMESPACE}" exec "${pod}" -- \
             curl -sf --max-time 10 http://127.0.0.1:10254/metrics 2>/dev/null)"
  fi
  [ -n "${raw}" ] || return 1

  # nginx_ingress_controller_requests{...,namespace="otterworks-x",...} 12345
  #
  # `|| true` because grep exits 1 when the body carries no request series at
  # all, and under `pipefail` that would surface as a scrape failure and skip
  # the whole scan -- the opposite of this function's contract. The scrape has
  # already been validated above; from here an empty result means no traffic.
  printf '%s\n' "${raw}" \
    | grep '^nginx_ingress_controller_requests{' \
    | sed -n 's/.*namespace="\([^"]*\)".*} \([0-9.e+]*\)$/\1 \2/p' \
    | awk '{ total[$1] += $2 } END { for (ns in total) printf "%s %d\n", ns, total[ns] }' \
    || true
}

# The namespace of a tenant id -- the inverse of tenant_namespaces below. Kept
# local rather than taken from scripts/lib/tenant-common.sh so the scan still
# runs standalone with only control-common.sh sourced. The ids it is called with
# come from stripping this same prefix, so they are already sanitised.
idle_ns() { printf 'otterworks-%s' "$1"; }

# Is this tenant exempt from suspension? Set by `deploy-tenant.sh --always-on`.
# A label rather than an inference: exemption costs ~1.5 vCPU and ~15 pod IPs
# for as long as the tenant exists, so it should be something somebody chose.
#
# Fails closed, like tenant_is_persistent in reaper.sh, and for a sharper reason:
# an always-on tenant has no control item, so the dashboard cannot wake it and a
# suspension stands until somebody runs tenant-scale.sh. One throttled lookup out
# of ~95 must not be what takes a standing environment down. stdout and stderr
# are kept apart so a Warning header on a successful read is not compared to
# "true" along with the label.
#
# true | false | unknown, rather than a bare exit status, because the two things
# the caller does with the answer need different amounts of certainty. Not
# suspending is safe under doubt -- it costs an hour of compute and the next pass
# retries. Scaling a tenant *up* on the same doubt is not: a single throttled
# label read would wake an ordinary tenant that was correctly asleep, and reset
# its clock for another full idle window. Only a label read as "true" wakes
# anything.
tenant_always_on() {
  local out err errfile rc
  errfile="$(mktemp)"
  out="$(kubectl get ns "$1" -o jsonpath='{.metadata.labels.demo/always-on}' 2>"${errfile}")"; rc=$?
  err="$(cat "${errfile}")"; rm -f "${errfile}"
  if [ "${rc}" -eq 0 ]; then
    if [ "${out}" = "true" ]; then printf 'true'; else printf 'false'; fi
    return 0
  fi
  # The namespace is gone: there is nothing left to suspend either way.
  case "${err}" in *NotFound*|*"not found"*) printf 'false'; return 0 ;; esac
  idle_warn "cannot read demo/always-on on $1 (${err//$'\n'/ }); leaving it as it is this pass"
  printf 'unknown'
}

# Where a tenant's idle bookkeeping lives. The dashboard's tenants have a
# control-table item; tenants deployed straight from deploy-tenant.sh do not,
# and the scan used to skip those entirely -- which quietly made every
# script-deployed tenant always-on, whether or not anyone wanted it. They keep
# their counters on the namespace instead, so the same decisions apply to both.
#
# Sets TENANT_HAS_ITEM[id] to yes | no | unknown, and keeps the item it read in
# TENANT_ITEM[id]: this is a GetItem on the same key state_read wants, so the
# attributes come back with the answer and asking a second time would be a second
# request per tenant per pass against the table whose throttling this code exists
# to notice -- and a request that can fail on its own, one call after the check.
#
# Not ctl_tenant_exists: it reads through ctl_get, which turns any API failure
# into '{}' and so answers "no item" for a throttled, unauthorised or unreachable
# table. That answer sends every read and write to the namespace, leaving a
# dashboard tenant's real counters untouched -- a scan that suspends nothing while
# reporting nothing wrong. A failure has to stay a failure.
tenant_item_backend() {
  local id="$1" out err errfile rc
  # stdout is JSON this parses, so stderr cannot share it: the CLI writes there
  # on plenty of successful calls (urllib3/botocore deprecation notices, config
  # warnings), and one line of it makes jq fail and the answer come back "no" --
  # the misrouting this function exists to prevent, arriving by another door.
  errfile="$(mktemp)"
  out="$(aws dynamodb get-item \
           --table-name "${CONTROL_TABLE}" --region "${AWS_REGION}" \
           --key "$(jq -n --arg pk "TENANT#${id}" '{PK:{S:$pk},SK:{S:"META"}}')" \
           --output json 2>"${errfile}")"; rc=$?
  err="$(cat "${errfile}")"; rm -f "${errfile}"
  if [ "${rc}" -ne 0 ]; then
    idle_warn "control table lookup failed for ${id}: ${err//$'\n'/ }"
    TENANT_HAS_ITEM[$id]=unknown
    return
  fi
  if [ -n "$(printf '%s' "${out}" | jq -r '.Item.PK.S // empty' 2>/dev/null)" ]; then
    TENANT_HAS_ITEM[$id]=yes
    TENANT_ITEM[$id]="${out}"
  else
    TENANT_HAS_ITEM[$id]=no
  fi
}

declare -A TENANT_HAS_ITEM=()
declare -A TENANT_ITEM=()
tenant_has_item() {
  local id="$1"
  # Not a command substitution: the item is cached alongside the answer, and a
  # subshell would drop it.
  [ -n "${TENANT_HAS_ITEM[$id]+x}" ] || tenant_item_backend "${id}"
  [ "${TENANT_HAS_ITEM[$id]}" = "yes" ]
}

# "<req_count> <idle_since> <was_running>", each "-" when unset, or "? ? ?" when
# the store could not be read at all. Callers read it with `read -r`, so the
# fields cannot be empty.
state_read() {
  local id="$1" ns item c s r out err errfile rc
  ns="$(idle_ns "${id}")"
  # The item the backend probe already read, not a fresh ctl_get: that second
  # read is one more chance to fail, and ctl_get answers a failure with '{}' --
  # unset counters, which the scan treats as a first observation and starts the
  # idle clock over, every pass, for as long as the table is unhappy.
  if tenant_has_item "${id}"; then
    item="${TENANT_ITEM[$id]:-}"
    c="$(printf '%s' "${item}" | jq -r '.Item.req_count.N // empty')"
    s="$(printf '%s' "${item}" | jq -r '.Item.idle_since.N // empty')"
    r="$(printf '%s' "${item}" | jq -r '.Item.was_running.N // empty')"
  else
    # One call for all three: the scan reads them per tenant per pass, so over
    # ~95 namespaces the split version was ~285 requests an hour against the
    # same API server the always-on label read has to be able to reach -- and a
    # read it cannot reach is a tenant this pass leaves alone.
    #
    # The leading '.' on each field is what keeps them aligned: an unset
    # annotation prints nothing, and `read` would collapse the run of spaces
    # and shift the remaining values into the wrong variables.
    #
    # Discarding stderr and reading the empty result would be the same three
    # blanks an unannotated namespace gives, i.e. a first observation -- so a
    # throttled or unauthorised API server restarts the idle clock every pass and
    # silently switches suspension off for every script-deployed tenant, with
    # nothing in the log. Like the two lookups above: a failure stays a failure.
    errfile="$(mktemp)"
    out="$(kubectl get ns "${ns}" -o jsonpath='.{.metadata.annotations.demo/req-count} .{.metadata.annotations.demo/idle-since} .{.metadata.annotations.demo/was-running}' 2>"${errfile}")"; rc=$?
    err="$(cat "${errfile}")"; rm -f "${errfile}"
    if [ "${rc}" -ne 0 ]; then
      # A namespace that is gone has no state and nothing to suspend; the caller
      # finds no Deployments either way.
      case "${err}" in
        *NotFound*|*"not found"*) : ;;
        *) idle_warn "cannot read idle state on ${ns} (${err//$'\n'/ }); leaving it as it is this pass"
           printf '? ? ?\n'; return 0 ;;
      esac
    fi
    read -r c s r <<< "${out}"
    c="${c#.}"; s="${s#.}"; r="${r#.}"
  fi
  printf '%s %s %s\n' "${c:--}" "${s:--}" "${r:--}"
}

# Persist the observed counter and the time it was first seen at this value.
# Key attributes are PK/SK, matching control-common.sh -- DynamoDB rejects an
# update whose key names differ from the table schema.
record_activity() {
  local id="$1" count="$2" since="$3" out
  if ! tenant_has_item "${id}"; then
    if ! out="$(kubectl annotate ns "$(idle_ns "${id}")" --overwrite \
                  "demo/req-count=${count}" "demo/idle-since=${since}" 2>&1)"; then
      idle_warn "could not record activity for ${id} on its namespace: ${out}"
      return 1
    fi
    return 0
  fi
  # Report the AWS error rather than discarding it. A silently-dropped write
  # here disables suspension entirely while looking healthy, because the next
  # scan reads no previous counter and restarts the idle clock forever.
  if ! out="$(aws dynamodb update-item --table-name "${CONTROL_TABLE}" --region "${AWS_REGION}" \
                --key "$(jq -n --arg id "TENANT#${id}" '{PK:{S:$id}, SK:{S:"META"}}')" \
                --update-expression "SET req_count = :c, idle_since = :s" \
                --expression-attribute-values \
                  "$(jq -n --arg c "${count}" --arg s "${since}" '{":c":{N:$c},":s":{N:$s}}')" 2>&1)"; then
    idle_warn "could not record activity for ${id}: ${out}"
    return 1
  fi
}

# Remember whether the tenant had any replicas up at the end of a pass. This is
# what makes a wake detectable: nothing on the wake path (tenant-scale.sh, the
# dashboard, a manual kubectl scale) writes to the control table, so the
# transition 0 -> running is the only evidence the reaper gets.
record_running() {
  local id="$1" running="$2" out
  if ! tenant_has_item "${id}"; then
    if ! out="$(kubectl annotate ns "$(idle_ns "${id}")" --overwrite \
                  "demo/was-running=${running}" 2>&1)"; then
      idle_warn "could not record run state for ${id} on its namespace: ${out}"
      return 1
    fi
    return 0
  fi
  if ! out="$(aws dynamodb update-item --table-name "${CONTROL_TABLE}" --region "${AWS_REGION}" \
                --key "$(jq -n --arg id "TENANT#${id}" '{PK:{S:$id}, SK:{S:"META"}}')" \
                --update-expression "SET was_running = :r" \
                --expression-attribute-values \
                  "$(jq -n --arg r "${running}" '{":r":{N:$r}}')" 2>&1)"; then
    idle_warn "could not record run state for ${id}: ${out}"
    return 1
  fi
}

# Number of Deployments currently running at least one replica.
running_deployments() {
  kubectl -n "$1" get deploy -o jsonpath='{range .items[*]}{.spec.replicas}{"\n"}{end}' 2>/dev/null \
    | awk '$1 > 0 { n++ } END { print n + 0 }'
}

# Does the tenant have an injected chaos scenario running? Such a tenant is a
# lab in progress: its Redis holds the bug, and Redis has no persistence, so
# suspending would quietly un-inject the scenario the attendee is debugging.
tenant_has_chaos() {
  local ns="$1"
  # Same access path inject-bug.sh uses, so the two agree on what "injected" means.
  kubectl -n "${ns}" exec deploy/redis -- redis-cli --scan --pattern 'chaos:*' 2>/dev/null | grep -q .
}

# Returns non-zero if the tenant is still running afterwards. The caller records
# the suspension only on success: writing was_running=0 for a tenant that never
# scaled down would make the next pass read it as a wake, reset the idle clock,
# and start the wait over -- so a persistently failing scale-down would keep the
# tenant running forever while the platform believed it had been suspended.
suspend_tenant() {
  local id="$1" ns="$2"
  idle_log "suspending ${id}: no ingress requests for >= ${IDLE_AFTER_SECONDS}s"
  if kubectl -n "${ns}" scale deployment --all --replicas=0 >/dev/null 2>&1; then
    ctl_audit "${id}" "suspend" "idle for ${IDLE_AFTER_SECONDS}s" 2>/dev/null || true
    return 0
  fi
  idle_warn "failed to scale down ${ns}; leaving its idle clock alone so the next pass retries"
  return 1
}

# An always-on tenant found at zero replicas. The label is a promise that the
# URL answers, and zero replicas is a 503 for as long as it lasts; the tenant
# gets there by having been suspended before the label was applied, or by a
# manual tenant-scale.sh down. Nothing else brings it back -- a script-deployed
# tenant has no control-table item, so the dashboard's check-out cannot reach it
# -- so the scan that would otherwise only leave it asleep wakes it instead. To
# take one down deliberately, drop the label first (redeploy without
# --always-on), or this puts it straight back up on the next pass.
#
# A namespace with no Deployments at all -- freshly created, mid-deploy, half
# torn down -- is left alone: `scale --all` over an empty set succeeds, and this
# would then claim to wake something that does not exist, every pass, forever.
resume_tenant() {
  local id="$1" ns="$2" deploys
  deploys="$(kubectl -n "${ns}" get deploy -o name 2>/dev/null | awk 'END { print NR + 0 }')"
  [ "${deploys}" -gt 0 ] || return 1
  idle_log "waking ${id}: always-on, but found scaled to zero"
  if kubectl -n "${ns}" scale deployment --all --replicas=1 >/dev/null 2>&1; then
    ctl_audit "${id}" "resume" "always-on tenant found suspended" 2>/dev/null || true
    return 0
  fi
  idle_warn "failed to scale up ${ns}; leaving it for the next pass"
  return 1
}

# Every tenant namespace that currently exists, as "<id> <namespace>" lines.
# The scan is driven from this list rather than from the metrics, because
# ingress-nginx only exports a counter series for a namespace once it has served
# a request since the controller started. A tenant nobody ever opened -- exactly
# the one worth suspending -- has no series at all, and a controller restart
# (routine on Spot) drops the series for every idle tenant.
tenant_namespaces() {
  kubectl get ns -l demo/tenant -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null \
    | while read -r ns; do
        [ -n "${ns}" ] || continue
        case "${ns}" in
          otterworks-platform|otterworks-system) continue ;;
          otterworks-*) printf '%s %s\n' "${ns#otterworks-}" "${ns}" ;;
        esac
      done
}

suspend_idle_tenants() {
  idle_log "idle scan starting (threshold=${IDLE_AFTER_SECONDS}s)"
  local counts now ns id count prev since running was_running always_on
  # Traffic is the only evidence of use, so without it there is nothing to
  # decide on. Skipping the pass delays suspension until the next run; guessing
  # scales every attendee's environment to zero mid-workshop.
  if ! counts="$(ingress_request_counts)"; then
    idle_warn "skipping idle scan: could not read ingress metrics"
    return 1
  fi
  now="$(date -u +%s)"

  while read -r id ns; do
    [ -n "${id}" ] || continue
    # No counter series means the controller has routed nothing to this tenant,
    # which is zero traffic -- not a reason to skip it.
    count="$(printf '%s\n' "${counts}" | awk -v n="${ns}" '$1 == n { print $2; exit }')"
    [ -n "${count}" ] || count=0

    # Resolve the backend here, in this shell: state_read runs in a command
    # substitution, so a lookup it caches is thrown away with the subshell and
    # the record_* calls below would repeat it.
    tenant_has_item "${id}" || true
    if [ "${TENANT_HAS_ITEM[$id]:-}" = "unknown" ]; then
      # Guessing costs a tenant either way: to the namespace, a dashboard tenant's
      # counters are lost and it never suspends; to the control table, a script
      # tenant's are written where nothing reads them. Leave it for the next pass.
      idle_warn "skipping ${id}: cannot tell which store its idle state lives in"
      continue
    fi
    # Read after the backend resolution, not before it: a tenant skipped just
    # above never uses the answer, and the pass that skips is the degraded one.
    #
    # Exempt tenants are measured like everyone else and only spared the
    # suspension itself. Skipping them outright would freeze req_count at
    # whatever the last non-exempt pass stored, and the pass after the label is
    # dropped would then compare live traffic against an hours-old baseline --
    # an ingress restart in between reads as "idle since this morning" and
    # suspends a tenant somebody is using. (idle_since does sit still while an
    # exempt tenant is genuinely idle: no branch writes when the counter has not
    # moved, which is the same "idle since then" a non-exempt tenant records.
    # Traffic, a wake, or a counter reset all update it as usual.)
    always_on="$(tenant_always_on "${ns}")"

    read -r prev since was_running <<< "$(state_read "${id}")"
    # The store answered with an error rather than with counters (state_read has
    # already said so). Its blanks would read as a first observation, so acting on
    # them would restart the clock -- and on the next pass, and the one after.
    [ "${prev}" != "?" ] || continue
    [ "${prev}" != "-" ] || prev=""
    [ "${since}" != "-" ] || since=""
    [ "${was_running}" != "-" ] || was_running=""

    running="$(running_deployments "${ns}")"
    if [ "${running}" -eq 0 ]; then
      # Only a label positively read as true: 'unknown' leaves it asleep.
      if [ "${always_on}" = "true" ] && resume_tenant "${id}" "${ns}"; then
        # Up again, and its clock starts now: the counters date from before it
        # was suspended, and an hour-old baseline would read as idle.
        record_activity "${id}" "${count}" "${now}"
        record_running "${id}" 1
        continue
      fi
      # Asleep: nothing to suspend. Record that, so the tenant coming back is
      # recognisable as a wake on a later pass.
      [ "${was_running}" = "0" ] || record_running "${id}" 0
      continue
    fi

    # Waking is just `kubectl scale` -- tenant-scale.sh, the dashboard check-out
    # and a manual scale-up all leave the control table untouched, so the idle
    # clock still reads from before the tenant was scaled down and every one of
    # those paths would otherwise be undone by the next pass. Treat the tenant
    # running again as the activity that the wake itself represents.
    if [ "${was_running}" = "0" ]; then
      idle_log "${id}: running again after being scaled down; restarting the idle clock"
      record_activity "${id}" "${count}" "${now}"
      record_running "${id}" 1
      continue
    fi
    [ "${was_running}" = "1" ] || record_running "${id}" 1

    if [ -z "${prev}" ] || [ -z "${since}" ]; then
      # First observation: start the clock, decide on the next pass.
      record_activity "${id}" "${count}" "${now}"
      continue
    fi

    if [ "${count}" -gt "${prev}" ]; then
      # Requests served since the last run: tenant is in use, reset the clock.
      record_activity "${id}" "${count}" "${now}"
      continue
    fi

    if [ "${count}" -lt "${prev}" ]; then
      # Counters only ever increase, so a drop means the controller restarted.
      if [ "${count}" -gt 0 ]; then
        # It has already served this tenant since coming back, which is real
        # traffic in the recent past however high the pre-restart total was.
        record_activity "${id}" "${count}" "${now}"
        continue
      fi
      # Nothing served since the restart. Re-baseline but keep the existing idle
      # clock: crediting a restart alone as activity would let a cycling
      # controller keep genuinely idle tenants awake forever.
      idle_log "${id}: ingress counter reset (${prev} -> ${count}); keeping idle clock"
      record_activity "${id}" "${count}" "${since}"
    fi

    # Anything but a definite "false" keeps it up: an unreadable label is the one
    # case where suspending is the irreversible mistake, since an always-on tenant
    # has no control item for the dashboard to wake it from.
    if [ "${always_on}" != "false" ]; then
      idle_log "${id}: demo/always-on=${always_on}, leaving it running (idle $(( now - since ))s)"
      continue
    fi

    if [ $(( now - since )) -lt "${IDLE_AFTER_SECONDS}" ]; then
      idle_log "${id} idle for $(( now - since ))s (threshold ${IDLE_AFTER_SECONDS}s)"
      continue
    fi

    if tenant_has_chaos "${ns}"; then
      idle_log "${id} is idle but has an injected scenario; leaving it running"
      continue
    fi

    suspend_tenant "${id}" "${ns}" || continue
    record_activity "${id}" "${count}" "${now}"
    record_running "${id}" 0
  done <<< "$(tenant_namespaces)"

  idle_log "idle scan complete."
}

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
  # shellcheck source=/dev/null
  source "${REPO_ROOT}/demo-platform/lib/control-common.sh"
  suspend_idle_tenants
fi
