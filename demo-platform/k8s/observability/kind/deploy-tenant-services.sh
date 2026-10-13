#!/usr/bin/env bash
# kind-only: deploy 3 core OtterWorks charts + an admin-service stand-in into the
# `otterworks-kind` tenant namespace with the shared observability wiring ON,
# the way scripts/lib/tenant-common.sh does when OBSERVABILITY_ENABLED=true.
# Prereqs: install-observability.sh --env kind, images loaded into kind
# (otterworks-{api-gateway,auth-service,document-service}:latest, otterworks-mock-admin:kind).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../../../.." && pwd)"
CTX="${CTX:-kind-otterworks-obs}"
NS=otterworks-kind
CHARTS="${REPO_ROOT}/infrastructure/helm"
PG=postgres.${NS}.svc.cluster.local
JWT=kind-only-jwt-secret-not-for-production-use-0123456789

kubectl --context "${CTX}" apply -f "${HERE}/tenant-deps.yaml"
kubectl --context "${CTX}" -n "${NS}" rollout status deploy/postgres --timeout=180s

common=(--kube-context "${CTX}" --namespace "${NS}" --set replicaCount=1
        --set networkPolicy.enabled=false --set service.type=ClusterIP --set ingress.enabled=false
        --set image.pullPolicy=Never --set observability.otel.enabled=true
        --set-string observability.otel.resourceAttributes.deployment\\.environment=kind
        --wait --timeout 5m)

helm upgrade --install auth-service "${CHARTS}/auth-service" "${common[@]}" \
  --set image.repository=otterworks-auth-service --set image.tag=latest \
  --set-string config.SPRING_DATASOURCE_URL="jdbc:postgresql://${PG}:5432/otterworks" \
  --set-string config.SPRING_DATASOURCE_USERNAME=otterworks \
  --set-string secrets.SPRING_DATASOURCE_PASSWORD=otterworks_dev \
  --set-string secrets.JWT_SECRET="${JWT}" \
  --set resources.requests.memory=512Mi --set resources.limits.memory=1024Mi --set resources.limits.cpu=1000m &
pids=($!)
helm upgrade --install document-service "${CHARTS}/document-service" "${common[@]}" \
  --set image.repository=otterworks-document-service --set image.tag=latest \
  --set-string config.DOC_SVC_DATABASE_URL="postgresql+asyncpg://otterworks:otterworks_dev@${PG}:5432/otterworks" \
  --set-string config.DOC_SVC_SNS_ENABLED=false \
  --set-string secrets.JWT_SECRET="${JWT}" &
pids+=($!)
helm upgrade --install admin-service "${CHARTS}/admin-service" "${common[@]}" \
  --set image.repository=otterworks-mock-admin --set image.tag=kind \
  --set observability.alerting.enabled=true \
  --set observability.alerting.webhookSecret.name=admin-service-secrets \
  --set-string secrets.ALERT_WEBHOOK_SECRET=kind-alert-secret &
pids+=($!)
failed=0
for pid in "${pids[@]}"; do wait "${pid}" || failed=1; done
[ "${failed}" -eq 0 ] || { echo "a helm release failed" >&2; exit 1; }
helm upgrade --install api-gateway "${CHARTS}/api-gateway" "${common[@]}" \
  --set image.repository=otterworks-api-gateway --set image.tag=latest \
  --set-string secrets.JWT_SECRET="${JWT}" \
  --set-string config.AUTH_SERVICE_URL=http://auth-service:8081 \
  --set-string config.DOCUMENT_SERVICE_URL=http://document-service:8083 \
  --set-string config.ADMIN_SERVICE_URL=http://admin-service:80
kubectl --context "${CTX}" -n "${NS}" get pods,servicemonitors,alertmanagerconfigs
