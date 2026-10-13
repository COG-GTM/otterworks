#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Install cert-manager on the shared cluster (once per cluster, never per tenant).
#
# Pinned via demo-platform/k8s/platform-addons.versions.env. On an existing
# release the deployed version is kept unless CERT_MANAGER_ALLOW_UPGRADE=true,
# so a routine re-run never silently moves the component that renews every
# tenant's TLS. Route53 IRSA wiring for the ACME DNS-01 solver is EKS-specific
# and stays in scripts/enable-dns-tls.sh.
#
# Idempotent. Uses the current kubectl context (run
# `aws eks update-kubeconfig ...` first for EKS, or point at a kind cluster).
#
# Usage:
#   demo-platform/scripts/install-cert-manager.sh
#   CERT_MANAGER_CHART_VERSION=v1.21.2 demo-platform/scripts/install-cert-manager.sh
# ------------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="${HERE}/../k8s"
pinned_version="${CERT_MANAGER_CHART_VERSION:-}"
# shellcheck source=/dev/null
source "${K8S_DIR}/platform-addons.versions.env"
CERT_MANAGER_CHART_VERSION="${pinned_version:-${CERT_MANAGER_CHART_VERSION}}"
CERT_MANAGER_NAMESPACE="${CERT_MANAGER_NAMESPACE:-cert-manager}"

log()  { echo "[cert-manager] $*"; }
fail() { echo "[cert-manager] ERROR: $*" >&2; exit 1; }

for bin in kubectl helm jq; do
  command -v "${bin}" >/dev/null 2>&1 || fail "${bin} is required"
done

version="${CERT_MANAGER_CHART_VERSION}"
deployed="$(helm list -n "${CERT_MANAGER_NAMESPACE}" --filter '^cert-manager$' -o json 2>/dev/null \
  | jq -r '.[0].chart // ""' | sed 's/^cert-manager-//')"
if [ -n "${deployed}" ] && [ "${deployed}" != "${version}" ] && [ "${CERT_MANAGER_ALLOW_UPGRADE:-false}" != true ]; then
  log "cert-manager ${deployed} is deployed; pinned is ${version}. Keeping ${deployed} (set CERT_MANAGER_ALLOW_UPGRADE=true to move)."
  version="${deployed}"
fi

helm repo add jetstack https://charts.jetstack.io >/dev/null 2>&1 || true
helm repo update jetstack >/dev/null

log "Installing cert-manager ${version} into ${CERT_MANAGER_NAMESPACE}..."
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace "${CERT_MANAGER_NAMESPACE}" --create-namespace \
  --version "${version}" \
  --reuse-values -f "${K8S_DIR}/cert-manager/values.yaml" \
  --wait --timeout 5m

kubectl -n "${CERT_MANAGER_NAMESPACE}" rollout status deploy/cert-manager-webhook --timeout=120s
log "cert-manager ${version} ready."
