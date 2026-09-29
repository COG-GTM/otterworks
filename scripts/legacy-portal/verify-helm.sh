#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Verify the announcements/preferences/feedback Helm charts locally (nothing is installed).
#
#   1. helm lint each chart with its default values and with every optional template on
#      (image tag, DB password, ingress, servicemonitor).
#   2. helm template both renders for the EKS cluster's Kubernetes version and validate them
#      with kubeconform -strict (core schemas + the CRD catalog for ServiceMonitor).
#   3. Guardrails: the Service is ClusterIP, a LoadBalancer/NodePort type fails to render, the
#      default render has no Ingress/ServiceMonitor, and no Secret is rendered without a password.
#
# Usage: scripts/legacy-portal/verify-helm.sh
# Env:   KUBE_VERSION   Kubernetes version to validate against (default: platform/terraform
#                       cluster_version, 1.32, as 1.32.0)
# Needs: helm 3, kubeconform (schemas are downloaded from GitHub on first use)
# ------------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HELM_DIR="${REPO_ROOT}/infrastructure/helm"
SERVICES=(announcements-service preferences-service feedback-service)
TF_VERSION="$(sed -n '/variable "cluster_version"/,/}/s/.*default *= *"\([0-9.]*\)".*/\1/p' \
  "${REPO_ROOT}/platform/terraform/variables.tf")"
KUBE_VERSION="${KUBE_VERSION:-${TF_VERSION}.0}"
CRD_SCHEMAS='https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
FULL=(--set image.tag=verify --set database.password=verify
      --set ingress.enabled=true --set monitoring.enabled=true)
TEMPLATE=(--kube-version "${KUBE_VERSION}" --api-versions monitoring.coreos.com/v1)

for bin in helm kubeconform; do
  command -v "${bin}" >/dev/null || { echo "${bin} not found" >&2; exit 1; }
done

FAILED=0
SUMMARY=()
check() {
  local label="$1"; shift
  if "$@" >/dev/null 2>"${WORK_DIR}/err"; then
    SUMMARY+=("PASS ${label}")
  else
    SUMMARY+=("FAIL ${label}: $(tail -3 "${WORK_DIR}/err" | tr '\n' ' ')")
    FAILED=1
  fi
}
kinds() { grep -E '^kind: ' | awk '{print $2}' | sort | tr '\n' ' '; }
# shellcheck disable=SC2317  # invoked indirectly through check
render_fails() { ! helm template x "$1" --set image.tag=verify "${@:2}"; }
# shellcheck disable=SC2317  # invoked indirectly through check
lacks_kinds() { ! grep -qE "^kind: ($1)$" "$2"; }
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/legacy-portal-helm.XXXXXX")"
trap 'rm -rf "${WORK_DIR}"' EXIT

for svc in "${SERVICES[@]}"; do
  chart="${HELM_DIR}/${svc}"
  check "${svc}: helm lint (defaults)" helm lint --strict "${chart}"
  check "${svc}: helm lint (all templates on)" helm lint --strict "${chart}" "${FULL[@]}"

  helm template "${svc}" "${chart}" "${TEMPLATE[@]}" "${FULL[@]}" >"${WORK_DIR}/${svc}-full.yaml"
  helm template "${svc}" "${chart}" "${TEMPLATE[@]}" --set image.tag=verify >"${WORK_DIR}/${svc}-default.yaml"
  for render in full default; do
    check "${svc}: kubeconform ${render} render (k8s ${KUBE_VERSION}): $(kinds <"${WORK_DIR}/${svc}-${render}.yaml")" \
      kubeconform -strict -summary -kubernetes-version "${KUBE_VERSION}" \
        -schema-location default -schema-location "${CRD_SCHEMAS}" "${WORK_DIR}/${svc}-${render}.yaml"
  done

  check "${svc}: Service is ClusterIP" grep -qx '  type: ClusterIP' "${WORK_DIR}/${svc}-full.yaml"
  for type in LoadBalancer NodePort; do
    check "${svc}: service.type=${type} is rejected" \
      render_fails "${chart}" --set service.type="${type}"
  done
  check "${svc}: default render has no Ingress, ServiceMonitor or Secret" \
    lacks_kinds 'Ingress|ServiceMonitor|Secret' "${WORK_DIR}/${svc}-default.yaml"
done

echo "=== legacy-portal helm verification (kubernetes ${KUBE_VERSION}) ==="
printf '%s\n' "${SUMMARY[@]}"
exit "${FAILED}"
