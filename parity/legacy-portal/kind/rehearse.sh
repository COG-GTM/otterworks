#!/usr/bin/env bash
# Local-only rehearsal of the EKS rollout: installs the three extracted-service
# charts from infrastructure/helm into a kind cluster, with locally built images
# (never pushed) and an in-cluster PostgreSQL in the post-handover layout, then
# replays the golden transcripts through `kubectl port-forward`.
#
#   make parity-kind            # KEEP_CLUSTER=1 to leave the cluster running
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
HERE="${REPO_ROOT}/parity/legacy-portal"
CLUSTER="${KIND_CLUSTER:-legacy-portal}"
NS="${KIND_NAMESPACE:-legacy-portal}"
CTX="kind-${CLUSTER}"
SERVICES=(announcements-service user-preferences-service feedback-service)
declare -A PORT=([announcements-service]=8092 [user-preferences-service]=8093 [feedback-service]=8094)
declare -A ROLE=([announcements-service]=announcements_svc [user-preferences-service]=user_preferences_svc [feedback-service]=feedback_svc)
declare -A CONTEXT=([announcements-service]=announcements [user-preferences-service]=user-preferences [feedback-service]=feedback)
LOCAL_PORT_BASE=28000

log() { echo "[kind] $*"; }

for bin in docker kind kubectl helm; do
  command -v "$bin" >/dev/null || { echo "$bin not found" >&2; exit 1; }
done

if ! kind get clusters | grep -qx "$CLUSTER"; then
  log "creating cluster $CLUSTER"
  kind create cluster --name "$CLUSTER" --wait 120s
fi

log "building images locally"
MAVEN_SETTINGS="${MAVEN_SETTINGS:-$([ -f "$HOME/.m2/settings.xml" ] && echo "$HOME/.m2/settings.xml" || echo /dev/null)}" \
  docker compose -f "${HERE}/docker-compose.services.yml" build
docker image inspect postgres:15-alpine >/dev/null 2>&1 || docker pull postgres:15-alpine
# `kind load docker-image` imports with --all-platforms, which fails for images
# Docker's containerd store holds for one platform only; import just this one.
load_image() {
  docker save "$1" | docker exec -i "${CLUSTER}-control-plane" \
    ctr --namespace=k8s.io images import --platform "linux/$(docker version -f '{{.Server.Arch}}')" --snapshotter=overlayfs - >/dev/null
}
load_image postgres:15-alpine
for svc in "${SERVICES[@]}"; do load_image "otterworks/${svc}:local"; done

# Transcripts carry generated IDs, so every rehearsal starts from an empty database.
kubectl --context "$CTX" delete namespace "$NS" --ignore-not-found --wait >/dev/null
kubectl --context "$CTX" create namespace "$NS" --dry-run=client -o yaml | kubectl --context "$CTX" apply -f - >/dev/null
kubectl --context "$CTX" -n "$NS" create configmap legacy-portal-pg-init \
  --from-file="${HERE}/postgres/00-legacy-layout.sql" --from-file="${HERE}/postgres/10-handover.sql" \
  --dry-run=client -o yaml | kubectl --context "$CTX" apply -f - >/dev/null
kubectl --context "$CTX" -n "$NS" apply -f "${HERE}/kind/postgres.yaml" >/dev/null
kubectl --context "$CTX" -n "$NS" rollout status deploy/legacyportal-db --timeout=120s

# The /health banner is operator branding (the chart defaults it to "eks"); pin it
# to the value the golden transcripts were recorded with.
for svc in "${SERVICES[@]}"; do
  log "helm upgrade --install $svc"
  helm upgrade --install "$svc" "${REPO_ROOT}/infrastructure/helm/${svc}" \
    --kube-context "$CTX" -n "$NS" \
    --set image.repository="otterworks/${svc}" --set image.tag=local --set image.pullPolicy=Never \
    --set replicaCount=1 --set networkPolicy.enabled=false \
    --set-string config.PORTAL_ENVIRONMENT=on-prem \
    --set-string config.SPRING_DATASOURCE_URL="jdbc:postgresql://legacyportal-db:5432/legacyportal" \
    --set-string config.SPRING_DATASOURCE_USERNAME="${ROLE[$svc]}" \
    --set-string secrets.SPRING_DATASOURCE_PASSWORD="${ROLE[$svc]}" \
    --wait --timeout 5m
done
kubectl --context "$CTX" -n "$NS" get pods -o wide

PIDS=()
cleanup() {
  for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done
  if [ "${KEEP_CLUSTER:-0}" != "1" ]; then kind delete cluster --name "$CLUSTER" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

TARGET_ARGS=()
i=0
for svc in "${SERVICES[@]}"; do
  lp=$((LOCAL_PORT_BASE + i)); i=$((i + 1))
  kubectl --context "$CTX" -n "$NS" port-forward "svc/${svc}" "${lp}:${PORT[$svc]}" >/dev/null 2>&1 &
  PIDS+=($!)
  TARGET_ARGS+=(--target "${CONTEXT[$svc]}=http://127.0.0.1:${lp}")
done
for _ in $(seq 1 30); do
  ok=1
  for j in 0 1 2; do curl -fs "http://127.0.0.1:$((LOCAL_PORT_BASE + j))/actuator/health/readiness" >/dev/null || ok=0; done
  [ "$ok" = 1 ] && break
  sleep 1
done

cd "$HERE"
uv run --no-project --with pyyaml==6.0.2 python -m harness.run verify --label kind "${TARGET_ARGS[@]}"
