#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# OtterWorks - Batch Tenant Deploy (one persistent tenant per person)
#
# Deploys one tenant per name in a roster file by calling deploy-tenant.sh with
# a "firstname-lastname" id, so each person gets a standing environment at
# namespace otterworks-<firstname-lastname> and database
# otterworks_<firstname_lastname>.
#
# Tenants are PERSISTENT by default (--ttl none): no expiry is written and the
# namespace is labelled demo/persistent=true, which every reaper path skips.
# They are removed only by scripts/teardown-tenant.sh.
#
# Resumable: a tenant whose namespace already exists is skipped unless
# --redeploy is passed, so a partial run can simply be re-run.
#
# Usage:
#   ./scripts/deploy-tenant-batch.sh [options] [NAME ...]
#
#   NAME ...            deploy only these people (default: the whole roster)
#   --roster FILE       roster file (default: scripts/tenant-roster.txt)
#   --ttl VALUE         lifetime passed to deploy-tenant.sh (default: none)
#   --concurrency N     tenants to deploy in parallel (default: 4)
#   --redeploy          also (re)deploy tenants whose namespace already exists
#   --dry-run           print the resolved ids and commands; touch nothing
#   --no-preflight      deploy even if the cluster cannot hold the roster
#   --log-dir DIR       per-tenant logs (default: /tmp/otterworks-batch-<epoch>)
#   --tier A|B | --profile core|full | --host-suffix D | --image-tag T
#                       passed through to deploy-tenant.sh
#
# Required env: AWS creds (exported), DB_PASSWORD. Export a stable JWT_SECRET /
#   SECRET_KEY_BASE so a later redeploy does not invalidate issued sessions.
# ------------------------------------------------------------------------------
# No -e: one person's failed deploy must not abandon the rest of the roster.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/tenant-common.sh
source "${SCRIPT_DIR}/lib/tenant-common.sh"

ROSTER="${SCRIPT_DIR}/tenant-roster.txt"
TTL="none"
CONCURRENCY=4
REDEPLOY=false
DRY_RUN=false
PREFLIGHT=true
LOG_DIR=""
PROFILE="full"
NAMES=()
PASSTHROUGH=()

while [ $# -gt 0 ]; do
  case "$1" in
    --roster)      ROSTER="$2"; shift 2 ;;
    --ttl)         TTL="$2"; shift 2 ;;
    --concurrency) CONCURRENCY="$2"; shift 2 ;;
    --log-dir)     LOG_DIR="$2"; shift 2 ;;
    --redeploy)    REDEPLOY=true; shift ;;
    --dry-run)     DRY_RUN=true; shift ;;
    --no-preflight) PREFLIGHT=false; shift ;;
    --tier|--profile|--host-suffix|--image-tag)
                   [ "$1" = "--profile" ] && PROFILE="$2"
                   PASSTHROUGH+=("$1" "$2"); shift 2 ;;
    --skip-db)     PASSTHROUGH+=("$1"); shift ;;
    -h|--help)     sed -n '2,34p' "$0"; exit 0 ;;
    -*)            err "Unknown flag: $1"; exit 1 ;;
    *)             NAMES+=("$1"); shift ;;
  esac
done

[[ "${CONCURRENCY}" =~ ^[1-9][0-9]*$ ]] || { err "--concurrency must be a positive integer"; exit 1; }

# Turn a person's name into a tenant id. Accents are transliterated rather than
# dashed out, so "João Esteves" is joao-esteves and not jo--o-esteves (sanitize_id
# replaces each byte of a multi-byte character). //TRANSLIT can spell an accent
# out as a quote or caret ("o -> o umlaut), hence the punctuation strip before
# the remaining runs of non-alphanumerics collapse to single dashes.
tenant_id_from_name() {
  local ascii
  ascii="$(printf '%s' "$1" | iconv -f UTF-8 -t ASCII//TRANSLIT 2>/dev/null)" || ascii="$1"
  printf '%s' "${ascii}" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E "s/[\"'\`^~]//g; s/[^a-z0-9]+/-/g; s/^-+//; s/-+$//"
}

# ---------- Build the roster ----------
FROM="the command line"
if [ "${#NAMES[@]}" -eq 0 ]; then
  FROM="${ROSTER}"
  [ -f "${ROSTER}" ] || { err "Roster file not found: ${ROSTER}"; exit 1; }
  while IFS= read -r line; do
    line="${line%$'\r'}"                       # tolerate CRLF rosters
    line="$(printf '%s' "${line}" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
    case "${line}" in ""|\#*) continue ;; esac
    NAMES+=("${line}")
  done < "${ROSTER}"
fi
[ "${#NAMES[@]}" -gt 0 ] || { err "No names to deploy."; exit 1; }

IDS=()
declare -A NAME_OF_ID=()
INVALID=0
for name in "${NAMES[@]}"; do
  id="$(tenant_id_from_name "${name}")"
  if [ -z "${id}" ]; then
    err "Cannot derive a tenant id from '${name}'"; INVALID=1; continue
  fi
  # otterworks-<id> is a namespace, i.e. one RFC-1123 label (63 chars max).
  if [ "${#id}" -gt 52 ]; then
    err "Tenant id '${id}' is too long for namespace $(tenant_namespace "${id}") (max 63 chars)"
    INVALID=1; continue
  fi
  if [ -n "${NAME_OF_ID[${id}]:-}" ]; then
    err "'${name}' and '${NAME_OF_ID[${id}]}' both map to tenant id '${id}'; disambiguate them in the roster"
    INVALID=1; continue
  fi
  NAME_OF_ID["${id}"]="${name}"
  IDS+=("${id}")
done
[ "${INVALID}" -eq 0 ] || { err "Roster has errors (above); nothing deployed."; exit 1; }

log "${#IDS[@]} tenant(s) from ${FROM}:"
for id in "${IDS[@]}"; do printf '  %-28s <- %s\n' "$(tenant_namespace "${id}")" "${NAME_OF_ID[${id}]}"; done

# Measured footprint of one tenant, from demo-platform/docs/cost-and-scale.md.
case "${PROFILE}" in
  core) PODS_EACH=7;  MILLICPU_EACH=500 ;;
  *)    PODS_EACH=15; MILLICPU_EACH=1500 ;;
esac
log "Steady state: $(( ${#IDS[@]} * PODS_EACH )) pods / ~$(( (${#IDS[@]} * MILLICPU_EACH + 999) / 1000 )) vCPU reserved permanently (${PROFILE} profile, no scale-to-zero)."

DEPLOY_ARGS=(--ttl "${TTL}" "${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}")
if [ "${DRY_RUN}" = true ]; then
  echo ""
  log "--dry-run: would run, ${CONCURRENCY} at a time:"
  for id in "${IDS[@]}"; do echo "  ${SCRIPT_DIR}/deploy-tenant.sh ${id} ${DEPLOY_ARGS[*]}"; done
  exit 0
fi

# ---------- Preflight ----------
require_bins aws kubectl helm terraform jq iconv
[ -n "${DB_PASSWORD:-}" ] || { err "DB_PASSWORD must be set (shared RDS master password)."; exit 1; }
# deploy-tenant.sh mints a random JWT_SECRET / SECRET_KEY_BASE when unset, which
# is per-invocation: a redeploy would then invalidate every session and token
# the tenant had issued. Fine for a first run, worth knowing before a redeploy.
[ -n "${JWT_SECRET:-}" ] || warn "JWT_SECRET unset: each tenant gets a random one, and a redeploy will rotate it."
[ -n "${SECRET_KEY_BASE:-}" ] || warn "SECRET_KEY_BASE unset: each tenant gets a random one, and a redeploy will rotate it."
if [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
  aws eks update-kubeconfig --name "${EKS_CLUSTER}" --region "${AWS_REGION}" --alias "${EKS_CLUSTER}" >/dev/null \
    || { err "Could not reach EKS cluster ${EKS_CLUSTER} in ${AWS_REGION}."; exit 1; }
fi

LOG_DIR="${LOG_DIR:-/tmp/otterworks-batch-$(date -u +%s)}"
mkdir -p "${LOG_DIR}/status"
log "Per-tenant logs: ${LOG_DIR}"

# ---------- Capacity ----------
# A persistent tenant never scales to zero -- idle-suspend only considers
# tenants that have a control-table item, and these have none, which is what
# keeps their URL answering without a wake step. So the roster is sized against
# the cluster's totals rather than against how many people are using it at once,
# and pod IPs bind first: the VPC CNI gives every pod a real subnet address, and
# a /24 node subnet holds ~250 of them.
capacity_preflight() {
  local want="$1" need_ips need_cpu free_ips limit_cpu rc=0
  need_ips=$(( want * PODS_EACH ))
  need_cpu=$(( (want * MILLICPU_EACH + 999) / 1000 ))

  # Free addresses across every subnet Karpenter may launch into. Prefix
  # delegation books a /28 at a time, so this reads slightly pessimistic --
  # addresses reserved for a node's next pods count as allocated.
  free_ips="$(aws ec2 describe-subnets --region "${AWS_REGION}" \
    --filters "Name=tag:karpenter.sh/discovery,Values=${EKS_CLUSTER}" \
    --query 'sum(Subnets[].AvailableIpAddressCount)' --output text 2>/dev/null | sed 's/\..*//')"
  if [[ "${free_ips}" =~ ^[0-9]+$ ]]; then
    log "Capacity: ${want} × ${PODS_EACH} pods = ${need_ips} pod IPs needed, ${free_ips} free in the node subnets."
    if [ "${free_ips}" -lt "${need_ips}" ]; then
      err "Not enough pod IPs for ${want} persistent ${PROFILE} tenants (need ${need_ips}, have ${free_ips})."
      err "Pods would sit Pending and the deploys would time out one by one."
      err "Widen the node subnets first: apply aws_subnet.pods in platform/terraform (a /20 per AZ),"
      err "or deploy fewer people at a time. --no-preflight overrides this check."
      rc=1
    fi
  else
    warn "Could not read subnet capacity from EC2; skipping the pod-IP check."
  fi

  # Advisory: the NodePool ceiling counts node capacity, not requests, so it is
  # not a like-for-like comparison -- but being under it already means the
  # roster cannot fit.
  limit_cpu="$(kubectl get nodepool tenants -o jsonpath='{.spec.limits.cpu}' 2>/dev/null)"
  if [[ "${limit_cpu}" =~ ^[0-9]+$ ]] && [ "${limit_cpu}" -lt "${need_cpu}" ]; then
    warn "Karpenter NodePool 'tenants' is capped at ${limit_cpu} vCPU; ${want} ${PROFILE} tenants request ~${need_cpu}. Raise spec.limits.cpu."
  fi
  return "${rc}"
}

# ---------- Deploy ----------
# Status is written to a file per tenant rather than a shell variable: each
# deploy runs in a background subshell and cannot write back to this one.
deploy_one() {
  local id="$1" logfile="${LOG_DIR}/${id}.log"
  if "${SCRIPT_DIR}/deploy-tenant.sh" "${id}" "${DEPLOY_ARGS[@]}" >"${logfile}" 2>&1; then
    echo ok > "${LOG_DIR}/status/${id}"
    log "  [ok]   ${id}"
  else
    echo fail > "${LOG_DIR}/status/${id}"
    err "  [fail] ${id} — see ${logfile}"
    tail -3 "${logfile}" | sed 's/^/         /' >&2
  fi
}

SKIPPED=()
QUEUE=()
for id in "${IDS[@]}"; do
  if [ "${REDEPLOY}" = false ] && kubectl get ns "$(tenant_namespace "${id}")" >/dev/null 2>&1; then
    SKIPPED+=("${id}")
    continue
  fi
  QUEUE+=("${id}")
done
[ "${#SKIPPED[@]}" -eq 0 ] || log "Skipping ${#SKIPPED[@]} existing tenant(s) (pass --redeploy to redeploy them)."

if [ "${#QUEUE[@]}" -gt 0 ] && [ "${PREFLIGHT}" = true ]; then
  capacity_preflight "${#QUEUE[@]}" || exit 1
fi

log "Deploying ${#QUEUE[@]} tenant(s), ${CONCURRENCY} at a time..."
running=0
for id in "${QUEUE[@]+"${QUEUE[@]}"}"; do
  deploy_one "${id}" &
  running=$(( running + 1 ))
  if [ "${running}" -ge "${CONCURRENCY}" ]; then
    wait -n
    running=$(( running - 1 ))
  fi
done
wait

# ---------- Summary ----------
OK=(); FAILED=()
for id in "${QUEUE[@]+"${QUEUE[@]}"}"; do
  if [ "$(cat "${LOG_DIR}/status/${id}" 2>/dev/null)" = "ok" ]; then OK+=("${id}"); else FAILED+=("${id}"); fi
done

echo ""
log "Batch complete: ${#OK[@]} deployed, ${#SKIPPED[@]} skipped, ${#FAILED[@]} failed."
if [ "${#FAILED[@]}" -gt 0 ]; then
  err "Failed: ${FAILED[*]}"
  err "Re-run the same command to retry only those (successful tenants are skipped)."
  exit 1
fi
log "Tenants are persistent (ttl=${TTL}); remove one with ./scripts/teardown-tenant.sh <id>"
