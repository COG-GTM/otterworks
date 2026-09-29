#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Install the announcements/preferences/feedback charts on a throwaway local kind cluster, wired
# the way deploy-tenant.sh wires a tenant, and replay the legacy-portal parity suite through it.
# Nothing is pushed or deployed anywhere: no ECR, no AWS, no remote kube context.
#
#   1. Build the three images locally (docker buildx bake, context services/, each service's own
#      Dockerfile). The builder's maven base image is overlaid with the host Maven repository and
#      settings.xml as named build contexts, so dependencies resolve from the local cache and its
#      mirror instead of Maven Central (which rate-limits with 429).
#   2. Create kind cluster <KIND_CLUSTER> (kubeconfig private to this run, context kind-<name>)
#      and `kind load` the images plus the PostgreSQL images; nothing is pulled by the node.
#   3. In namespace otterworks-<TENANT_ID>, run a throwaway PostgreSQL 15 (the RDS engine) with a
#      non-superuser admin role (as the RDS master user) and the tenant database otterworks_<ID>.
#   4. Per run: create the per-service roles and schemas with the SQL deploy-tenant.sh generates
#      (portal_db_setup_sql, same Job shape and psql 16 image), render each chart with the
#      arguments build_helm_args produces for a tenant with portal roles (ClusterIP, replicas 1,
#      networkPolicy off, per-service role and password), validate the render with kubeconform,
#      `helm install --wait`, check the pods are Ready and each schema is owned by and connected
#      as its role only, replay tests/parity/legacy_portal through `kubectl port-forward`, then
#      uninstall and drop the schemas so the next run starts empty.
#   5. Delete the cluster and print a summary usable as commit trailers / ticket note.
#
# Usage:
#   scripts/legacy-portal/verify-kind.sh [--runs N] [--skip-image-build] [--keep-cluster]
#   --skip-image-build  use the existing otterworks-<service>:<IMAGE_TAG> images
#   --keep-cluster      leave the cluster (and the last run's releases) up for inspection;
#                       its kubeconfig path is printed
# Env:
#   KUBE_CONTEXT      context to use; anything but kind-* is refused (default kind-<KIND_CLUSTER>)
#   KIND_CLUSTER      cluster name (default otterworks-portal-verify); must not exist yet
#   KIND_NODE_IMAGE   node image (default kindest/node v1.32.5, the EKS cluster_version)
#   TENANT_ID         tenant the install stands in for (default kind -> otterworks-kind)
#   IMAGE_TAG         local image tag (default verify-kind)
#   MAVEN_REPO        Maven repository used as build context (default ~/.m2/repository)
#   MAVEN_SETTINGS    settings.xml copied next to it (default ~/.m2/settings.xml, if present)
#   ANNOUNCEMENTS_PORT / PREFERENCES_PORT / FEEDBACK_PORT
#                     local port-forward ports (default 18096 / 18097 / 18098)
# Needs: docker (buildx), kind, kubectl, helm 3, kubeconform, jq, openssl, uv
# ------------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HELM_DIR="${REPO_ROOT}/infrastructure/helm"
PARITY_DIR="${REPO_ROOT}/tests/parity/legacy_portal"
SERVICES=(announcements-service preferences-service feedback-service)

RUNS=2
SKIP_IMAGE_BUILD=0
KEEP_CLUSTER=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --runs) RUNS="$2"; shift 2 ;;
    --skip-image-build) SKIP_IMAGE_BUILD=1; shift ;;
    --keep-cluster) KEEP_CLUSTER=1; shift ;;
    -h|--help) sed -n '2,42p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ "${RUNS}" =~ ^[1-9][0-9]*$ ]] || { echo "--runs must be a positive integer" >&2; exit 2; }

CLUSTER="${KIND_CLUSTER:-otterworks-portal-verify}"
CONTEXT="${KUBE_CONTEXT:-kind-${CLUSTER}}"
if [[ "${CONTEXT}" != kind-* ]]; then
  echo "refusing kube context '${CONTEXT}': only local kind-* contexts are allowed" >&2
  exit 2
fi
CLUSTER="${CONTEXT#kind-}"
[[ "${CLUSTER}" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || { echo "invalid kind cluster name '${CLUSTER}'" >&2; exit 2; }
NODE_IMAGE="${KIND_NODE_IMAGE:-kindest/node:v1.32.5@sha256:e3b2327e3a5ab8c76f5ece68936e4cafaa82edf58486b769727ab0b3b97a5b0d}"
IMAGE_TAG="${IMAGE_TAG:-verify-kind}"
MAVEN_REPO="${MAVEN_REPO:-${HOME}/.m2/repository}"
MAVEN_SETTINGS="${MAVEN_SETTINGS:-${HOME}/.m2/settings.xml}"
PG_SERVER_IMAGE=postgres:15-alpine
PG_CLIENT_IMAGE=postgres:16-alpine

for bin in docker kind kubectl helm kubeconform jq openssl uv curl; do
  command -v "${bin}" >/dev/null || { echo "${bin} not found" >&2; exit 1; }
done

# Nothing below may reach AWS or any cluster other than the one this run creates.
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE AWS_DEFAULT_PROFILE
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/legacy-portal-kind.XXXXXX")"
export KUBECONFIG="${WORK_DIR}/kubeconfig"

# shellcheck source=scripts/lib/tenant-common.sh
source "${REPO_ROOT}/scripts/lib/tenant-common.sh"

# Tenant wiring as deploy-tenant.sh sets it, with the in-cluster PostgreSQL standing in for RDS.
NS="$(tenant_namespace "${TENANT_ID:-kind}")"
T_DB_NAME="$(tenant_db_name "${TENANT_ID:-kind}")"
RDS_HOST="postgres.${NS}.svc.cluster.local"
RDS_PORT=5432
DB_USER=otterworks_admin
DB_PASSWORD="$(openssl rand -hex 24)"
# shellcheck disable=SC2034  # read by resolve_db_endpoint
DB_VIA_PGBOUNCER=false
resolve_db_endpoint
# shellcheck disable=SC2034  # read by build_helm_args
IRSA_JSON='{}' JWT_SECRET="" T_WIRE_EVENTING=false T_REDIS_HOST="redis" T_MEILI_URL="http://meilisearch:7700"
T_PORTAL_DB_ROLES=false
PG_SUPERUSER_PASSWORD="$(openssl rand -hex 24)"

PF_PIDS=()
CLUSTER_CREATED=0
SUMMARY=()
FAILED=0

say() { echo "[verify-kind] $*" >&2; }
record() { SUMMARY+=("$1"); say "$1"; }

# Every cluster call goes through these: the private kubeconfig must hold exactly the kind
# context of this run, and its API server must be local.
require_kind_context() {
  local current server
  current="$(command kubectl config current-context 2>/dev/null || true)"
  server="$(command kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}' 2>/dev/null || true)"
  if [[ "${current}" != "${CONTEXT}" || "${current}" != kind-* || "${server}" != https://127.0.0.1:* ]]; then
    say "refusing: current context '${current}' (${server:-no server}) is not the local ${CONTEXT}"
    exit 2
  fi
}
kubectl() { require_kind_context; command kubectl --context "${CONTEXT}" "$@"; }
helm() { require_kind_context; command helm --kube-context "${CONTEXT}" "$@"; }

stop_port_forwards() {
  local pid
  for pid in "${PF_PIDS[@]:-}"; do
    [[ -n "${pid}" ]] || continue
    kill "${pid}" 2>/dev/null || true
    wait "${pid}" 2>/dev/null || true
  done
  PF_PIDS=()
}

cleanup() {
  stop_port_forwards
  if [[ "${CLUSTER_CREATED}" == 1 ]]; then
    if [[ "${KEEP_CLUSTER}" == 1 ]]; then
      cp "${KUBECONFIG}" "${HOME}/.kube-${CLUSTER}.config" 2>/dev/null || true
      say "cluster ${CLUSTER} kept; KUBECONFIG=${HOME}/.kube-${CLUSTER}.config, delete with: kind delete cluster --name ${CLUSTER}"
    else
      kind delete cluster --name "${CLUSTER}" --kubeconfig "${KUBECONFIG}" >/dev/null 2>&1 || true
    fi
  fi
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

service_port() { echo "${CONTAINER_PORT[$1]}"; }
local_port() {
  local stem="${1%-service}" var default
  var="$(echo "${stem}" | tr '[:lower:]' '[:upper:]')_PORT"
  default=$(( $(service_port "$1") + 10000 ))
  echo "${!var:-${default}}"
}

build_images() {
  local conf="${WORK_DIR}/m2conf" bake="${WORK_DIR}/portal.bake.hcl" svc
  [[ -d "${MAVEN_REPO}" ]] || { say "no Maven repository at ${MAVEN_REPO}"; return 1; }
  mkdir -p "${conf}"
  if [[ -f "${MAVEN_SETTINGS}" ]]; then cp "${MAVEN_SETTINGS}" "${conf}/settings.xml"; else echo '<settings/>' >"${conf}/settings.xml"; fi
  cat >"${bake}" <<HCL
# The services' builder stage starts FROM maven:3.9-eclipse-temurin-17; this target replaces
# that image with one that already holds the host Maven repository and settings.
target "maven-cache" {
  dockerfile-inline = <<-DOCKERFILE
    FROM maven:3.9-eclipse-temurin-17
    COPY --from=m2settings settings.xml /root/.m2/settings.xml
    COPY --from=m2 . /root/.m2/repository/
  DOCKERFILE
  contexts = {
    m2 = "${MAVEN_REPO}"
    m2settings = "${conf}"
  }
}
group "default" {
  targets = [$(printf '"%s", ' "${SERVICES[@]}" | sed 's/, $//')]
}
HCL
  for svc in "${SERVICES[@]}"; do
    cat >>"${bake}" <<HCL
target "${svc}" {
  context = "${REPO_ROOT}/services"
  dockerfile = "${svc}/Dockerfile"
  contexts = { "maven:3.9-eclipse-temurin-17" = "target:maven-cache" }
  tags = ["otterworks-${svc}:${IMAGE_TAG}"]
  output = ["type=docker"]
}
HCL
  done
  local cmd="docker buildx bake (context services/, <service>/Dockerfile, Maven cache as named context)"
  if docker buildx bake --allow "fs.read=${MAVEN_REPO}" --allow "fs.read=${conf}" -f "${bake}" --progress plain \
      >"${WORK_DIR}/image-build.log" 2>&1; then
    record "PASS images: ${cmd} - built $(printf 'otterworks-%s:'"${IMAGE_TAG}"' ' "${SERVICES[@]}" | sed 's/ $//'), $(grep -c 'Downloaded from central:' "${WORK_DIR}/image-build.log" || true) artifacts from Maven Central"
  else
    tail -60 "${WORK_DIR}/image-build.log" >&2
    record "FAIL images: ${cmd}"
    return 1
  fi
}

create_cluster() {
  if kind get clusters 2>/dev/null | grep -qx "${CLUSTER}"; then
    say "kind cluster ${CLUSTER} already exists; delete it or set KIND_CLUSTER"
    return 1
  fi
  CLUSTER_CREATED=1
  kind create cluster --name "${CLUSTER}" --image "${NODE_IMAGE}" --kubeconfig "${KUBECONFIG}" \
    --wait 120s >"${WORK_DIR}/kind.log" 2>&1 || { cat "${WORK_DIR}/kind.log" >&2; return 1; }
  require_kind_context
  local -a images=()
  local img svc platform
  for svc in "${SERVICES[@]}"; do images+=("otterworks-${svc}:${IMAGE_TAG}"); done
  kind load docker-image --name "${CLUSTER}" "${images[@]}" >>"${WORK_DIR}/kind.log" 2>&1 \
    || { cat "${WORK_DIR}/kind.log" >&2; return 1; }
  # A pulled multi-arch image only has this platform's layers locally, and with the containerd
  # image store `kind load docker-image` exports the whole index; save just this platform.
  platform="$(docker version --format '{{.Server.Os}}/{{.Server.Arch}}')"
  for img in "${PG_SERVER_IMAGE}" "${PG_CLIENT_IMAGE}"; do
    docker image inspect "${img}" >/dev/null 2>&1 || docker pull -q --platform "${platform}" "${img}" >/dev/null
    docker save --platform "${platform}" -o "${WORK_DIR}/image.tar" "${img}"
    kind load image-archive --name "${CLUSTER}" "${WORK_DIR}/image.tar" >>"${WORK_DIR}/kind.log" 2>&1 \
      || { cat "${WORK_DIR}/kind.log" >&2; return 1; }
    rm -f "${WORK_DIR}/image.tar"
  done
  record "PASS cluster: kind create cluster ${CLUSTER} ($(kubectl version -o json | jq -r .serverVersion.gitVersion)), context ${CONTEXT}; kind load docker-image ${images[*]}; ${PG_SERVER_IMAGE} ${PG_CLIENT_IMAGE} (${platform})"
}

pg_admin_sql() {
  kubectl -n "${NS}" exec -i deploy/postgres -- env PGOPTIONS="-c client_min_messages=warning" \
    psql -v ON_ERROR_STOP=1 -U postgres -d "$1" -Atq
}

# PostgreSQL 15 (the RDS engine_version) with a superuser that only this script uses, and an admin
# role without SUPERUSER that owns the tenant database, like the RDS master user.
start_postgres() {
  local b64
  kubectl create namespace "${NS}" >/dev/null
  b64="$(printf '%s' "${PG_SUPERUSER_PASSWORD}" | base64 | tr -d '\n')"
  kubectl -n "${NS}" apply -f - >/dev/null <<YAML
apiVersion: v1
kind: Secret
metadata:
  name: postgres-superuser
type: Opaque
data:
  POSTGRES_PASSWORD: ${b64}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
spec:
  replicas: 1
  selector: { matchLabels: { app: postgres } }
  template:
    metadata: { labels: { app: postgres } }
    spec:
      containers:
        - name: postgres
          image: ${PG_SERVER_IMAGE}
          imagePullPolicy: Never
          env:
            - { name: POSTGRES_USER, value: postgres }
            - { name: POSTGRES_DB, value: otterworks }
            - name: POSTGRES_PASSWORD
              valueFrom: { secretKeyRef: { name: postgres-superuser, key: POSTGRES_PASSWORD } }
          ports: [{ containerPort: 5432 }]
          readinessProbe:
            exec: { command: ["pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-d", "otterworks"] }
            periodSeconds: 2
---
apiVersion: v1
kind: Service
metadata:
  name: postgres
spec:
  type: ClusterIP
  selector: { app: postgres }
  ports: [{ port: 5432, targetPort: 5432 }]
YAML
  kubectl -n "${NS}" rollout status deploy/postgres --timeout=120s >/dev/null
  # The admin password reaches psql on stdin, never on an argv.
  pg_admin_sql otterworks >/dev/null <<SQL
CREATE ROLE ${DB_USER} WITH LOGIN CREATEDB CREATEROLE PASSWORD '${DB_PASSWORD}';
CREATE DATABASE ${T_DB_NAME} OWNER ${DB_USER};
ALTER DATABASE ${T_DB_NAME} SET search_path = public, analytics;
SQL
  record "PASS postgres: ${PG_SERVER_IMAGE} in ${NS}, admin role ${DB_USER} (NOSUPERUSER, CREATEDB, CREATEROLE) owns ${T_DB_NAME}"
}

# deploy-tenant.sh create_portal_db_roles: the same generated SQL, Secrets and Job, run as the
# admin role against the tenant database.
create_portal_db_roles() {
  local service env_name env_yaml="" secret_data="" sql
  for service in "${SERVICES[@]}"; do
    env_name="$(portal_db_password_env "${service}")"
    secret_data+="  ${env_name}: $(printf '%s' "$(portal_db_password "$(portal_db_role "${T_DB_NAME}" "${service}")")" | base64 | tr -d '\n')"$'\n'
    env_yaml+="            - name: ${env_name}"$'\n'
    env_yaml+="              valueFrom: { secretKeyRef: { name: tenant-db-portal, key: ${env_name} } }"$'\n'
  done
  sql="$(portal_db_setup_sql "${T_DB_NAME}" "${SERVICES[@]}" | sed 's/^/              /')"
  kubectl -n "${NS}" delete job tenant-db-portal --ignore-not-found >/dev/null 2>&1 || true
  apply_db_admin_secret "${NS}"
  kubectl -n "${NS}" apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: tenant-db-portal
type: Opaque
data:
${secret_data}
EOF
  kubectl apply -n "${NS}" -f - >/dev/null <<YAML
apiVersion: batch/v1
kind: Job
metadata:
  name: tenant-db-portal
spec:
  backoffLimit: 2
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: psql
          image: ${PG_CLIENT_IMAGE}
          imagePullPolicy: Never
          env:
            - name: PGPASSWORD
              valueFrom: { secretKeyRef: { name: tenant-db-admin, key: PGPASSWORD } }
${env_yaml}          command: ["/bin/sh","-c"]
          args:
            - |
              set -e
              psql "host=${RDS_HOST} port=${RDS_PORT} dbname=${T_DB_NAME} user=${DB_USER} sslmode=prefer connect_timeout=10" <<'SQL'
${sql}
              SQL
              echo "portal roles/schemas ready in ${T_DB_NAME}"
YAML
  if kubectl -n "${NS}" wait --for=condition=complete job/tenant-db-portal --timeout=120s >/dev/null 2>&1; then
    # shellcheck disable=SC2034  # read by build_helm_args
    T_PORTAL_DB_ROLES=true
  else
    kubectl -n "${NS}" logs job/tenant-db-portal >&2 || true
    kubectl -n "${NS}" get pods -o wide >&2 || true
    kubectl -n "${NS}" logs deploy/postgres --tail 30 >&2 || true
    return 1
  fi
  kubectl -n "${NS}" delete secret tenant-db-admin tenant-db-portal --ignore-not-found >/dev/null
}

drop_portal_schemas() {
  local service schemas=()
  for service in "${SERVICES[@]}"; do schemas+=("${PORTAL_DB_SCHEMA[$service]}"); done
  pg_admin_sql "${T_DB_NAME}" >/dev/null <<<"DROP SCHEMA IF EXISTS $(IFS=,; echo "${schemas[*]}") CASCADE;"
}

# deploy-tenant.sh deploy_service with a local image: build_helm_args, the release secrets file,
# then render + kubeconform and helm install.
install_service() {
  local service="$1" chart="${HELM_DIR}/$1" secret_file="${WORK_DIR}/$1-secrets.json"
  build_helm_args "${service}"
  jq -n --args '{secrets: (reduce range(0; ($ARGS.positional | length); 2) as $i
    ({}; . + {($ARGS.positional[$i]): $ARGS.positional[$i + 1]}))}' "${SECRET_KV[@]}" >"${secret_file}"
  chmod 600 "${secret_file}"
  local -a args=(--namespace "${NS}"
    --set image.repository="otterworks-${service}" --set image.tag="${IMAGE_TAG}" --set image.pullPolicy=Never
    "${EXTRA_ARGS[@]}" -f "${secret_file}")
  command helm template "${service}" "${chart}" --kube-version "$(kubectl version -o json | jq -r .serverVersion.gitVersion)" \
    "${args[@]}" >"${WORK_DIR}/${service}.yaml"
  kubeconform -strict -summary -kubernetes-version "$(kubectl version -o json | jq -r '.serverVersion.gitVersion | ltrimstr("v")')" \
    "${WORK_DIR}/${service}.yaml" >"${WORK_DIR}/${service}.kubeconform" 2>&1 \
    || { cat "${WORK_DIR}/${service}.kubeconform" >&2; return 1; }
  helm install "${service}" "${chart}" "${args[@]}" --wait --timeout 5m >"${WORK_DIR}/${service}.helm" 2>&1 \
    || { cat "${WORK_DIR}/${service}.helm" >&2; kubectl -n "${NS}" logs "deploy/${service}" --tail 60 >&2 || true; return 1; }
}

# Service type, replicas and NetworkPolicy as build_helm_args asks, pods Ready without restarts.
check_install() {
  local service type replicas ready restarts
  restarts="$(kubectl -n "${NS}" get pods -l app=postgres -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}')"
  [[ "${restarts}" == 0 ]] || { say "postgres restarted ${restarts} time(s); its data is not persistent"; return 1; }
  [[ "$(kubectl -n "${NS}" get networkpolicy -o name | wc -l)" == 0 ]] || { say "unexpected NetworkPolicy in ${NS}"; return 1; }
  for service in "${SERVICES[@]}"; do
    type="$(kubectl -n "${NS}" get svc "${service}" -o jsonpath='{.spec.type}')"
    replicas="$(kubectl -n "${NS}" get deploy "${service}" -o jsonpath='{.spec.replicas}')"
    kubectl -n "${NS}" wait --for=condition=Ready pod -l "app.kubernetes.io/instance=${service}" --timeout=60s >/dev/null \
      || { say "${service} pod not Ready"; return 1; }
    ready="$(kubectl -n "${NS}" get pods -l "app.kubernetes.io/instance=${service}" \
      -o jsonpath='{range .items[*]}{.status.containerStatuses[0].ready}{"\n"}{end}' | grep -c true)"
    restarts="$(kubectl -n "${NS}" get pods -l "app.kubernetes.io/instance=${service}" \
      -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}')"
    if [[ "${type}" != ClusterIP || "${replicas}" != 1 || "${ready}" != 1 ]]; then
      say "${service}: type=${type} replicas=${replicas} ready=${ready}"
      return 1
    fi
    INSTALL_DETAIL+="${service} 1/1 Ready (restarts ${restarts}); "
  done
}

# Each schema is owned by its service role, the service is connected as that role, and no portal
# role can use another service's schema.
check_ownership() {
  local service role schema other other_schema owner connected usage
  for service in "${SERVICES[@]}"; do
    role="$(portal_db_role "${T_DB_NAME}" "${service}")"
    schema="${PORTAL_DB_SCHEMA[$service]}"
    owner="$(pg_admin_sql "${T_DB_NAME}" <<<"SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = '${schema}'")"
    connected="$(pg_admin_sql "${T_DB_NAME}" <<<"SELECT count(*) FROM pg_stat_activity WHERE datname = '${T_DB_NAME}' AND usename = '${role}'")"
    [[ "${owner}" == "${role}" ]] || { say "schema ${schema} owned by '${owner}', expected ${role}"; return 1; }
    [[ "${connected}" != 0 ]] || { say "${service} has no connection as ${role}"; return 1; }
    for other in "${SERVICES[@]}"; do
      [[ "${other}" != "${service}" ]] || continue
      other_schema="${PORTAL_DB_SCHEMA[$other]}"
      usage="$(pg_admin_sql "${T_DB_NAME}" <<<"SELECT has_schema_privilege('${role}', '${other_schema}', 'USAGE')")"
      [[ "${usage}" == f ]] || { say "${role} can use schema ${other_schema}"; return 1; }
    done
  done
}

start_port_forwards() {
  local service port lport deadline
  require_kind_context
  for service in "${SERVICES[@]}"; do
    port="$(service_port "${service}")"; lport="$(local_port "${service}")"
    command kubectl --context "${CONTEXT}" -n "${NS}" port-forward "svc/${service}" "${lport}:${port}" \
      >"${WORK_DIR}/pf-${service}.log" 2>&1 &
    PF_PIDS+=("$!")
  done
  for service in "${SERVICES[@]}"; do
    lport="$(local_port "${service}")"; deadline=$((SECONDS + 30))
    until curl -fsS "http://127.0.0.1:${lport}/actuator/health/readiness" >/dev/null 2>&1; do
      (( SECONDS < deadline )) || { cat "${WORK_DIR}/pf-${service}.log" >&2; say "port-forward to ${service} not answering on :${lport}"; return 1; }
      sleep 1
    done
  done
}

run_parity() {
  local run="$1" service stem rc=0
  local out="${WORK_DIR}/parity-${run}.log"
  local -a url_env=()
  for service in "${SERVICES[@]}"; do
    stem="$(echo "${service%-service}" | tr '[:lower:]' '[:upper:]')"
    url_env+=("${stem}_URL=http://127.0.0.1:$(local_port "${service}")")
  done
  (cd "${REPO_ROOT}" && env "${url_env[@]}" \
    uv run --quiet --no-project --with-requirements "${PARITY_DIR}/requirements.txt" \
    python -m pytest -c "${PARITY_DIR}/pytest.ini" "${PARITY_DIR}" -q) >"${out}" 2>&1 || rc=$?
  PARITY_RESULT="$(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error)' "${out}" | tail -1 | tr -d '=' | sed -E 's/^ +| +$//g; s/ in [0-9.]+s$//')"
  [[ ${rc} -eq 0 ]] || cat "${out}" >&2
  return ${rc}
}

one_run() {
  local run="$1" service
  INSTALL_DETAIL=""
  PARITY_RESULT=""
  [[ "${run}" == 1 ]] || drop_portal_schemas
  create_portal_db_roles || { record "FAIL run ${run}/${RUNS}: portal roles/schemas Job"; return 1; }
  for service in "${SERVICES[@]}"; do
    install_service "${service}" || { record "FAIL run ${run}/${RUNS}: helm install ${service}"; return 1; }
  done
  check_install || { record "FAIL run ${run}/${RUNS}: pods/services not as build_helm_args specifies"; return 1; }
  record "PASS helm run ${run}/${RUNS}: helm install --wait $(printf '%s ' "${SERVICES[@]}")with build_helm_args (T_PORTAL_DB_ROLES=true; ClusterIP, replicas 1, networkPolicy off; kubeconform -strict clean) - ${INSTALL_DETAIL%; }"
  check_ownership || { record "FAIL run ${run}/${RUNS}: role/schema ownership"; return 1; }
  record "PASS roles run ${run}/${RUNS}: portal_db_setup_sql Job (psql 16 as ${DB_USER}) - schemas owned by and connected as $(for s in "${SERVICES[@]}"; do printf '%s ' "$(portal_db_role "${T_DB_NAME}" "${s}")"; done | sed 's/ $//'), no cross-schema USAGE"
  start_port_forwards || { record "FAIL parity run ${run}/${RUNS}: port-forward"; return 1; }
  if run_parity "${run}"; then
    record "PASS parity run ${run}/${RUNS}: make parity-legacy-portal through kubectl port-forward ($(for s in "${SERVICES[@]}"; do printf 'svc/%s:%s ' "${s}" "$(service_port "${s}")"; done | sed 's/ $//')) - ${PARITY_RESULT}"
  else
    record "FAIL parity run ${run}/${RUNS}: through kubectl port-forward - ${PARITY_RESULT:-did not run}"
    return 1
  fi
  stop_port_forwards
  if [[ "${run}" != "${RUNS}" || "${KEEP_CLUSTER}" != 1 ]]; then
    for service in "${SERVICES[@]}"; do helm uninstall "${service}" -n "${NS}" --wait >/dev/null; done
  fi
}

GOLDEN_BEFORE="$(cd "${PARITY_DIR}/golden" && sha256sum ./*.json | sha256sum | cut -c1-12)"
main() {
  if [[ "${SKIP_IMAGE_BUILD}" == 1 ]]; then
    say "skipping image build; using otterworks-<service>:${IMAGE_TAG}"
  else
    build_images || return 1
  fi
  create_cluster || { record "FAIL cluster: kind create cluster ${CLUSTER}"; return 1; }
  start_postgres || { record "FAIL postgres"; return 1; }
  local run
  for run in $(seq 1 "${RUNS}"); do
    one_run "${run}" || return 1
  done
}
main || FAILED=1
GOLDEN_AFTER="$(cd "${PARITY_DIR}/golden" && sha256sum ./*.json | sha256sum | cut -c1-12)"
[[ "${GOLDEN_BEFORE}" == "${GOLDEN_AFTER}" ]] || { record "FAIL golden transcripts changed during verification"; FAILED=1; }
if [[ "${FAILED}" == 0 && "${KEEP_CLUSTER}" == 0 ]]; then
  kind delete cluster --name "${CLUSTER}" --kubeconfig "${KUBECONFIG}" >/dev/null 2>&1 && CLUSTER_CREATED=0
  if kind get clusters 2>/dev/null | grep -qx "${CLUSTER}"; then
    record "FAIL teardown: cluster ${CLUSTER} still exists"; FAILED=1
  else
    record "PASS teardown: kind delete cluster ${CLUSTER} - no cluster left"
  fi
fi

echo
echo "=== legacy-portal verify-kind summary ==="
echo "commit:  $(git -C "${REPO_ROOT}" rev-parse --short HEAD)$(git -C "${REPO_ROOT}" diff --quiet HEAD -- || echo ' (dirty)')"
echo "cluster: ${CONTEXT} (${NODE_IMAGE%@*}), namespace ${NS}, database ${T_DB_NAME}"
echo "golden:  $(find "${PARITY_DIR}/golden" -name '*.json' | wc -l | tr -d ' ') transcripts, sha256 ${GOLDEN_AFTER}"
printf '%s\n' "${SUMMARY[@]}"
echo "--- trailers ---"
for line in "${SUMMARY[@]}"; do
  [[ "${line}" != PASS* ]] || echo "Verified-by: ${line#PASS *: }"
done | awk '!seen[$0]++'
if [[ "${FAILED}" == 1 ]]; then
  echo "RESULT: FAIL"
  exit 1
fi
echo "RESULT: PASS"
