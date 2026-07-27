#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# OtterWorks Demo Platform — idle tenant suspend (scale to zero)
#
# The economics of 100 tenants only work if a provisioned tenant that nobody is
# using costs nothing. A full tenant reserves ~1.5 vCPU / 3.5GiB; 100 of those
# is ~$3,600/month of nodes. Suspended, a tenant costs only its database rows
# and its DNS record, so spend tracks *active* tenants rather than provisioned
# ones -- roughly a 10x reduction at realistic workshop utilisation.
#
# Idleness is measured from real HTTP traffic, not from a timer: ingress-nginx
# exports a per-namespace request counter on its metrics port, and every tenant
# is reached exclusively through that controller. Each run compares the current
# counter against the value stored on the tenant's control-table item:
#
#   counter moved            -> tenant is in use; record the new value, reset idle
#   counter unchanged        -> tenant took zero requests since the last run
#   unchanged for IDLE_AFTER -> scale every Deployment in the namespace to zero
#
# Suspending preserves the namespace, config, secrets, Redis/MeiliSearch data
# and the tenant's database, so waking is `tenant-scale.sh <id> up` (which the
# dashboard calls on check-out) and takes seconds.
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
ingress_request_counts() {
  local raw=""
  raw="$(curl -sf --max-time 10 "${INGRESS_METRICS_URL}" 2>/dev/null)"
  if [ -z "${raw}" ]; then
    local pod
    pod="$(kubectl -n "${INGRESS_NAMESPACE}" get pod \
             -l app.kubernetes.io/component=controller \
             -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)"
    [ -n "${pod}" ] || return 0
    raw="$(kubectl -n "${INGRESS_NAMESPACE}" exec "${pod}" -- \
             curl -sf --max-time 10 http://127.0.0.1:10254/metrics 2>/dev/null)"
  fi
  [ -n "${raw}" ] || return 0

  # nginx_ingress_controller_requests{...,namespace="otterworks-x",...} 12345
  printf '%s\n' "${raw}" \
    | grep '^nginx_ingress_controller_requests{' \
    | sed -n 's/.*namespace="\([^"]*\)".*} \([0-9.e+]*\)$/\1 \2/p' \
    | awk '{ total[$1] += $2 } END { for (ns in total) printf "%s %d\n", ns, total[ns] }'
}

# Persist the observed counter and the time it was first seen at this value.
record_activity() {
  local id="$1" count="$2" since="$3"
  aws dynamodb update-item --table-name "${CONTROL_TABLE}" --region "${AWS_REGION}" \
    --key "$(jq -n --arg id "TENANT#${id}" '{pk:{S:$id}, sk:{S:"META"}}')" \
    --update-expression "SET req_count = :c, idle_since = :s" \
    --expression-attribute-values \
      "$(jq -n --arg c "${count}" --arg s "${since}" '{":c":{N:$c},":s":{N:$s}}')" \
    >/dev/null 2>&1 || idle_warn "could not record activity for ${id}"
}

# Number of Deployments currently running at least one replica.
running_deployments() {
  kubectl -n "$1" get deploy -o jsonpath='{range .items[*]}{.spec.replicas}{"\n"}{end}' 2>/dev/null \
    | awk '$1 > 0 { n++ } END { print n + 0 }'
}

suspend_tenant() {
  local id="$1" ns="$2"
  idle_log "suspending ${id}: no ingress requests for >= ${IDLE_AFTER_SECONDS}s"
  if kubectl -n "${ns}" scale deployment --all --replicas=0 >/dev/null 2>&1; then
    ctl_audit "suspend" "${id}" "idle for ${IDLE_AFTER_SECONDS}s" 2>/dev/null || true
  else
    idle_warn "failed to scale down ${ns}"
  fi
}

suspend_idle_tenants() {
  idle_log "idle scan starting (threshold=${IDLE_AFTER_SECONDS}s)"
  local counts now ns id count prev since running
  counts="$(ingress_request_counts)"
  if [ -z "${counts}" ]; then
    idle_warn "no ingress metrics available; skipping idle scan"
    return 0
  fi
  now="$(date -u +%s)"

  while read -r ns count; do
    [ -n "${ns}" ] || continue
    case "${ns}" in
      otterworks-*) ;;
      *) continue ;;
    esac
    case "${ns}" in otterworks-platform|otterworks-system) continue ;; esac
    id="${ns#otterworks-}"
    ctl_tenant_exists "${id}" || continue

    # Nothing to suspend if the tenant is already asleep.
    running="$(running_deployments "${ns}")"
    [ "${running}" -gt 0 ] || continue

    prev="$(ctl_get "TENANT#${id}" "META" | jq -r '.Item.req_count.N // empty')"
    since="$(ctl_get "TENANT#${id}" "META" | jq -r '.Item.idle_since.N // empty')"

    if [ -z "${prev}" ] || [ "${prev}" != "${count}" ]; then
      # First observation, or traffic since the last run: tenant is in use.
      record_activity "${id}" "${count}" "${now}"
      continue
    fi

    # Counter unchanged. Suspend once it has been unchanged long enough.
    [ -n "${since}" ] || { record_activity "${id}" "${count}" "${now}"; continue; }
    if [ $(( now - since )) -ge "${IDLE_AFTER_SECONDS}" ]; then
      suspend_tenant "${id}" "${ns}"
      record_activity "${id}" "${count}" "${now}"
    else
      idle_log "${id} idle for $(( now - since ))s (threshold ${IDLE_AFTER_SECONDS}s)"
    fi
  done <<< "${counts}"

  idle_log "idle scan complete."
}

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
  # shellcheck source=/dev/null
  source "${REPO_ROOT}/demo-platform/lib/control-common.sh"
  suspend_idle_tenants
fi
