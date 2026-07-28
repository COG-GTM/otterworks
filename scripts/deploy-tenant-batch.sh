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
LOG_DIR=""
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
    --tier|--profile|--host-suffix|--image-tag)
                   PASSTHROUGH+=("$1" "$2"); shift 2 ;;
    --skip-db)     PASSTHROUGH+=("$1"); shift ;;
    -h|--help)     sed -n '2,33p' "$0"; exit 0 ;;
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

# Warm the shared Terraform working directory ONCE, serially, before fanning
# out: each deploy-tenant.sh calls load_infra_outputs, which runs
# `terraform init` in infrastructure/terraform. Concurrent inits in one
# directory race on .terraform/ (and the failure is swallowed by `|| true`), so
# a parallel worker can then read empty outputs and deploy a tenant with no DB
# wiring. A pre-warmed directory makes each worker's init a concurrency-safe
# no-op re-init.
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
terraform -chdir="${REPO_ROOT}/infrastructure/terraform" init -input=false >/dev/null \
  || { err "terraform init failed in ${REPO_ROOT}/infrastructure/terraform"; exit 1; }

LOG_DIR="${LOG_DIR:-/tmp/otterworks-batch-$(date -u +%s)}"
mkdir -p "${LOG_DIR}/status"
log "Per-tenant logs: ${LOG_DIR}"

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
