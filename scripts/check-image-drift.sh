#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Fails when image / service naming drifts between the places that must agree:
#   - every chart's image.repository is [<registry>/]otterworks/<chart-name>
#     (ECR_PREFIX="otterworks/" in scripts/lib/tenant-common.sh and
#     platform/terraform/variables.tf; docker-build.yml pushes the same path)
#   - the chart set == Terraform's ECR service_names == tenant-common.sh's
#     ALL_SERVICES == the services in every GitOps environment
#   - no tracked file still references the legacy workshop/otterworks-<svc> path
#   - the static external-dns manifest uses the pinned EXTERNAL_DNS_VERSION
#   - no chart default renders a LoadBalancer Service (when helm is available)
# No dependencies beyond bash/awk/grep/git (helm optional). Run from anywhere.
# ------------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
errors=0
err() { echo "DRIFT: $*" >&2; errors=$((errors + 1)); }
sorted() { tr ' ' '\n' | grep -v '^$' | sort | tr '\n' ' '; }

# 1. chart image.repository ---------------------------------------------------
charts=()
for dir in infrastructure/helm/*/; do
  [ -f "${dir}Chart.yaml" ] || continue
  chart="$(basename "${dir}")"
  charts+=("${chart}")
  repo="$(awk '/^image:/{f=1;next} f&&/^[^ #]/{exit} f&&$1=="repository:"{print $2;exit}' "${dir}values.yaml")"
  if [ -z "${repo}" ]; then
    err "${dir}values.yaml: no image.repository"
  elif ! [[ "${repo}" =~ ^([^/]+/)?otterworks/${chart}$ ]]; then
    err "${dir}values.yaml: image.repository '${repo}' should end in otterworks/${chart}"
  else
    echo "ok  ${chart}: ${repo}"
  fi
done
[ "${#charts[@]}" -gt 0 ] || err "no charts found under infrastructure/helm"
chart_set="$(echo "${charts[*]}" | sorted)"

# 2. service sets agree --------------------------------------------------------
tf_set="$(awk '/service_names = \[/{f=1;next} f&&/\]/{exit} f{gsub(/[",]/,"");print $1}' platform/terraform/main.tf | tr '\n' ' ' | sorted)"
[ "${tf_set}" = "${chart_set}" ] || err "platform/terraform/main.tf service_names (${tf_set}) != charts (${chart_set})"

tenant_set="$(bash -c 'source <(sed -n "/^BACKEND_SERVICES=(/,/^ALL_SERVICES=/p" scripts/lib/tenant-common.sh); echo "${ALL_SERVICES[*]}"' | sorted)"
[ "${tenant_set}" = "${chart_set}" ] || err "scripts/lib/tenant-common.sh ALL_SERVICES (${tenant_set}) != charts (${chart_set})"

grep -q '^ECR_PREFIX="otterworks/"' scripts/lib/tenant-common.sh || err "scripts/lib/tenant-common.sh: ECR_PREFIX is not \"otterworks/\""
grep -A3 'variable "ecr_prefix"' platform/terraform/variables.tf | grep -q 'default *= *"otterworks/"' \
  || err "platform/terraform/variables.tf: ecr_prefix default is not \"otterworks/\""

for envdir in deploy/gitops/envs/*/; do
  [ -d "${envdir}services" ] || continue
  env_set="$(for f in "${envdir}services/"*.yaml; do basename "${f}" .yaml; done | tr '\n' ' ' | sorted)"
  [ "${env_set}" = "${chart_set}" ] || err "${envdir}services (${env_set}) != charts (${chart_set})"
done

# 3. legacy repository path ---------------------------------------------------
# docs/SDLC-COVERAGE.md is a self-assessment that describes the drift itself.
legacy="$(git grep -nE 'workshop/otterworks[-/]' -- ':!docs/SDLC-COVERAGE.md' ':!scripts/check-image-drift.sh' || true)"
[ -z "${legacy}" ] || err "legacy workshop/otterworks image path still referenced:
${legacy}"

# 4. external-dns pin ---------------------------------------------------------
# shellcheck source=../demo-platform/k8s/platform-addons.versions.env
source demo-platform/k8s/platform-addons.versions.env
grep -q "image: registry.k8s.io/external-dns/external-dns:${EXTERNAL_DNS_VERSION}\$" demo-platform/k8s/dns-tls/external-dns.yaml \
  || err "demo-platform/k8s/dns-tls/external-dns.yaml image is not pinned to ${EXTERNAL_DNS_VERSION}"

# 5. LoadBalancer guard -------------------------------------------------------
if command -v helm >/dev/null 2>&1; then
  for chart in "${charts[@]}"; do
    if helm template guard "infrastructure/helm/${chart}" --set image.tag=drift-check 2>/dev/null \
        | grep -qE '^\s*type:\s*LoadBalancer'; then
      err "infrastructure/helm/${chart} renders a LoadBalancer Service (only shared ingress-nginx may)"
    fi
  done
fi

if [ "${errors}" -gt 0 ]; then
  echo "check-image-drift: ${errors} problem(s)" >&2
  exit 1
fi
echo "check-image-drift: ${#charts[@]} charts consistent with otterworks/<service>"
