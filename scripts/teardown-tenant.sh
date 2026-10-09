#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# OtterWorks - Per-Tenant Teardown
#
# Deletes an ephemeral tenant created by deploy-tenant.sh:
#   1. (unless --keep-db) drops the per-tenant RDS database otterworks_<ID>
#      via an in-cluster job (the Devin VM has no direct VPC access to RDS)
#   2. deletes the namespace otterworks-<ID> (all Helm releases, Redis, Meili,
#      config/secrets, ingress, quota, netpol) in one shot
#   3. removes the tenant's service-account subs from the shared IRSA role trust
#      policies (reverse of deploy-tenant's ensure_irsa_trust)
#
# Usage:
#   ./scripts/teardown-tenant.sh <ATTENDEE_ID> [--keep-db] [--keep-trust]
#
# Required env: AWS creds (exported). DB_PASSWORD (RDS master) needed only to
#   drop the DB and the tenant's login role.
# ------------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=lib/tenant-common.sh
source "${SCRIPT_DIR}/lib/tenant-common.sh"

ATTENDEE_ID=""
KEEP_DB=false
KEEP_TRUST=false
while [ $# -gt 0 ]; do
  case "$1" in
    --keep-db)    KEEP_DB=true; shift ;;
    --keep-trust) KEEP_TRUST=true; shift ;;
    -*)           err "Unknown flag: $1"; exit 1 ;;
    *)            if [ -z "${ATTENDEE_ID}" ]; then ATTENDEE_ID="$1"; else err "Unexpected arg: $1"; exit 1; fi; shift ;;
  esac
done
[ -n "${ATTENDEE_ID}" ] || { err "Usage: $0 <ATTENDEE_ID> [--keep-db] [--keep-trust]"; exit 1; }

require_bins aws kubectl jq
NS="$(tenant_namespace "${ATTENDEE_ID}")"
T_DB_NAME="$(tenant_db_name "${ATTENDEE_ID}")"

# In-cluster (runner Job) use the pod ServiceAccount + RBAC; only build a
# kubeconfig when running standalone (see deploy-tenant.sh for the rationale).
if [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
  aws eks update-kubeconfig --name "${EKS_CLUSTER}" --region "${AWS_REGION}" --alias "${EKS_CLUSTER}" >/dev/null 2>&1 || true
fi

# --- Step 1: delete the namespace (everything in it) FIRST ---
# This stops every application pod so nothing is still holding a connection to
# the per-tenant database when we drop it in step 2 (avoids DROP racing the
# connection-pool reconnects of live pods). The namespace may already be gone
# (e.g. the TTL reaper deleted it) — that's fine, we still drop the DB below.
if ! kubectl get ns "${NS}" >/dev/null 2>&1; then
  warn "Namespace ${NS} not found (already deleted / reaped); still dropping DB + cleaning IRSA trust."
else
  log "Deleting namespace ${NS}..."
  kubectl delete namespace "${NS}" --wait=true --timeout=180s || \
    warn "Namespace deletion timed out; it may still be terminating."
fi

# --- Step 2: drop the per-tenant database + role (now that no pods are connected) ---
# Runs regardless of whether the namespace still existed: the drop Job executes
# in ${SYSTEM_NAMESPACE}, not the tenant namespace, so it works even after the
# reaper has removed the tenant namespace (the reaper does NOT drop DBs).
if [ "${KEEP_DB}" = false ] && [ -n "${DB_PASSWORD:-}" ]; then
  load_infra_outputs
  if [ -n "${RDS_HOST}" ]; then
    log "Dropping per-tenant database ${T_DB_NAME} and role $(tenant_db_role_for_db "${T_DB_NAME}") (in-cluster job in ${SYSTEM_NAMESPACE})..."
    kubectl get ns "${SYSTEM_NAMESPACE}" >/dev/null 2>&1 || kubectl create ns "${SYSTEM_NAMESPACE}" >/dev/null 2>&1 || true
    drop_tenant_db "${T_DB_NAME}" "${SYSTEM_NAMESPACE}" || \
      warn "  check RDS manually for ${T_DB_NAME}."
  fi
elif [ "${KEEP_DB}" = false ]; then
  warn "DB_PASSWORD not set; skipping DB drop. Set it or drop ${T_DB_NAME} manually."
fi

# --- Step 3: remove this tenant's subs from the shared IRSA role trust policies ---
remove_irsa_trust() {
  local d="${REPO_ROOT}/infrastructure/terraform"
  terraform -chdir="$d" init -input=false >/dev/null 2>&1 || true
  local irsa_json; irsa_json="$(terraform -chdir="$d" output -json irsa_role_arns 2>/dev/null || echo "{}")"
  local oidc_url; oidc_url="$(terraform -chdir="${REPO_ROOT}/platform/terraform" output -raw oidc_provider_url 2>/dev/null || echo "")"
  # In-cluster fall back to the EKS API for the OIDC issuer (see deploy-tenant.sh).
  if [ -z "${oidc_url}" ]; then
    oidc_url="$(aws eks describe-cluster --name "${EKS_CLUSTER}" --region "${AWS_REGION}" \
      --query 'cluster.identity.oidc.issuer' --output text 2>/dev/null || echo "")"
  fi
  oidc_url="${oidc_url#https://}"
  [ -n "${oidc_url}" ] || { warn "OIDC URL unavailable; skipping IRSA trust cleanup."; return 0; }
  local svc role sub
  for svc in $(echo "${irsa_json}" | jq -r 'keys[]'); do
    role="otterworks-${svc}-dev"
    sub="system:serviceaccount:${NS}:${svc}"
    local doc; doc="$(aws iam get-role --role-name "${role}" --query 'Role.AssumeRolePolicyDocument' --output json 2>/dev/null || echo "")"
    [ -n "${doc}" ] || continue
    # Remove ONLY legacy per-tenant statements that pin this exact sub via
    # StringEquals (added by older deploys). Statements without a
    # StringEquals[:sub] — notably the shared Terraform-managed StringLike
    # wildcard statement that grants every otterworks-* namespace — MUST be left
    # untouched; stripping it would break AWS access for the golden app and all
    # other tenants. The current deploy relies on that wildcard and adds no
    # per-tenant StringEquals statement, so this is normally a no-op.
    local new; new="$(echo "${doc}" | jq --arg sub "${sub}" --arg url "${oidc_url}" '
      .Statement |= map(
        if (.Condition.StringEquals[$url+":sub"] // null) != null then
          select((.Condition.StringEquals[$url+":sub"]
            | (if type=="array" then . else [.] end) | index($sub)) | not)
        else . end)')"
    # Only update if something actually changed.
    if [ "$(echo "${doc}" | jq -cS .)" != "$(echo "${new}" | jq -cS .)" ]; then
      aws iam update-assume-role-policy --role-name "${role}" --policy-document "${new}" >/dev/null \
        && log "  IRSA trust: removed ${sub} from ${role}" \
        || warn "  failed to clean trust for ${role}"
    fi
  done
}
if [ "${KEEP_TRUST}" = false ]; then
  log "Cleaning tenant service-account subs from shared IRSA role trust policies..."
  remove_irsa_trust
fi

log "Teardown complete for tenant ${ATTENDEE_ID} (namespace ${NS})."
