#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Install External Secrets Operator (shared platform add-on, once per cluster)
# plus the otterworks ClusterSecretStores. See docs/SECRETS.md.
#
# The controller authenticates to AWS with IRSA only: its ServiceAccount is
# annotated with the role from Terraform output `external_secrets_role_arn`
# (infrastructure/terraform, enable_external_secrets = true). No static keys.
#
# Idempotent: safe to re-run; re-running with a new ESO_VERSION upgrades.
#
# Usage:
#   ESO_ROLE_ARN=arn:aws:iam::<acct>:role/otterworks-external-secrets-dev \
#     demo-platform/scripts/install-external-secrets.sh
#   demo-platform/scripts/install-external-secrets.sh --dry-run   # render only
#
# Env:
#   ESO_VERSION         chart version (pinned; default below)
#   ESO_ROLE_ARN        IRSA role ARN (required unless --dry-run)
#   ESO_TENANT_ROLE_ARN role the tenant store assumes (external_secrets_tenant_role_arn)
#   GOLDEN_NAMESPACE    only namespace allowed to use the golden stores (default otterworks)
#   AWS_REGION          region for the ClusterSecretStores (default us-east-1)
#   ESO_EXTRA_VALUES    optional extra values file (e.g. local kind/LocalStack)
# ------------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STORES="${HERE}/../k8s/external-secrets/cluster-secret-stores.yaml"
NS=external-secrets
RELEASE=external-secrets
SERVICE_ACCOUNT=external-secrets
ESO_VERSION="${ESO_VERSION:-2.10.0}"
AWS_REGION="${AWS_REGION:-us-east-1}"
GOLDEN_NAMESPACE="${GOLDEN_NAMESPACE:-otterworks}"
DRY_RUN=false
[ "${1:-}" = "--dry-run" ] && DRY_RUN=true

log()  { echo "[external-secrets] $*"; }
fail() { echo "[external-secrets] ERROR: $*" >&2; exit 1; }

for bin in helm kubectl; do
  command -v "${bin}" >/dev/null 2>&1 || fail "${bin} is required"
done
[[ "${AWS_REGION}" =~ ^[a-z0-9-]+$ ]] || fail "invalid AWS_REGION: ${AWS_REGION}"
[[ "${GOLDEN_NAMESPACE}" =~ ^[a-z0-9-]+$ ]] || fail "invalid GOLDEN_NAMESPACE: ${GOLDEN_NAMESPACE}"

if [ "${DRY_RUN}" = false ] && [ -z "${ESO_ROLE_ARN:-}" ]; then
  fail "ESO_ROLE_ARN is required (terraform -chdir=infrastructure/terraform output -raw external_secrets_role_arn)"
fi
if [ "${DRY_RUN}" = false ] && [ -z "${ESO_TENANT_ROLE_ARN:-}" ]; then
  fail "ESO_TENANT_ROLE_ARN is required (terraform -chdir=infrastructure/terraform output -raw external_secrets_tenant_role_arn)"
fi
ESO_TENANT_ROLE_ARN="${ESO_TENANT_ROLE_ARN:-arn:aws:iam::000000000000:role/dry-run-tenant}"
[[ "${ESO_TENANT_ROLE_ARN}" =~ ^arn:aws[a-z-]*:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+$ ]] \
  || fail "invalid ESO_TENANT_ROLE_ARN: ${ESO_TENANT_ROLE_ARN}"

helm repo add external-secrets https://charts.external-secrets.io >/dev/null 2>&1 || true
helm repo update external-secrets >/dev/null

helm_args=(
  --namespace "${NS}"
  --version "${ESO_VERSION}"
  --set installCRDs=true
  --set serviceAccount.create=true
  --set-string serviceAccount.name="${SERVICE_ACCOUNT}"
  --set-string "serviceAccount.annotations.eks\.amazonaws\.com/role-arn=${ESO_ROLE_ARN:-arn:aws:iam::000000000000:role/dry-run}"
)
[ -n "${ESO_EXTRA_VALUES:-}" ] && helm_args+=(-f "${ESO_EXTRA_VALUES}")

render_stores() {
  sed -e "s|\${AWS_REGION}|${AWS_REGION}|g" -e "s|\${GOLDEN_NAMESPACE}|${GOLDEN_NAMESPACE}|g" \
    -e "s|\${ESO_TENANT_ROLE_ARN}|${ESO_TENANT_ROLE_ARN}|g" "${STORES}"
}

if [ "${DRY_RUN}" = true ]; then
  helm template "${RELEASE}" external-secrets/external-secrets "${helm_args[@]}"
  echo "---"
  render_stores
  exit 0
fi

log "installing external-secrets ${ESO_VERSION} into ${NS}..."
helm upgrade --install "${RELEASE}" external-secrets/external-secrets \
  "${helm_args[@]}" --create-namespace --wait --timeout 5m

for crd in externalsecrets clustersecretstores secretstores; do
  kubectl wait --for=condition=Established "crd/${crd}.external-secrets.io" --timeout=60s >/dev/null
done
kubectl -n "${NS}" rollout status "deploy/${RELEASE}-webhook" --timeout=120s

log "applying ClusterSecretStores (region ${AWS_REGION})..."
# The webhook can take a few seconds to serve after rollout; retry briefly.
for attempt in 1 2 3 4 5 6; do
  if render_stores | kubectl apply -f -; then break; fi
  [ "${attempt}" -eq 6 ] && fail "could not apply ClusterSecretStores"
  sleep 5
done

kubectl wait --for=condition=Ready clustersecretstore/otterworks-secretsmanager \
  clustersecretstore/otterworks-parameterstore clustersecretstore/otterworks-tenant-secretsmanager \
  --timeout=120s \
  || fail "ClusterSecretStores not Ready; check the IRSA role trust/policy (kubectl describe clustersecretstore)"
log "done."
