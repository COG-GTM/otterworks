#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# OtterWorks - Per-Tenant Teardown
#
# Deletes an ephemeral tenant created by deploy-tenant.sh:
#   1. (unless --keep-db) drops the per-tenant RDS database otterworks_<ID>
#      via an in-cluster job (the Devin VM has no direct VPC access to RDS)
#   2. deletes the namespace otterworks-<ID> (all Helm releases, Redis, Meili,
#      config/secrets, ingress, quota, netpol) in one shot
#   3. deletes the tenant's IRSA roles (reverse of deploy-tenant's
#      ensure_tenant_irsa) and strips any trust for the namespace left on the
#      shared per-service roles by older deploys
#   4. (unless --keep-db) deletes the tenant's DynamoDB tables and its
#      tenants/<ID>/ prefix in the shared buckets
#
# Usage:
#   ./scripts/teardown-tenant.sh <ATTENDEE_ID> [--keep-db] [--keep-trust]
#
# Required env: AWS creds (exported). DB_PASSWORD needed only to drop the DB.
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
  warn "Namespace ${NS} not found (already deleted / reaped); still dropping DB + cleaning IRSA roles/data."
else
  log "Deleting namespace ${NS}..."
  kubectl delete namespace "${NS}" --wait=true --timeout=180s || \
    warn "Namespace deletion timed out; it may still be terminating."
fi

# --- Step 2: drop the per-tenant database (now that no pods are connected) ---
# Runs regardless of whether the namespace still existed: the drop Job executes
# in ${SYSTEM_NAMESPACE}, not the tenant namespace, so it works even after the
# reaper has removed the tenant namespace (the reaper does NOT drop DBs).
if [ "${KEEP_DB}" = false ] && [ -n "${DB_PASSWORD:-}" ]; then
  load_infra_outputs
  if [ -n "${RDS_HOST}" ]; then
    log "Dropping per-tenant database ${T_DB_NAME} (in-cluster job in ${SYSTEM_NAMESPACE})..."
    kubectl get ns "${SYSTEM_NAMESPACE}" >/dev/null 2>&1 || kubectl create ns "${SYSTEM_NAMESPACE}" >/dev/null 2>&1 || true
    drop_tenant_db "${T_DB_NAME}" "${SYSTEM_NAMESPACE}" || \
      warn "  check RDS manually for ${T_DB_NAME}."
  fi
elif [ "${KEEP_DB}" = false ]; then
  warn "DB_PASSWORD not set; skipping DB drop. Set it or drop ${T_DB_NAME} manually."
fi

# --- Step 3: delete this tenant's IRSA roles; strip legacy shared-role trust ---
oidc_host="$(terraform -chdir="${REPO_ROOT}/platform/terraform" output -raw oidc_provider_url 2>/dev/null || echo "")"
# In-cluster fall back to the EKS API for the OIDC issuer (see deploy-tenant.sh).
if [ -z "${oidc_host}" ]; then
  oidc_host="$(aws eks describe-cluster --name "${EKS_CLUSTER}" --region "${AWS_REGION}" \
    --query 'cluster.identity.oidc.issuer' --output text 2>/dev/null || echo "")"
fi
if [ "${KEEP_TRUST}" = false ]; then
  log "Deleting tenant IRSA roles..."
  delete_tenant_irsa_roles "${ATTENDEE_ID}"
  remove_shared_role_tenant_trust "${NS}" "${oidc_host#https://}"
fi

# --- Step 4: delete the tenant's DynamoDB tables and S3 prefixes ---
if [ "${KEEP_DB}" = false ]; then
  [ -n "${S3_FILE_BUCKET:-}" ] || load_infra_outputs
  log "Deleting tenant DynamoDB tables and S3 prefixes..."
  delete_tenant_data_stores "${ATTENDEE_ID}" || TEARDOWN_FAILED=true
fi

if [ "${TEARDOWN_FAILED:-false}" = true ]; then
  err "Teardown incomplete for tenant ${ATTENDEE_ID}: some tenant tables/objects remain (see warnings)."
  exit 1
fi
log "Teardown complete for tenant ${ATTENDEE_ID} (namespace ${NS})."
