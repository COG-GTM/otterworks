#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# OtterWorks - Per-Tenant Ephemeral Demo Deploy
#
# Stands up an isolated copy of the golden app for one attendee/demo run in the
# namespace  otterworks-<ATTENDEE_ID>  on the SHARED otterworks-dev EKS cluster.
# Wraps the config/secret wiring from scripts/deploy-dev.sh (via
# scripts/lib/tenant-common.sh) and layers on tenant isolation + cost controls.
#
# Per tenant this creates:
#   - namespace otterworks-<ID> (TTL-labeled for the reaper)
#   - ResourceQuota + LimitRange + a namespace NetworkPolicy
#   - per-tenant in-cluster Redis + MeiliSearch (chaos/session/search isolation)
#   - a per-tenant RDS database otterworks_<ID> (Postgres data isolation)
#   - all 11 backends + 2 frontends via Helm (replicas=1), frontends on the
#     SHARED ingress (ClusterIP + one Ingress), NOT one LoadBalancer per tenant
#
# Usage:
#   ./scripts/deploy-tenant.sh <ATTENDEE_ID> [--tier A|B] [--image-tag TAG] \
#       [--ttl 8h|none] [--always-on] [--host-suffix demo.example.com] \
#       [--skip-db] [--profile core|full]
#
#   Lifetime and wakefulness are separate choices:
#
#   --ttl none    makes the tenant PERSISTENT: no expiry annotation is written
#                 and the namespace is labelled demo/persistent=true, which both
#                 the baseline TTL reaper and the platform reaper treat as
#                 "never reap" (including its database, S3 prefix and DynamoDB
#                 items). Persistent tenants are removed only by
#                 teardown-tenant.sh. They still scale to zero when idle.
#
#   --always-on   exempts the tenant from idle scale-to-zero (label
#                 demo/always-on=true). Its URL answers with no wake step, at
#                 the cost of holding ~1.5 vCPU and ~15 pod IPs forever. Opt in
#                 only for environments someone must be able to open cold.
#
# Required env: AWS creds (exported), DB_PASSWORD. Stable JWT_SECRET /
#   SECRET_KEY_BASE recommended across redeploys (auto-generated if unset).
# ------------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=lib/tenant-common.sh
source "${SCRIPT_DIR}/lib/tenant-common.sh"

# ---------- Args ----------
ATTENDEE_ID=""
TIER="A"
IMAGE_TAG_OVERRIDE=""
TTL="8h"
ALWAYS_ON=false
HOST_SUFFIX="${HOST_SUFFIX:-}"
SKIP_DB=false
# Deploy only the services the lab needs. At 100 tenants the difference between
# "core" and "full" is roughly 100 vCPU of requests. Defaults to "full" so no
# existing lab loses a service; see profile_services in lib/tenant-common.sh.
PROFILE="${TENANT_PROFILE:-full}"
while [ $# -gt 0 ]; do
  case "$1" in
    --tier)        TIER="$2"; shift 2 ;;
    --image-tag)   IMAGE_TAG_OVERRIDE="$2"; shift 2 ;;
    --ttl)         TTL="$2"; shift 2 ;;
    --host-suffix) HOST_SUFFIX="$2"; shift 2 ;;
    --profile)     PROFILE="$2"; shift 2 ;;
    --always-on)   ALWAYS_ON=true; shift ;;
    --skip-db)     SKIP_DB=true; shift ;;
    -*)            err "Unknown flag: $1"; exit 1 ;;
    *)             if [ -z "${ATTENDEE_ID}" ]; then ATTENDEE_ID="$1"; else err "Unexpected arg: $1"; exit 1; fi; shift ;;
  esac
done

[ -n "${ATTENDEE_ID}" ] || { err "Usage: $0 <ATTENDEE_ID> [--tier A|B] [--image-tag TAG] [--ttl 8h|none] [--always-on] [--profile core|full]"; exit 1; }
case "${TIER}" in A|B) ;; *) err "--tier must be A or B"; exit 1 ;; esac
case "${PROFILE}" in core|full) ;; *) err "--profile must be core or full"; exit 1 ;; esac
mapfile -t TENANT_SERVICES < <(profile_services "${PROFILE}")

require_bins aws kubectl helm terraform jq
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text 2>/dev/null)}"
[ -n "${AWS_ACCOUNT_ID}" ] || { err "Unable to resolve AWS account (are creds exported?)"; exit 1; }
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
DB_PASSWORD="${DB_PASSWORD:?ERROR: DB_PASSWORD must be set}"
JWT_SECRET="${JWT_SECRET:-$(openssl rand -hex 32)}"
SECRET_KEY_BASE="${SECRET_KEY_BASE:-$(openssl rand -hex 64)}"

NS="$(tenant_namespace "${ATTENDEE_ID}")"
T_DB_NAME="$(tenant_db_name "${ATTENDEE_ID}")"
T_REDIS_HOST="redis"
T_MEILI_URL="http://meilisearch:7700"
# Tier A shares SNS/SQS eventing off by default to avoid cross-tenant queue
# consumption; Tier B (data-isolated) can opt in later. Kept off for both here.
T_WIRE_EVENTING="false"
# Convert a compact TTL (e.g. 8h, 30m, 2d) into an absolute UTC expiry, working
# with both GNU date (-d "8 hours") and BSD/macOS date (-v+8H).
ttl_to_expiry() {
  local ttl="$1" num unit gnu bsd
  num="${ttl%%[!0-9]*}"; unit="${ttl##*[0-9]}"
  [ -n "${num}" ] || { err "Invalid --ttl '${ttl}' (use e.g. 8h, 30m, 2d)"; exit 1; }
  case "${unit}" in
    h|H|"") gnu="${num} hours";   bsd="+${num}H" ;;
    m|M)    gnu="${num} minutes"; bsd="+${num}M" ;;
    d|D)    gnu="${num} days";    bsd="+${num}d" ;;
    *)      err "Invalid --ttl unit in '${ttl}' (use h, m, or d)"; exit 1 ;;
  esac
  date -u -d "+${gnu}" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v"${bsd}" +%Y-%m-%dT%H:%M:%SZ
}
# A persistent tenant carries no expiry at all: every reaper path keys off the
# presence of an expiry rather than its value, so "no expiry" is the encoding
# for "never reap" -- a far-future timestamp would still be a deadline.
PERSISTENT=false
case "${TTL}" in none|never|infinite|persistent) PERSISTENT=true ;; esac

TENANT_LABELS=""
TENANT_ANNOTATIONS=""
if [ "${ALWAYS_ON}" = true ]; then
  TENANT_LABELS=$'\n    demo/always-on: "true"'
fi
if [ "${PERSISTENT}" = true ]; then
  TENANT_LABELS="${TENANT_LABELS}"$'\n    demo/persistent: "true"'
  log "Tenant '${ATTENDEE_ID}' -> namespace ${NS} (tier ${TIER}, persistent: no TTL, reapers skip it)"
else
  # The two flags are independent on purpose, but this pairing is nearly always a
  # mistake: it holds the tenant's requests for the whole TTL and then deletes the
  # tenant -- namespace, database and S3 prefix -- at the end of it.
  [ "${ALWAYS_ON}" = false ] || warn "--always-on with --ttl ${TTL}: this reserves the tenant's compute until it expires, and it is still reaped then. Pass --ttl none for a standing environment."
  EXPIRES_AT="$(ttl_to_expiry "${TTL}")"
  # Epoch form for the reaper: it compares integers only (no ISO parsing), so the
  # reaper image needs nothing more than `date +%s`.
  EXPIRES_EPOCH="$(date -u -d "${EXPIRES_AT}" +%s 2>/dev/null || date -u -jf %Y-%m-%dT%H:%M:%SZ "${EXPIRES_AT}" +%s)"
  TENANT_ANNOTATIONS=$'\n    demo/expires-at: "'"${EXPIRES_AT}"$'"\n    demo/expires-at-epoch: "'"${EXPIRES_EPOCH}"'"'
  log "Tenant '${ATTENDEE_ID}' -> namespace ${NS} (tier ${TIER}, ttl ${TTL} -> expires ${EXPIRES_AT})"
fi

# ---------- kubectl + shared infra outputs ----------
# In-cluster (runner Job) the pod's ServiceAccount already has cluster access via
# RBAC; writing a kubeconfig would instead auth as the IRSA IAM role, which is
# not mapped in aws-auth. Only build a kubeconfig when running outside the cluster.
# OTTERWORKS_KUBECONFIG_READY says a caller has already written it: the update is a
# read-modify-write of one file, so a batch running several deploys at once would
# have them clobber each other's kubeconfig, and a kubectl reading it mid-write
# fails for reasons that have nothing to do with the tenant.
if [ -z "${KUBERNETES_SERVICE_HOST:-}" ] && [ -z "${OTTERWORKS_KUBECONFIG_READY:-}" ]; then
  aws eks update-kubeconfig --name "${EKS_CLUSTER}" --region "${AWS_REGION}" --alias "${EKS_CLUSTER}" >/dev/null
fi
log "Loading shared application-infra Terraform outputs..."
load_infra_outputs

# ---------- Namespace + isolation guardrails ----------
log "Creating namespace ${NS} with quota / limits / network policy..."
kubectl apply -f - <<YAML
apiVersion: v1
kind: Namespace
metadata:
  name: ${NS}
  labels:
    app.kubernetes.io/managed-by: otterworks-tenant
    platform/environment: dev
    platform/team: otterworks
    demo/tenant: "$(sanitize_id "${ATTENDEE_ID}")"
    demo/tier: "${TIER}"
    demo/profile: "${PROFILE}"
    kubernetes.io/metadata.name: ${NS}${TENANT_LABELS}
  annotations:
    demo/attendee-id: "${ATTENDEE_ID}"${TENANT_ANNOTATIONS}
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: tenant-quota
  namespace: ${NS}
spec:
  hard:
    # Requests are what actually reserve node capacity, so they stay tight --
    # this is the number that decides how many tenants fit on the cluster.
    requests.cpu: "4"
    requests.memory: 8Gi
    # Limits only cap bursting, but the quota counts them, and the full service
    # set declares ~9.25 CPU of limits. At 8 the last two Deployments to be
    # created were rejected by the quota and simply never appeared -- the
    # namespace looked healthy because the failure lands on the ReplicaSet, not
    # on a pod. Sized above the profile's total rather than by trimming limits,
    # which would only make services throttle under load.
    limits.cpu: "12"
    limits.memory: 20Gi
    pods: "40"
---
apiVersion: v1
kind: LimitRange
metadata:
  name: tenant-limits
  namespace: ${NS}
spec:
  limits:
    - type: Container
      default:
        cpu: 500m
        memory: 256Mi
      defaultRequest:
        cpu: 100m
        memory: 128Mi
---
# Tenant isolation: allow traffic only from within this namespace, the shared
# ingress controller, and monitoring. Cross-tenant pod-to-pod traffic is denied.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: tenant-isolation
  namespace: ${NS}
spec:
  podSelector: {}
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ${NS}
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ${INGRESS_NAMESPACE}
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
YAML

# demo/deployed-at describes the run that wrote it, and this run has not finished:
# it is set with `kubectl annotate`, so the apply above does not prune it, and a
# redeploy that then loses a service would be read as complete on the strength of
# the previous one's marker.
kubectl annotate namespace "${NS}" demo/deployed-at- >/dev/null 2>&1 || true

# The idle scan's bookkeeping for a script-deployed tenant lives on the same
# namespace and survives this apply for the same reason. Left in place, a tenant
# that was 50 minutes idle when it was redeployed carries that clock across and
# can be suspended ten minutes later, having just been rebuilt. The redeploy is
# activity; the counters start again with it.
kubectl annotate namespace "${NS}" \
  demo/req-count- demo/idle-since- demo/was-running- >/dev/null 2>&1 || true

# The same clock, for a tenant the dashboard checked out: its counters live in
# the control table, nothing on the deploy path has ever reset them, and the
# hazard is identical -- a tenant rebuilt after 55 idle minutes is suspended by
# the next pass, five minutes old. Smaller blast radius than the namespace case
# (check-out can wake a dashboard tenant; nothing can wake a script-deployed
# one), which is why it went unnoticed, not why it is acceptable.
#
# attribute_exists(PK) is what makes this safe to run for every tenant: without
# it, update-item would *create* an item for a script-deployed tenant, and an
# item is precisely what tells the idle scan and the orphan sweeps that a tenant
# is the dashboard's -- state written where nothing reads it, and a persistent
# tenant that suddenly looks checked out. The condition fails for those, aws
# exits non-zero, and the line below swallows it, which is the intent.
#
# Best-effort in every other sense too: this script runs from operator machines
# with no DynamoDB access at all, and an idle clock is not worth failing a
# deploy over.
aws dynamodb update-item \
  --table-name "${CONTROL_TABLE:-otterworks-demo-control}" --region "${AWS_REGION}" \
  --key "{\"PK\":{\"S\":\"TENANT#${NS#otterworks-}\"},\"SK\":{\"S\":\"META\"}}" \
  --update-expression "REMOVE req_count, idle_since, was_running" \
  --condition-expression "attribute_exists(PK)" >/dev/null 2>&1 || true

# Converting a TTL'd tenant to a persistent one has to strip the annotations the
# earlier deploy left behind: the baseline reaper reads them straight off the
# namespace, and `kubectl apply` only prunes fields it owns (a namespace created
# by an older deploy, or edited with `kubectl annotate`, is not owned here).
if [ "${PERSISTENT}" = true ]; then
  kubectl annotate namespace "${NS}" demo/expires-at- demo/expires-at-epoch- >/dev/null 2>&1 || true
else
  kubectl label namespace "${NS}" demo/persistent- >/dev/null 2>&1 || true
fi
if [ "${ALWAYS_ON}" = true ]; then
  log "Tenant '${ATTENDEE_ID}' is always-on: the idle scan will not scale it to zero."
else
  # Dropping the flag on a redeploy has to take the label with it, or the
  # tenant keeps its exemption from a decision nobody made twice.
  kubectl label namespace "${NS}" demo/always-on- >/dev/null 2>&1 || true
fi

# ---------- IRSA trust: allow this tenant namespace to assume the shared roles ----------
update_irsa_trust() {
  local d="${REPO_ROOT}/infrastructure/terraform"
  local oidc_url; oidc_url="$(terraform -chdir="${REPO_ROOT}/platform/terraform" output -raw oidc_provider_url 2>/dev/null || echo "")"
  # In-cluster the platform/terraform state isn't initialized; fall back to the
  # cluster's OIDC issuer via the EKS API (the runner IRSA role has
  # eks:DescribeCluster). Without this the per-namespace trust is skipped and
  # tenant pods can't assume the shared roles (AWS ops fail).
  if [ -z "${oidc_url}" ]; then
    oidc_url="$(aws eks describe-cluster --name "${EKS_CLUSTER}" --region "${AWS_REGION}" \
      --query 'cluster.identity.oidc.issuer' --output text 2>/dev/null || echo "")"
  fi
  oidc_url="${oidc_url#https://}"
  # 3, not 0: this runs inside ensure_irsa_trust's flock subshell, so it cannot
  # append to INCOMPLETE itself -- the caller translates the status.
  [ -n "${oidc_url}" ] || { warn "OIDC provider URL unavailable; skipping IRSA trust update (IRSA may fail for ${NS})"; return 3; }
  local svc role sub
  for svc in $(echo "${IRSA_JSON}" | jq -r 'keys[]'); do
    role="otterworks-${svc}-dev"
    sub="system:serviceaccount:${NS}:${svc}"
    local doc; doc="$(aws iam get-role --role-name "${role}" --query 'Role.AssumeRolePolicyDocument' --output json 2>/dev/null || echo "")"
    [ -n "${doc}" ] || { warn "role ${role} not found; skipping"; continue; }
    # Skip if the sub is already trusted — either an exact StringEquals entry or
    # a StringLike wildcard (e.g. the Terraform-managed "otterworks-*" pattern)
    # that already matches this namespace. Checking only StringEquals would make
    # us append a redundant statement on every deploy and bloat the trust policy
    # (IAM trust docs cap at 2048/4096 chars) until deploys start failing.
    local trusted already=false pat
    trusted="$(echo "${doc}" | jq -r --arg url "${oidc_url}" '
      [ .Statement[]?.Condition
        | (.StringEquals[$url+":sub"], .StringLike[$url+":sub"])
        | select(. != null)
        | if type=="array" then .[] else . end ] | .[]' 2>/dev/null)"
    while IFS= read -r pat; do
      [ -n "${pat}" ] || continue
      # shellcheck disable=SC2254  # glob-match the exact sub against trust patterns
      case "${sub}" in ${pat}) already=true; break ;; esac
    done <<EOF
${trusted}
EOF
    [ "${already}" = true ] && continue
    # Append an AssumeRoleWithWebIdentity statement scoped to this namespace SA.
    local new; new="$(echo "${doc}" | jq --arg sub "${sub}" --arg url "${oidc_url}" '
      .Statement += [{
        Effect: "Allow",
        Action: "sts:AssumeRoleWithWebIdentity",
        Principal: (.Statement[0].Principal),
        Condition: { StringEquals: { ($url+":sub"): $sub, ($url+":aud"): "sts.amazonaws.com" } }
      }]')"
    aws iam update-assume-role-policy --role-name "${role}" --policy-document "${new}" >/dev/null \
      && log "  IRSA trust: ${role} now trusts ${sub}" \
      || warn "  failed to update trust for ${role}"
  done
  # Pin the contract the caller switches on: 0 is done, 3 is skipped, anything
  # else aborts the deploy. Without this the function returns whatever the loop
  # last ran, and a future edit near the end of it turns an incidental non-zero
  # into a failed tenant.
  return 0
}

# The trust documents are shared between all tenants and updated read-modify-
# write, so two deploys running at once (deploy-tenant-batch.sh fans out by
# default) can each append their namespace to the same document and the second
# write drops the first. Nothing surfaces the loss: the deploy succeeds and that
# tenant's pods then fail every AWS call. Serialise the pass across processes on
# this host; it is seconds long, and a no-op when the Terraform-managed
# otterworks-* wildcard already covers the namespace.
#
# The lock lives in a directory this user owns, not at a fixed path in a
# world-writable /tmp: there, any local account can hold the file open until the
# timeout fires (every deploy aborts) or pre-create it unwritable, and defeating
# the lock re-opens the lost-update it exists to close. Falls back to the shared
# path only if a private directory cannot be made, which is where it was before.
irsa_lock_path() {
  local base dir
  base="${XDG_RUNTIME_DIR:-${HOME:-}}"
  [ -n "${base}" ] && [ -d "${base}" ] || base="${TMPDIR:-/tmp}"
  dir="${base}/.otterworks"
  mkdir -p "${dir}" 2>/dev/null || return 1
  # -O, because mkdir -p on an existing directory owned by somebody else
  # succeeds, and that directory is exactly what this is avoiding.
  [ -O "${dir}" ] || return 1
  chmod 700 "${dir}" 2>/dev/null || return 1
  printf '%s/irsa-trust.lock' "${dir}"
}

ensure_irsa_trust() {
  local lock
  lock="$(irsa_lock_path)" || {
    lock="${TMPDIR:-/tmp}/otterworks-irsa-trust.lock"
    warn "no private lock directory available; falling back to ${lock}"
  }
  if ! command -v flock >/dev/null 2>&1; then
    warn "flock unavailable: concurrent deploys may race on the shared IRSA trust policies"
    update_irsa_trust
    return
  fi
  # The redirection below is what opens the lock, and a path that cannot be
  # opened (someone else's file, a symlink into a directory we cannot write)
  # fails there, inside a subshell, leaving the deploy to abort on a bare status
  # 1 and a line about a file descriptor. Find out here, where the message can
  # say what actually went wrong.
  if ! : >>"${lock}" 2>/dev/null; then
    err "  cannot open the IRSA trust lock (${lock}); not updating the shared trust"
    err "  policies unserialised — remove or fix that path and re-run."
    return 1
  fi
  # Ten minutes is far longer than the pass takes, so a timeout means a stuck
  # holder rather than contention. Going ahead anyway is the one outcome worth
  # avoiding — it is the lost-update this lock exists to prevent, and it fails
  # later and invisibly, in another tenant's pods.
  (
    flock -w 600 9 || { err "  timed out waiting for the IRSA trust lock (${lock}); another deploy is mid-update"; exit 1; }
    update_irsa_trust
  ) 9>"${lock}"
}
# Steps that leave a tenant unusable without failing the run. They warn rather
# than abort on purpose -- one missing piece should not abandon the other twelve
# services -- but the completion marker must not call the result finished:
# deploy-tenant-batch.sh skips a marked tenant on every re-run, which is exactly
# when someone is trying to repair one of these.
INCOMPLETE=()

log "Ensuring shared IRSA roles trust the tenant namespace service accounts..."
IRSA_RC=0; ensure_irsa_trust || IRSA_RC=$?
# 3 is "skipped, tenant unusable"; anything else (a lock timeout) still aborts.
case "${IRSA_RC}" in
  0) ;;
  3) INCOMPLETE+=("IRSA trust for ${NS}") ;;
  *) exit "${IRSA_RC}" ;;
esac

# ---------- Per-tenant RDS database (Postgres data isolation) ----------
create_tenant_database() {
  [ -n "${RDS_HOST}" ] || {
    warn "RDS endpoint unknown; skipping per-tenant DB (services will share the default DB)"
    INCOMPLETE+=("database (RDS endpoint unknown)"); return 0
  }
  log "Ensuring per-tenant database ${T_DB_NAME} exists on shared RDS (in-cluster job)..."
  kubectl -n "${NS}" delete job tenant-db-init --ignore-not-found >/dev/null 2>&1 || true
  apply_db_admin_secret "${NS}"
  kubectl apply -n "${NS}" -f - <<YAML
apiVersion: batch/v1
kind: Job
metadata:
  name: tenant-db-init
spec:
  backoffLimit: 2
  ttlSecondsAfterFinished: 120
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: psql
          image: postgres:16-alpine
          env:
            - name: PGPASSWORD
              valueFrom: { secretKeyRef: { name: tenant-db-admin, key: PGPASSWORD } }
          command: ["/bin/sh","-c"]
          args:
            - |
              set -e
              CONN="host=${RDS_HOST} port=${RDS_PORT} dbname=otterworks user=${DB_USER} sslmode=prefer connect_timeout=10"
              if psql "\$CONN" -tAc "SELECT 1 FROM pg_database WHERE datname='${T_DB_NAME}'" | grep -q 1; then
                echo "database ${T_DB_NAME} already exists"
              else
                psql "\$CONN" -c "CREATE DATABASE \"${T_DB_NAME}\""
                echo "created database ${T_DB_NAME}"
              fi
          resources:
            requests: { cpu: 50m, memory: 64Mi }
            limits: { cpu: 200m, memory: 128Mi }
YAML
  if kubectl -n "${NS}" wait --for=condition=complete job/tenant-db-init --timeout=120s >/dev/null 2>&1; then
    log "  per-tenant database ready."
  else
    warn "  per-tenant DB init did not complete; check: kubectl -n ${NS} logs job/tenant-db-init"
    INCOMPLETE+=("database ${T_DB_NAME}")
    kubectl -n "${NS}" logs job/tenant-db-init 2>/dev/null | tail -5 || true
  fi
  kubectl -n "${NS}" delete secret tenant-db-admin --ignore-not-found >/dev/null 2>&1 || true
}
if [ "${SKIP_DB}" = true ]; then
  warn "--skip-db set: using the shared default database (no Postgres data isolation)."
  T_DB_NAME="otterworks"
else
  create_tenant_database
fi

# ---------- Per-tenant Redis + MeiliSearch ----------
log "Deploying per-tenant Redis + MeiliSearch..."
kubectl apply -n "${NS}" -f - <<'YAML'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  labels: { app: redis }
spec:
  replicas: 1
  selector: { matchLabels: { app: redis } }
  template:
    metadata:
      labels: { app: redis }
    spec:
      containers:
        - name: redis
          image: redis:7-alpine
          args: ["--save","","--appendonly","no"]
          ports: [{ containerPort: 6379 }]
          readinessProbe:
            tcpSocket: { port: 6379 }
            initialDelaySeconds: 3
            periodSeconds: 10
          resources:
            requests: { cpu: 50m, memory: 64Mi }
            limits: { cpu: 250m, memory: 256Mi }
---
apiVersion: v1
kind: Service
metadata:
  name: redis
  labels: { app: redis }
spec:
  selector: { app: redis }
  ports: [{ port: 6379, targetPort: 6379 }]
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: meilisearch
  labels: { app: meilisearch }
spec:
  replicas: 1
  selector: { matchLabels: { app: meilisearch } }
  template:
    metadata:
      labels: { app: meilisearch }
    spec:
      containers:
        - name: meilisearch
          image: getmeili/meilisearch:v1.8
          env:
            - { name: MEILI_ENV, value: "development" }
            - { name: MEILI_NO_ANALYTICS, value: "true" }
          ports: [{ containerPort: 7700 }]
          readinessProbe:
            httpGet: { path: /health, port: 7700 }
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests: { cpu: 100m, memory: 256Mi }
            limits: { cpu: 500m, memory: 512Mi }
---
apiVersion: v1
kind: Service
metadata:
  name: meilisearch
  labels: { app: meilisearch }
spec:
  selector: { app: meilisearch }
  ports: [{ port: 7700, targetPort: 7700 }]
YAML
# Chaos flags, sessions and search live here, so a tenant without them is not
# usable -- and these timeouts are realistic while a batch waits on Karpenter to
# launch nodes and pull images. Recorded rather than only warned about, so the
# tenant is not stamped complete and a re-run retries it.
kubectl -n "${NS}" rollout status deployment/redis --timeout=120s \
  || { warn "redis not ready"; INCOMPLETE+=("redis"); }
kubectl -n "${NS}" rollout status deployment/meilisearch --timeout=180s \
  || { warn "meilisearch not ready"; INCOMPLETE+=("meilisearch"); }

# ---------- Resolve image tags ----------
# No `docker login` here: nothing in this script talks to a Docker daemon. Tags
# come from the ECR API below, and the images themselves are pulled by kubelet
# with the node role's credentials. The login was also a shared-file write --
# every concurrent child of deploy-tenant-batch.sh rewriting ~/.docker/config.json
# at once -- for a credential none of them read.
latest_tag() {
  # deploy-tenant-batch.sh resolves each service's tag once and exports it here:
  # the answer is the same for every tenant, and asking per tenant is ~1200
  # calls for a 95-name roster with a throttled one costing that tenant a
  # service. Unset outside the batch, where this is a single lookup anyway.
  local cached="OTTERWORKS_IMAGE_TAG_${1//-/_}"
  if [ -n "${!cached:-}" ]; then printf '%s' "${!cached}"; return 0; fi
  aws ecr describe-images --repository-name "${ECR_PREFIX}$1" --region "${AWS_REGION}" \
    --query 'sort_by(imageDetails,&imagePushedAt)[-1].imageTags[0]' --output text 2>/dev/null
}

# ---------- Deploy services via Helm ----------
deploy_service() {
  local service=$1
  local chart_dir="${REPO_ROOT}/infrastructure/helm/${service}"
  # Non-zero, not a benign skip: every service in every profile has a chart, so a
  # missing one leaves the tenant without that service. The caller collects it in
  # FAILED, which withholds the completion marker and makes a re-run retry.
  [ -d "${chart_dir}" ] || { warn "No chart for ${service}; not deployed"; return 1; }

  local tag="${IMAGE_TAG_OVERRIDE}"
  # Per-service image tag override: BUG_IMAGE_TAG_<service_with_underscores>
  local var="BUG_IMAGE_TAG_${service//-/_}"
  [ -n "${!var:-}" ] && tag="${!var}"
  [ -z "${tag}" ] && tag="$(latest_tag "${service}")"
  if [ -z "${tag}" ] || [ "${tag}" = "None" ]; then
    warn "No image in ECR for ${service}; not deployed."
    return 1
  fi

  build_helm_args "${service}"
  local secret_file="" secret_args=()
  if [ "${#SECRET_KV[@]}" -gt 0 ]; then
    secret_file="$(mktemp)"; chmod 600 "${secret_file}"
    jq -n --args '{secrets: (reduce range(0; ($ARGS.positional | length); 2) as $i
      ({}; . + {($ARGS.positional[$i]): $ARGS.positional[$i + 1]}))}' \
      "${SECRET_KV[@]}" > "${secret_file}"
    secret_args=(-f "${secret_file}")
  fi

  log "Deploying ${service} (tag ${tag})..."
  helm upgrade --install "${service}" "${chart_dir}" \
    --namespace "${NS}" \
    --set image.repository="${ECR_REGISTRY}/${ECR_PREFIX}${service}" \
    --set image.tag="${tag}" \
    "${EXTRA_ARGS[@]}" \
    "${secret_args[@]}" \
    --timeout 4m \
    && local rc=0 || local rc=1
  [ -n "${secret_file}" ] && rm -f "${secret_file}"
  if [ "${rc}" -ne 0 ]; then
    warn "Helm deploy failed for ${service}"
    return 1
  fi
  return 0
}

log "Deploying services into ${NS} (profile=${PROFILE}, ${#TENANT_SERVICES[@]} services)..."
FAILED=()
for service in "${TENANT_SERVICES[@]}"; do
  deploy_service "${service}" || FAILED+=("${service}")
done

# ---------- Shared ingress (host/path routing, ONE shared ALB/NLB) ----------
apply_ingress() {
  local sid; sid="$(sanitize_id "${ATTENDEE_ID}")"
  if [ -n "${HOST_SUFFIX}" ]; then
    # Preferred: host-based routing. One shared ingress controller / ELB fronts
    # every tenant; the web host serves the SPA, the api host the gateway.
    local web_host="t-${sid}.${HOST_SUFFIX}"
    local api_host="api-t-${sid}.${HOST_SUFFIX}"
    log "Applying shared ingress for ${NS} (hosts ${web_host}, ${api_host})..."
    kubectl apply -n "${NS}" -f - <<YAML
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: tenant-ingress
spec:
  ingressClassName: nginx
  rules:
    - host: ${web_host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: { name: web-app, port: { number: 80 } }
    - host: ${api_host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: { name: api-gateway, port: { number: 8080 } }
YAML
  else
    # Fallback: path-based routing on the shared ingress IP when no wildcard DNS
    # is available. The SPA is best reached with a base path; the gateway is
    # rewritten so /<id>/api/v1/... -> /api/v1/... on the backend.
    log "Applying shared ingress for ${NS} (path /${sid} , no host suffix)..."
    kubectl apply -n "${NS}" -f - <<YAML
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: tenant-ingress-api
  annotations:
    nginx.ingress.kubernetes.io/use-regex: "true"
    nginx.ingress.kubernetes.io/rewrite-target: /api/\$2
spec:
  ingressClassName: nginx
  rules:
    - http:
        paths:
          - path: /${sid}/api(/|\$)(.*)
            pathType: ImplementationSpecific
            backend:
              service: { name: api-gateway, port: { number: 8080 } }
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: tenant-ingress-web
  annotations:
    nginx.ingress.kubernetes.io/use-regex: "true"
    nginx.ingress.kubernetes.io/rewrite-target: /\$2
spec:
  ingressClassName: nginx
  rules:
    - http:
        paths:
          - path: /${sid}(/|\$)(.*)
            pathType: ImplementationSpecific
            backend:
              service: { name: web-app, port: { number: 80 } }
YAML
  fi
}
if kubectl get ns "${INGRESS_NAMESPACE}" >/dev/null 2>&1; then
  apply_ingress
else
  warn "No '${INGRESS_NAMESPACE}' namespace — shared ingress controller not installed."
  warn "Run scripts/tenant-platform-baseline.sh once to install it. Frontends are ClusterIP-only for now."
  # No ingress means no URL, which is the whole point of the tenant.
  INCOMPLETE+=("ingress (no ${INGRESS_NAMESPACE} namespace)")
fi

# ---------- Late readiness re-check ----------
# Redis and MeiliSearch are waited for early, before thirteen Helm installs and
# the ingress, so on a cold cluster their timeout can expire while Karpenter is
# still launching the node they are scheduled onto. That is a slow tenant, not a
# broken one, and several minutes of deploy have run since -- so ask once more
# here, briefly, rather than withholding the marker and having the batch
# redeploy a tenant that came up thirty seconds after anyone last looked.
if [ ${#INCOMPLETE[@]} -gt 0 ]; then
  STILL=()
  for step in "${INCOMPLETE[@]}"; do
    case "${step}" in
      redis|meilisearch)
        if kubectl -n "${NS}" rollout status "deployment/${step}" --timeout=60s >/dev/null 2>&1; then
          log "${step} came up during the rest of the deploy."
          continue
        fi ;;
    esac
    STILL+=("${step}")
  done
  INCOMPLETE=("${STILL[@]+"${STILL[@]}"}")
fi

# ---------- Completion marker ----------
# The namespace is created in the first seconds, so its existence says nothing
# about whether the deploy finished; deploy-tenant-batch.sh reads this annotation
# to tell a finished tenant from one to retry. Every step above either succeeded
# (set -e), is in FAILED (the Helm loop collects per-service failures rather than
# aborting the tenant) or is in INCOMPLETE (the steps that warn and carry on:
# IRSA trust, the database, Redis/MeiliSearch readiness, the shared ingress).
# A tenant missing services, a database, or a URL is half-built and not done.
#
# Retried, and loud when it still fails: the batch reads this one annotation to
# decide what to retry, so a single throttled write turns a finished tenant into
# "services missing, tenant incomplete" and a full redeploy on the next run. The
# marker is only as trustworthy as the write that sets it.
if [ ${#FAILED[@]} -eq 0 ] && [ ${#INCOMPLETE[@]} -eq 0 ]; then
  MARKED=false
  for attempt in 1 2 3; do
    if kubectl annotate namespace "${NS}" --overwrite \
         "demo/deployed-at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null 2>&1; then
      MARKED=true
      break
    fi
    sleep $(( attempt * 2 ))
  done
  if [ "${MARKED}" = false ]; then
    warn "could not mark ${NS} deployed: the tenant is built, but the batch reads that"
    warn "  annotation, so it will report this one incomplete and redeploy it."
  fi
fi

# ---------- Summary ----------
echo ""
log "Tenant ${ATTENDEE_ID} deployed to namespace ${NS}."
kubectl get pods -n "${NS}" -o wide || true
if [ ${#FAILED[@]} -gt 0 ]; then
  warn "Services with deploy issues: ${FAILED[*]}"
fi
if [ ${#INCOMPLETE[@]} -gt 0 ]; then
  warn "Incomplete: ${INCOMPLETE[*]} -- re-run this deploy once the cause is fixed."
fi
echo ""
if [ "${PERSISTENT}" = true ]; then
  log "Lifetime:  persistent (no TTL) — remove with ./scripts/teardown-tenant.sh ${ATTENDEE_ID}"
fi
log "Inspect:   kubectl get all -n ${NS}"
log "Reach API: kubectl -n ${NS} port-forward svc/api-gateway 8080:8080"
log "Inject bug: ./scripts/inject-bug.sh ${ATTENDEE_ID} <scenario>"
log "Teardown:  ./scripts/teardown-tenant.sh ${ATTENDEE_ID}"
