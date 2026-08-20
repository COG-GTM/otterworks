#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# OtterWorks - Per-Tenant Bug Injection
#
# Applies a scenario from scripts/bug-catalog.yaml to a SINGLE tenant namespace
# without touching the golden app or any other tenant. See the catalog for the
# full list and mechanisms (chaos flag / config override / variant image).
#
# Usage:
#   ./scripts/inject-bug.sh <ATTENDEE_ID> list
#   ./scripts/inject-bug.sh <ATTENDEE_ID> <scenario> [--image-tag TAG]
#   ./scripts/inject-bug.sh <ATTENDEE_ID> reset        # clear all chaos flags
# ------------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=lib/tenant-common.sh
source "${SCRIPT_DIR}/lib/tenant-common.sh"

ATTENDEE_ID="${1:-}"
SCENARIO="${2:-}"
shift $(( $# > 2 ? 2 : $# )) || true
IMAGE_TAG_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --image-tag) IMAGE_TAG_ARG="$2"; shift 2 ;;
    *) shift ;;
  esac
done

[ -n "${ATTENDEE_ID}" ] && [ -n "${SCENARIO}" ] || {
  err "Usage: $0 <ATTENDEE_ID> <list|reset|scenario> [--image-tag TAG]"; exit 1; }

require_bins kubectl
NS="$(tenant_namespace "${ATTENDEE_ID}")"

# Chaos scenario -> Redis key (mirrors admin-service ChaosController::VALID_SCENARIOS).
declare -A CHAOS_KEY=(
  [file-upload-fails]="chaos:file-service:upload_s3_error"
  [search-suggest-500]="chaos:search-service:suggest_500"
  [document-slow]="chaos:document-service:slow_queries"
  [notification-schema]="chaos:notification-service:consumer_strict_schema"
)
CHAOS_TTL="${CHAOS_TTL:-3600}"

redis_exec() { kubectl -n "${NS}" exec deploy/redis -- redis-cli "$@"; }

case "${SCENARIO}" in
  list)
    echo "Bug catalog (scripts/bug-catalog.yaml):"
    grep -E '^  [a-z].*:$|mechanism:|description:' "${SCRIPT_DIR}/bug-catalog.yaml" | sed 's/^/  /'
    exit 0 ;;
  reset)
    kubectl get ns "${NS}" >/dev/null 2>&1 || { err "Namespace ${NS} not found; deploy the tenant first."; exit 1; }
    log "Clearing all chaos flags in ${NS}..."
    keys="$(redis_exec --scan --pattern 'chaos:*' 2>/dev/null || true)"
    if [ -n "${keys}" ]; then echo "${keys}" | xargs -r -n1 kubectl -n "${NS}" exec deploy/redis -- redis-cli DEL >/dev/null; fi
    log "Cleared: ${keys:-<none>}"
    exit 0 ;;
esac

kubectl get ns "${NS}" >/dev/null 2>&1 || { err "Namespace ${NS} not found; deploy the tenant first."; exit 1; }

# --- Chaos-flag scenarios ---
if [ -n "${CHAOS_KEY[${SCENARIO}]:-}" ]; then
  key="${CHAOS_KEY[${SCENARIO}]}"
  log "Injecting chaos '${SCENARIO}' in ${NS}: SETEX ${key} ${CHAOS_TTL}"
  redis_exec SETEX "${key}" "${CHAOS_TTL}" 1 >/dev/null
  log "Active. Auto-expires in ${CHAOS_TTL}s, or clear now: $0 ${ATTENDEE_ID} reset"
  exit 0
fi

# --- Config-override scenario ---
if [ "${SCENARIO}" = "file-bad-bucket" ]; then
  log "Injecting config bug 'file-bad-bucket' (file-service -> nonexistent S3 bucket)..."
  helm upgrade file-service "${REPO_ROOT}/infrastructure/helm/file-service" -n "${NS}" --reuse-values \
    --set-string config.S3_BUCKET=otterworks-does-not-exist
  kubectl -n "${NS}" rollout restart deploy/file-service
  log "Applied (rollout restarting). Revert by re-running deploy-tenant.sh ${ATTENDEE_ID}."
  exit 0
fi

# --- Variant-image scenario ---
if [ "${SCENARIO}" = "code-variant" ]; then
  [ -n "${IMAGE_TAG_ARG}" ] || { err "code-variant requires --image-tag <variant-tag>"; exit 1; }
  svc="${VARIANT_SERVICE:-file-service}"
  log "Swapping ${svc} in ${NS} to variant image tag ${IMAGE_TAG_ARG}..."
  helm upgrade "${svc}" "${REPO_ROOT}/infrastructure/helm/${svc}" -n "${NS}" --reuse-values \
    --set image.tag="${IMAGE_TAG_ARG}"
  log "Applied. Rollback: re-run deploy-tenant.sh ${ATTENDEE_ID} (golden tag)."
  exit 0
fi

err "Unknown scenario '${SCENARIO}'. Run: $0 ${ATTENDEE_ID} list"
exit 1
