#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Install the SHARED observability stack into namespace `monitoring` (once per
# cluster, never per tenant). See docs/OBSERVABILITY.md and k8s/observability/.
#
#   kube-prometheus-stack  Prometheus Operator, Prometheus, Alertmanager, Grafana
#   + generated/           OtterWorks PrometheusRules and Grafana dashboards
#   jaeger                 trace store + UI (all-in-one, in-memory)
#   otel-collector         OTLP endpoint for every service chart
#   fluent-bit             DaemonSet shipping container logs to CloudWatch
#
# Every Service is ClusterIP; Grafana/Jaeger are reached through the shared
# ingress-nginx (env/<env>/ overlays) or `kubectl port-forward`.
#
# Secrets are never passed on argv or kept in git. They are read from the
# environment and applied as Secrets on stdin:
#   ALERT_PLATFORM_WEBHOOK_URL    platform-level admin-service ingest URL
#                                 (https://.../api/v1/admin/alerts/ingest)
#   ALERT_PLATFORM_WEBHOOK_TOKEN  its ALERT_WEBHOOK_SECRET (sent as Bearer)
#   ALERT_SLACK_WEBHOOK_URL       Slack incoming webhook (optional)
#   GRAFANA_ADMIN_PASSWORD        default: random on first install, then kept
#   JAEGER_BASIC_AUTH             htpasswd line for the Jaeger ingress (dev)
#   FLUENT_BIT_ROLE_ARN           IRSA role (terraform output fluent_bit_role_arn)
#
# Idempotent. Usage:
#   install-observability.sh --env kind                       # local kind cluster
#   install-observability.sh --env dev --context <ctx> --yes  # shared EKS (needs sign-off)
#   install-observability.sh --env dev --template /tmp/out    # render only, no cluster
# ------------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
OBS="${REPO_ROOT}/demo-platform/k8s/observability"
NS=monitoring
ENVIRONMENT=""
CONTEXT=""
TEMPLATE_DIR=""
ASSUME_YES=false

log()  { echo "[observability] $*"; }
fail() { echo "[observability] ERROR: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENVIRONMENT="$2"; shift 2 ;;
    --context) CONTEXT="$2"; shift 2 ;;
    --template) TEMPLATE_DIR="$2"; shift 2 ;;
    --yes) ASSUME_YES=true; shift ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) fail "unknown argument: $1" ;;
  esac
done
[ -n "${ENVIRONMENT}" ] || fail "--env is required (an overlay directory under ${OBS}/env)"
[ -d "${OBS}/env/${ENVIRONMENT}" ] || fail "no overlay directory ${OBS}/env/${ENVIRONMENT}"

# shellcheck disable=SC1091  # pinned chart versions
source "${OBS}/versions.env"

command -v helm >/dev/null 2>&1 || fail "helm is required"
python3 "${OBS}/generate.py" --check >/dev/null || fail "k8s/observability/generated is stale; run generate.py"

values_for() {  # <component> -> -f base [-f overlay]
  local c=$1
  printf -- '-f\n%s\n' "${OBS}/${c}.values.yaml"
  if [ -f "${OBS}/env/${ENVIRONMENT}/${c}.yaml" ]; then
    printf -- '-f\n%s\n' "${OBS}/env/${ENVIRONMENT}/${c}.yaml"
  fi
}

# release|repo-name|repo-url|chart|version|component
RELEASES=(
  "kps|prometheus-community|https://prometheus-community.github.io/helm-charts|kube-prometheus-stack|${KUBE_PROMETHEUS_STACK_VERSION}|kube-prometheus-stack"
  "jaeger|jaegertracing|https://jaegertracing.github.io/helm-charts|jaeger|${JAEGER_VERSION}|jaeger"
  "otel-collector|open-telemetry|https://open-telemetry.github.io/opentelemetry-helm-charts|opentelemetry-collector|${OTEL_COLLECTOR_VERSION}|otel-collector"
  "fluent-bit|fluent|https://fluent.github.io/helm-charts|fluent-bit|${FLUENT_BIT_VERSION}|fluent-bit"
)

for r in "${RELEASES[@]}"; do
  IFS='|' read -r _ repo url _ _ _ <<<"$r"
  helm repo add "${repo}" "${url}" --force-update >/dev/null
done
helm repo update >/dev/null

extra_args_for() {  # <release>
  case "$1" in
    fluent-bit)
      printf -- '--set-file\nconfig.customParsers=%s\n' "${REPO_ROOT}/observability/logging/parsers.conf"
      if [ -n "${FLUENT_BIT_ROLE_ARN:-}" ]; then
        printf -- '--set-string\nserviceAccount.annotations.eks\\.amazonaws\\.com/role-arn=%s\n' "${FLUENT_BIT_ROLE_ARN}"
      fi ;;
  esac
}

# ---------- render-only mode (CI / review) ----------
if [ -n "${TEMPLATE_DIR}" ]; then
  mkdir -p "${TEMPLATE_DIR}"
  for r in "${RELEASES[@]}"; do
    IFS='|' read -r rel repo _ chart ver comp <<<"$r"
    mapfile -t vals < <(values_for "${comp}")
    mapfile -t extra < <(extra_args_for "${rel}")
    helm template "${rel}" "${repo}/${chart}" --version "${ver}" --namespace "${NS}" \
      --kube-version 1.31.0 --api-versions monitoring.coreos.com/v1 \
      "${vals[@]}" "${extra[@]}" > "${TEMPLATE_DIR}/${rel}.yaml"
    log "rendered ${rel} (${chart} ${ver}) -> ${TEMPLATE_DIR}/${rel}.yaml"
  done
  cp "${OBS}"/generated/*.yaml "${TEMPLATE_DIR}/"
  exit 0
fi

# ---------- install mode ----------
command -v kubectl >/dev/null 2>&1 || fail "kubectl is required"
[ -n "${CONTEXT}" ] || CONTEXT="$(kubectl config current-context)"
KCTL=(kubectl --context "${CONTEXT}")
HELM_CTX=(--kube-context "${CONTEXT}")
if [ "${ENVIRONMENT}" != kind ] && [ "${ASSUME_YES}" != true ]; then
  fail "refusing to install into '${CONTEXT}' (env ${ENVIRONMENT}) without --yes. This is a SHARED cluster-wide install; get sign-off first (AGENTS.md)."
fi
log "installing into context ${CONTEXT} (env ${ENVIRONMENT})"

"${KCTL[@]}" create namespace "${NS}" --dry-run=client -o yaml | "${KCTL[@]}" apply -f - >/dev/null
# Prometheus/Alertmanager select namespaces labelled platform/team in (otterworks, platform).
"${KCTL[@]}" label namespace "${NS}" platform/team=platform --overwrite >/dev/null

secret_from_env() {  # <secret-name> <key>=<ENV_VAR>... ; values travel via files, never argv
  local name=$1; shift
  local tmp; tmp="$(mktemp -d)"
  local args=() kv key var
  for kv in "$@"; do
    key="${kv%%=*}"; var="${kv#*=}"
    printf '%s' "${!var:-}" > "${tmp}/${key}"
    args+=("--from-file=${key}=${tmp}/${key}")
  done
  "${KCTL[@]}" -n "${NS}" create secret generic "${name}" "${args[@]}" --dry-run=client -o yaml \
    | "${KCTL[@]}" apply -f - >/dev/null
  rm -rf "${tmp}"
}

# Re-running without the variables keeps the existing receivers Secret.
if [ -n "${ALERT_PLATFORM_WEBHOOK_URL:-}${ALERT_PLATFORM_WEBHOOK_TOKEN:-}${ALERT_SLACK_WEBHOOK_URL:-}" ] \
   || ! "${KCTL[@]}" -n "${NS}" get secret alertmanager-otterworks-receivers >/dev/null 2>&1; then
  secret_from_env alertmanager-otterworks-receivers \
    platform-webhook-url=ALERT_PLATFORM_WEBHOOK_URL \
    platform-webhook-token=ALERT_PLATFORM_WEBHOOK_TOKEN \
    slack-webhook-url=ALERT_SLACK_WEBHOOK_URL
  [ -n "${ALERT_PLATFORM_WEBHOOK_URL:-}" ] || log "ALERT_PLATFORM_WEBHOOK_URL unset: the platform-admin receiver will fail deliveries (tenant AlertmanagerConfigs still work)"
fi

if [ -n "${GRAFANA_ADMIN_PASSWORD:-}" ] || ! "${KCTL[@]}" -n "${NS}" get secret grafana-admin >/dev/null 2>&1; then
  GRAFANA_ADMIN_USER="${GRAFANA_ADMIN_USER:-admin}"
  GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')}"
  secret_from_env grafana-admin admin-user=GRAFANA_ADMIN_USER admin-password=GRAFANA_ADMIN_PASSWORD
  log "grafana-admin Secret written (read it back with: kubectl -n ${NS} get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d)"
fi
if [ -n "${JAEGER_BASIC_AUTH:-}" ]; then
  secret_from_env jaeger-basic-auth auth=JAEGER_BASIC_AUTH
fi

install_release() {  # <entry>
  local rel repo chart ver comp
  IFS='|' read -r rel repo _ chart ver comp <<<"$1"
  local vals extra
  mapfile -t vals < <(values_for "${comp}")
  mapfile -t extra < <(extra_args_for "${rel}")
  log "helm upgrade --install ${rel} ${repo}/${chart}@${ver}"
  helm "${HELM_CTX[@]}" upgrade --install "${rel}" "${repo}/${chart}" --version "${ver}" \
    --namespace "${NS}" "${vals[@]}" "${extra[@]}" --wait --timeout 10m
}

install_release "${RELEASES[0]}"   # CRDs first
log "applying OtterWorks PrometheusRules + Grafana dashboards"
"${KCTL[@]}" apply --server-side -f "${OBS}/generated/" >/dev/null
for r in "${RELEASES[@]:1}"; do install_release "$r"; done

# AGENTS.md: the shared ingress-nginx controller is the ONLY LoadBalancer Service.
if "${KCTL[@]}" -n "${NS}" get svc -o jsonpath='{range .items[*]}{.spec.type}{"\n"}{end}' | grep -qx LoadBalancer; then
  fail "a LoadBalancer Service exists in ${NS}; remove it (only ingress-nginx may own one)"
fi
log "done. Grafana: kubectl -n ${NS} port-forward svc/kps-grafana 3000:80 | Jaeger: kubectl -n ${NS} port-forward svc/jaeger 16686:16686"
