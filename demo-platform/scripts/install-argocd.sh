#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Install Argo CD as a SHARED platform add-on (once per cluster) and, optionally,
# bootstrap the OtterWorks GitOps app-of-apps for the long-lived environments.
#
# GitOps covers dev/staging/prod only. Ephemeral tenants (otterworks-<id>) stay
# on scripts/deploy-tenant.sh -- see docs/GITOPS.md for how the two coexist.
#
# Nothing here runs automatically: it is never called from CI or deploy-dev.sh.
# Uses the current kubectl context.
#
# Usage:
#   demo-platform/scripts/install-argocd.sh                       # controller only
#   demo-platform/scripts/install-argocd.sh --bootstrap \
#     --envs dev --image-registry <acct>.dkr.ecr.us-east-1.amazonaws.com
#
# Options (all optional):
#   --bootstrap               apply deploy/gitops/bootstrap/root-app.yaml
#   --envs <glob>             environments this cluster hosts, e.g. dev or
#                             "{dev,staging}" (default: dev)
#   --services <glob>         service subset, e.g. "{api-gateway,web-app}" (default: *)
#   --image-registry <host>   registry prefix; images resolve to <host>/otterworks/<svc>
#   --revision <ref>          git revision the root app + ApplicationSet track (default: main)
#   --repo-url <url>          git repo (default: https://github.com/COG-GTM/otterworks.git)
#
# Env: ARGOCD_EXTRA_VALUES=<file> layers a cluster-specific values file over
# demo-platform/k8s/argocd/values.yaml (e.g. a registry mirror on kind).
# ------------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
K8S_DIR="${HERE}/../k8s"
pinned_version="${ARGOCD_CHART_VERSION:-}"
# shellcheck source=../k8s/platform-addons.versions.env
source "${K8S_DIR}/platform-addons.versions.env"
ARGOCD_CHART_VERSION="${pinned_version:-${ARGOCD_CHART_VERSION}}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"

BOOTSTRAP=false
ENVS="dev"
SERVICES="*"
IMAGE_REGISTRY=""
REVISION="main"
REPO_URL="https://github.com/COG-GTM/otterworks.git"

log()  { echo "[argocd] $*"; }
fail() { echo "[argocd] ERROR: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --bootstrap)      BOOTSTRAP=true; shift ;;
    --envs)           ENVS="$2"; shift 2 ;;
    --services)       SERVICES="$2"; shift 2 ;;
    --image-registry) IMAGE_REGISTRY="$2"; shift 2 ;;
    --revision)       REVISION="$2"; shift 2 ;;
    --repo-url)       REPO_URL="$2"; shift 2 ;;
    *) fail "unknown argument: $1" ;;
  esac
done

for bin in kubectl helm jq; do
  command -v "${bin}" >/dev/null 2>&1 || fail "${bin} is required"
done

version="${ARGOCD_CHART_VERSION}"
deployed="$(helm list -n "${ARGOCD_NAMESPACE}" --filter '^argocd$' -o json 2>/dev/null \
  | jq -r '.[0].chart // ""' | sed 's/^argo-cd-//')"
if [ -n "${deployed}" ] && [ "${deployed}" != "${version}" ] && [ "${ARGOCD_ALLOW_UPGRADE:-false}" != true ]; then
  log "argo-cd chart ${deployed} is deployed; pinned is ${version}. Keeping ${deployed} (set ARGOCD_ALLOW_UPGRADE=true to move)."
  version="${deployed}"
fi

helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
helm repo update argo >/dev/null

log "Installing Argo CD chart ${version} into ${ARGOCD_NAMESPACE}..."
helm upgrade --install argocd argo/argo-cd \
  --namespace "${ARGOCD_NAMESPACE}" --create-namespace \
  --version "${version}" \
  -f "${K8S_DIR}/argocd/values.yaml" \
  ${ARGOCD_EXTRA_VALUES:+-f "${ARGOCD_EXTRA_VALUES}"} \
  --wait --timeout 10m

if [ "${BOOTSTRAP}" != true ]; then
  log "Argo CD ready. Re-run with --bootstrap to register this cluster and apply the app-of-apps."
  exit 0
fi

[ -n "${IMAGE_REGISTRY}" ] || fail "--image-registry is required with --bootstrap"

# Argo CD has no Secret for its own cluster by default; declaring one is the
# documented way to attach labels/annotations to in-cluster. The ApplicationSet
# (deploy/gitops/apps/otterworks-envs.yaml) reads them as generator params.
log "Registering in-cluster for envs=${ENVS} services=${SERVICES} revision=${REVISION}"
kubectl apply -f - <<YAML
apiVersion: v1
kind: Secret
metadata:
  name: cluster-in-cluster
  namespace: ${ARGOCD_NAMESPACE}
  labels:
    argocd.argoproj.io/secret-type: cluster
    otterworks.io/gitops: "true"
  annotations:
    otterworks.io/envs: "${ENVS}"
    otterworks.io/services: "${SERVICES}"
    otterworks.io/image-registry: "${IMAGE_REGISTRY}"
    otterworks.io/git-revision: "${REVISION}"
type: Opaque
stringData:
  name: in-cluster
  server: https://kubernetes.default.svc
  config: '{"tlsClientConfig":{"insecure":false}}'
YAML

log "Applying app-of-apps (repo=${REPO_URL} revision=${REVISION})"
sed -e "s#targetRevision: main#targetRevision: ${REVISION}#" \
    -e "s#repoURL: https://github.com/COG-GTM/otterworks.git#repoURL: ${REPO_URL}#" \
    "${REPO_ROOT}/deploy/gitops/bootstrap/root-app.yaml" | kubectl apply -f -

log "Done. Watch: kubectl -n ${ARGOCD_NAMESPACE} get applications"
