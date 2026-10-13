#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Offline validation of the External Secrets wiring (docs/SECRETS.md). Touches
# no cluster and no cloud account.
#   - helm lint + template every chart with externalSecrets off and on
#   - off: no ExternalSecret rendered; on: one per chart that maps keys
#   - kubeconform (strict) against Kubernetes + the pinned ESO CRD schemas
# Needs: helm, kubeconform, python3 + PyYAML.
# ------------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC2016
ESO_VERSION="$(sed -n 's/^ESO_VERSION="\${ESO_VERSION:-\(.*\)}"$/\1/p' "${REPO_ROOT}/demo-platform/scripts/install-external-secrets.sh")"
K8S_VERSION="${K8S_VERSION:-1.31.0}"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

helm repo add external-secrets https://charts.external-secrets.io >/dev/null 2>&1 || true
helm repo update external-secrets >/dev/null
helm pull external-secrets/external-secrets --version "${ESO_VERSION}" --untar --untardir "${WORK}"

# JSON schemas from the pinned chart's CRDs. ExternalSecret (what the charts
# render) gets strict schemas so unknown fields are rejected; the much larger
# store schemas use oneOf-style unions that strict mode breaks, so stay as-is.
mkdir -p "${WORK}/schemas"
helm template eso "${WORK}/external-secrets" --set installCRDs=true \
  --show-only templates/crds/externalsecret.yaml \
  --show-only templates/crds/clustersecretstore.yaml > "${WORK}/crds.yaml"
python3 - "${WORK}" <<'PY'
import json, sys, yaml
work = sys.argv[1]
def strict(s):
    if isinstance(s, dict):
        if "properties" in s and "additionalProperties" not in s and not s.get("x-kubernetes-preserve-unknown-fields"):
            s["additionalProperties"] = False
        for v in s.values(): strict(v)
    elif isinstance(s, list):
        for v in s: strict(v)
for d in yaml.safe_load_all(open(f"{work}/crds.yaml")):
    if not d: continue
    kind = d["spec"]["names"]["kind"].lower()
    for v in d["spec"]["versions"]:
        sch = v["schema"]["openAPIV3Schema"]
        if kind == "externalsecret": strict(sch)
        json.dump(sch, open(f"{work}/schemas/{kind}_{v['name']}.json", "w"))
PY

mkdir -p "${WORK}/out"
sed -e "s|\${AWS_REGION}|us-east-1|g" -e "s|\${GOLDEN_NAMESPACE}|otterworks|g" \
  -e "s|\${ESO_TENANT_ROLE_ARN}|arn:aws:iam::000000000000:role/otterworks-external-secrets-tenant-dev|g" \
  "${REPO_ROOT}/demo-platform/k8s/external-secrets/cluster-secret-stores.yaml" \
  > "${WORK}/out/cluster-secret-stores.yaml"

fail=0
# shellcheck disable=SC2016
doc_tpl='postgresql+asyncpg://u:{{ .DB_PASSWORD | urlquery | replace "+" "%20" }}@h:5432/d'
for chart in "${REPO_ROOT}"/infrastructure/helm/*/; do
  c="$(basename "${chart}")"
  helm lint "${chart}" --set image.tag=ci >/dev/null || { echo "FAIL lint (off) ${c}"; fail=1; }
  helm lint "${chart}" --set image.tag=ci --set externalSecrets.enabled=true >/dev/null \
    || { echo "FAIL lint (on) ${c}"; fail=1; }
  helm template "${c}" "${chart}" --set image.tag=ci > "${WORK}/out/${c}.off.yaml"
  helm template "${c}" "${chart}" --set image.tag=ci --set externalSecrets.enabled=true \
    --set-string "externalSecrets.templates.DOC_SVC_DATABASE_URL=${doc_tpl}" > "${WORK}/out/${c}.on.yaml"
  off="$(grep -c '^kind: ExternalSecret$' "${WORK}/out/${c}.off.yaml" || true)"
  on="$(grep -c '^kind: ExternalSecret$' "${WORK}/out/${c}.on.yaml" || true)"
  keys="$(grep -c 'secretKey:' "${WORK}/out/${c}.on.yaml" || true)"
  printf '%-22s off: ExternalSecret=%s   on: ExternalSecret=%s keys=%s\n' "${c}" "${off}" "${on}" "${keys}"
  [ "${off}" = 0 ] || { echo "FAIL ${c}: ExternalSecret rendered while disabled"; fail=1; }
  if [ "${keys}" -gt 0 ] && [ "${on}" != 1 ]; then echo "FAIL ${c}: expected 1 ExternalSecret"; fail=1; fi
done

kubeconform -strict -summary -kubernetes-version "${K8S_VERSION}" \
  -schema-location default \
  -schema-location "${WORK}/schemas/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json" \
  -skip ServiceMonitor,PrometheusRule \
  "${WORK}/out" || fail=1

exit "${fail}"
