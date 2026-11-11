#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# OtterWorks multi-tenant demo — shared library
#
# Sourced by deploy-tenant.sh / teardown-tenant.sh / tenant-platform-baseline.sh.
# Holds the naming rules, Terraform-output loading and per-service Helm wiring
# that turn the golden app (see scripts/deploy-dev.sh) into a per-tenant deploy
# in namespace otterworks-<ATTENDEE_ID>.
#
# Design (see docs/MULTI-TENANT-DEMO-PLAN.md):
#   - namespace-per-tenant is the isolation boundary
#   - stateful backends are SHARED physically, isolated LOGICALLY:
#       * per-tenant in-cluster Redis      -> isolates chaos flags / sessions / collab
#       * per-tenant in-cluster MeiliSearch-> isolates search indexes
#       * per-tenant RDS database          -> isolates all Postgres-backed services
#       * shared S3 buckets (per-tenant prefix) + per-tenant DynamoDB tables,
#         reached through per-tenant IRSA roles
#   - frontends go on the SHARED ingress (ClusterIP), not one ELB per tenant
# ------------------------------------------------------------------------------

# Colors / logging ------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[tenant]${NC} $*"; }
warn() { echo -e "${YELLOW}[tenant]${NC} $*"; }
err()  { echo -e "${RED}[tenant]${NC} $*" >&2; }

# Shared constants ------------------------------------------------------------
AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER="${EKS_CLUSTER:-otterworks-dev}"
ECR_PREFIX="otterworks/"
SYSTEM_NAMESPACE="otterworks-system"   # holds the reaper CronJob + RBAC
INGRESS_NAMESPACE="ingress-nginx"

BACKEND_SERVICES=(
  api-gateway auth-service file-service document-service collab-service
  notification-service search-service analytics-service admin-service
  audit-service report-service
)
FRONTEND_SERVICES=(web-app admin-dashboard)
ALL_SERVICES=("${BACKEND_SERVICES[@]}" "${FRONTEND_SERVICES[@]}")

# Service profiles. A full tenant is ~1.5 vCPU / 3.5GiB of requests, which does
# not multiply to 100 tenants affordably -- but few labs exercise all 13
# services. "core" is the subset a browser session actually touches (~0.5 vCPU).
#
# "full" remains the default: "core" deliberately omits admin-service, which
# hosts the incident-triage path (and, on the upstream golden app, the planted
# crash-loop bug for bug-hunt labs), so switching the default would silently
# break those demos. Opt in with --profile core when a lab is known not to
# need the whole estate.
PROFILE_CORE_SERVICES=(api-gateway auth-service file-service document-service web-app)

# Echo the service list for a profile.
profile_services() {
  case "$1" in
    core) printf '%s\n' "${PROFILE_CORE_SERVICES[@]}" ;;
    full) printf '%s\n' "${ALL_SERVICES[@]}" ;;
    *)    err "unknown profile '$1' (expected core or full)"; return 1 ;;
  esac
}

# The gateway proxies each route to http://<service>:<containerPort>, so every
# backend Service must be exposed on its container port (mirrors deploy-dev.sh).
declare -A CONTAINER_PORT=(
  [api-gateway]=8080 [auth-service]=8081 [file-service]=8082 [document-service]=8083
  [collab-service]=8084 [notification-service]=8086 [search-service]=8087
  [analytics-service]=8088 [admin-service]=8089 [audit-service]=8090 [report-service]=8091
)
JVM_SERVICES=" auth-service report-service notification-service analytics-service "

# Naming ----------------------------------------------------------------------
# Namespace must be RFC-1123 (lowercase alnum + '-'); DB name uses '_'.
#
# Must match sanitizeId() in demo-platform/dashboard/lib/util.ts exactly, down
# to the collapsing and the 40-character cut: the dashboard creates the tenant
# under its own version of this id, and a tag or namespace derived from a
# different one points at nothing.
sanitize_id() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' |
    sed 's/[^a-z0-9-]/-/g; s/-\{2,\}/-/g; s/^-*//; s/-*$//' |
    cut -c1-40 | sed 's/-*$//'
}
tenant_namespace() { printf 'otterworks-%s' "$(sanitize_id "$1")"; }

# Git branch -> the Docker tag CI publishes that branch's images under. Docker
# tags allow [a-zA-Z0-9._-] only, so `feature/x` cannot be used verbatim.
branch_tag_slug() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9._-]/-/g'
}

# The tag a tenant's own build is published under. Keyed by tenant id, not by
# branch: several repositories (this one and its forks) push to one registry and
# would otherwise both claim `branch-demo-x`, each serving the other's build.
# Tenant ids are already namespaced per repository by TENANT_PREFIX, so keying
# on them makes the tag say exactly which environment it belongs to. CI and
# deploy-tenant.sh must agree exactly or a tenant silently falls back to the
# golden image, so both call this.
tenant_image_tag() { printf 'tenant-%s' "$(sanitize_id "$1")"; }

# Tenant id for a branch: `workshop-derek` and `demo-derek` both own tenant
# `derek`. The dashboard rejects a redeploy whose branch does not match the one
# the tenant was checked out from, so the collision cannot silently hijack.
#
# TENANT_PREFIX namespaces a whole repository's environments: a fork sets it so
# that its `demo-derek` is tenant `<prefix>-derek` with its own namespace,
# database and hostname, rather than redeploying the upstream repo's `derek`
# out from under whoever is using it. Unset upstream, where the bare id is the
# one people already know.
branch_tenant_id() {
  local id
  id="$(printf '%s' "$1" | sed -E 's#^(workshop|demo)[-/]##')"
  sanitize_id "${TENANT_PREFIX:+${TENANT_PREFIX}-}${id}"
}
tenant_db_name()   { printf 'otterworks_%s' "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/_/g; s/^_*//; s/_*$//')"; }
# The tenant's own Postgres login. It owns only otterworks_<id>; the RDS master
# credential stays with the runner and is never handed to tenant services.
tenant_db_role()   { printf '%s_app' "$(tenant_db_name "$1")"; }

# ---- Per-tenant AWS identity -------------------------------------------------
# Tenant pods never assume the shared otterworks-<svc>-dev roles (those trust
# only the golden namespace). Each tenant gets one role per AWS-using service,
# trusted by exactly system:serviceaccount:otterworks-<id>:<svc>, that reaches
# only its own S3 prefix and its own DynamoDB tables. Every other service runs
# with no AWS identity at all.
TENANT_AWS_SERVICES="file-service notification-service audit-service"
# Permissions boundary every tenant role is created under (defined in
# demo-platform/infra/terraform/iam_dashboard.tf). The runner may only create
# roles that carry it, so it cannot mint a role broader than tenant scope.
TENANT_IRSA_BOUNDARY_NAME="${TENANT_IRSA_BOUNDARY_NAME:-otterworks-tenant-workload-boundary}"
# IAM role names cap at 64 chars, so the id is hashed; the Tenant tag keeps it
# readable. The otterworks-t- prefix is what the runner's IAM policy scopes to.
tenant_iam_role_name() {
  printf 'otterworks-t-%s-%s' "$(printf '%s' "$(sanitize_id "$2")" | sha256sum | cut -c1-10)" "$1"
}
tenant_ddb_table() { printf '%s-t-%s' "$1" "$(sanitize_id "$2")"; }
tenant_s3_prefix() { printf 'tenants/%s/' "$(sanitize_id "$1")"; }

require_bins() {
  for bin in "$@"; do
    command -v "$bin" >/dev/null 2>&1 || { err "$bin not found"; exit 1; }
  done
}

# Load shared application-infra Terraform outputs (RDS/Redis/S3/DynamoDB/SNS/SQS
# and the per-service IRSA role ARNs). Same source of truth as deploy-dev.sh.
load_infra_outputs() {
  local d="${REPO_ROOT}/infrastructure/terraform"
  terraform -chdir="$d" init -input=false >/dev/null 2>&1 || true
  local rds; rds="$(terraform -chdir="$d" output -raw rds_endpoint 2>/dev/null || echo "")"
  RDS_HOST="${rds%%:*}"; RDS_PORT="${rds##*:}"
  [ "$RDS_PORT" = "$rds" ] && RDS_PORT=5432 || true
  S3_FILE_BUCKET="$(terraform -chdir="$d" output -raw s3_file_bucket 2>/dev/null || echo "")"
  S3_AUDIT_BUCKET="$(terraform -chdir="$d" output -raw s3_audit_archive_bucket 2>/dev/null || echo "")"
  DDB_FILE_META="$(terraform -chdir="$d" output -raw dynamodb_file_metadata_table 2>/dev/null || echo "")"
  DDB_AUDIT="$(terraform -chdir="$d" output -raw dynamodb_audit_events_table 2>/dev/null || echo "")"
  DDB_NOTIF="$(terraform -chdir="$d" output -raw dynamodb_notifications_table 2>/dev/null || echo "")"
  DDB_FOLDERS="$(terraform -chdir="$d" output -raw dynamodb_folders_table 2>/dev/null || echo "")"
  DDB_VERSIONS="$(terraform -chdir="$d" output -raw dynamodb_file_versions_table 2>/dev/null || echo "")"
  DDB_SHARES="$(terraform -chdir="$d" output -raw dynamodb_file_shares_table 2>/dev/null || echo "")"
  IRSA_JSON="$(terraform -chdir="$d" output -json irsa_role_arns 2>/dev/null || echo "{}")"
  DB_USER="${DB_USER:-otterworks_admin}"
  if [ -z "${RDS_HOST}" ]; then
    warn "Terraform outputs unavailable; services will deploy without wired config."
  fi
  resolve_db_endpoint
}

# Where the *application* services send their SQL. Distinct from RDS_HOST, which
# stays pointed at the instance itself: creating and dropping databases is
# administrative work that has no business going through a connection pooler
# (CREATE/DROP DATABASE cannot run inside the transaction a pooled connection
# may already be in).
#
# Each service holds its own pool, so connections grow with tenants x services
# against a db.t3.micro that allows ~112 of them -- around ten awake tenants.
# PgBouncer in transaction mode makes that a function of concurrent SQL instead.
#
# Only used when the pooler is actually up: a tenant deployed against a
# nonexistent Service would fail every query, which is a far worse failure than
# using more connections than we would like. Set DB_VIA_PGBOUNCER=false to force
# services back onto the instance directly.
resolve_db_endpoint() {
  DB_ENDPOINT_HOST="${RDS_HOST}"
  DB_ENDPOINT_PORT="${RDS_PORT}"
  # Schema migrations take session-level advisory locks, which a transaction
  # pooler breaks; they get the pooler's session-mode port instead. Same host,
  # so this is still one bounded set of connections to RDS.
  DB_SESSION_PORT="${RDS_PORT}"

  [ "${DB_VIA_PGBOUNCER:-true}" = "true" ] || return 0
  kubectl -n "${PGBOUNCER_NAMESPACE:-otterworks-platform}" get svc pgbouncer >/dev/null 2>&1 || {
    warn "pgbouncer not found; wiring services straight to RDS (install with demo-platform/scripts/install-pgbouncer.sh)"
    return 0
  }

  DB_ENDPOINT_HOST="pgbouncer.${PGBOUNCER_NAMESPACE:-otterworks-platform}.svc.cluster.local"
  DB_ENDPOINT_PORT=6432
  DB_SESSION_PORT=6433
}

# The role a tenant service runs as: only the per-tenant roles minted by
# ensure_tenant_aws_resources, never the shared golden-namespace roles.
tenant_irsa_arn() { echo "${T_IRSA_JSON:-{}}" | jq -r --arg s "$1" '.[$s] // empty' 2>/dev/null; }

resolve_oidc_url() {
  local url
  url="$(terraform -chdir="${REPO_ROOT}/platform/terraform" output -raw oidc_provider_url 2>/dev/null || echo "")"
  # In-cluster the platform/terraform state isn't initialized; fall back to the
  # cluster's OIDC issuer via the EKS API (the runner role has eks:DescribeCluster).
  if [ -z "${url}" ]; then
    url="$(aws eks describe-cluster --name "${EKS_CLUSTER}" --region "${AWS_REGION}" \
      --query 'cluster.identity.oidc.issuer' --output text 2>/dev/null || echo "")"
  fi
  printf '%s' "${url#https://}"
}

# Trust policy for a tenant role: one exact service account, no wildcard.
tenant_irsa_trust_policy() {
  local oidc_url="$1" ns="$2" svc="$3"
  jq -n --arg arn "arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/${oidc_url}" \
        --arg url "${oidc_url}" --arg sub "system:serviceaccount:${ns}:${svc}" '{
    Version: "2012-10-17",
    Statement: [{
      Effect: "Allow",
      Principal: { Federated: $arn },
      Action: "sts:AssumeRoleWithWebIdentity",
      Condition: { StringEquals: { ($url + ":sub"): $sub, ($url + ":aud"): "sts.amazonaws.com" } }
    }]
  }'
}

# Inline policy for a tenant role. Tables are listed by exact ARN (a wildcard
# like table/*-t-<id> would also match a tenant whose id ends in "-t-<id>"), and
# S3 is limited to the tenant's own key prefix. No Cognito, SNS, SQS or SES.
tenant_irsa_policy() {
  local svc="$1" id="$2" prefix tables=()
  prefix="$(tenant_s3_prefix "${id}")"
  case "${svc}" in
    file-service) tables=("${DDB_FILE_META}" "${DDB_FOLDERS}" "${DDB_VERSIONS}" "${DDB_SHARES}") ;;
    notification-service) tables=("${DDB_NOTIF}") ;;
    audit-service) tables=("${DDB_AUDIT}") ;;
    *) return 1 ;;
  esac
  local arns=() t
  for t in "${tables[@]}"; do
    [ -n "${t}" ] || continue
    t="arn:aws:dynamodb:${AWS_REGION}:${AWS_ACCOUNT_ID}:table/$(tenant_ddb_table "${t}" "${id}")"
    arns+=("${t}" "${t}/index/*")
  done
  jq -n --arg svc "${svc}" --arg prefix "${prefix}" \
        --arg files "${S3_FILE_BUCKET}" --arg audit "${S3_AUDIT_BUCKET}" \
        --args '$ARGS.positional as $tables | {
    Version: "2012-10-17",
    Statement: (
      if $svc == "file-service" then [
        { Sid: "TenantTables", Effect: "Allow", Resource: $tables,
          Action: ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                   "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan"] },
        { Sid: "TenantObjects", Effect: "Allow",
          Resource: ["arn:aws:s3:::\($files)/\($prefix)*"],
          Action: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"] },
        { Sid: "TenantPrefixList", Effect: "Allow",
          Resource: ["arn:aws:s3:::\($files)"], Action: ["s3:ListBucket"],
          Condition: { StringLike: { "s3:prefix": ["\($prefix)*"] } } }
      ]
      elif $svc == "notification-service" then [
        { Sid: "TenantTables", Effect: "Allow", Resource: $tables,
          Action: ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"] }
      ]
      else [
        { Sid: "TenantTables", Effect: "Allow", Resource: $tables,
          Action: ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query",
                   "dynamodb:Scan", "dynamodb:BatchWriteItem"] },
        { Sid: "TenantArchive", Effect: "Allow",
          Resource: ["arn:aws:s3:::\($audit)/\($prefix)*"], Action: ["s3:PutObject"] }
      ] end)
  }' "${arns[@]}"
}

# Create the tenant's DynamoDB table <shared>-t-<id> with the shared table's
# key schema and indexes, so the services see the shape they expect.
clone_ddb_table() {
  local src="$1" dst="$2" id="$3" desc input ttl
  aws dynamodb describe-table --table-name "${dst}" --region "${AWS_REGION}" >/dev/null 2>&1 && return 0
  desc="$(aws dynamodb describe-table --table-name "${src}" --region "${AWS_REGION}" --output json)" || return 1
  input="$(printf '%s' "${desc}" | jq --arg n "${dst}" --arg id "$(sanitize_id "${id}")" '
    def idx: [.[] | {IndexName, KeySchema, Projection}];
    .Table | {
      TableName: $n, AttributeDefinitions, KeySchema, BillingMode: "PAY_PER_REQUEST",
      Tags: [{Key: "demo/tenant", Value: $id}, {Key: "ManagedBy", Value: "deploy-tenant"}]
    }
    + (if .GlobalSecondaryIndexes then {GlobalSecondaryIndexes: (.GlobalSecondaryIndexes | idx)} else {} end)
    + (if .LocalSecondaryIndexes then {LocalSecondaryIndexes: (.LocalSecondaryIndexes | idx)} else {} end)')"
  aws dynamodb create-table --region "${AWS_REGION}" --cli-input-json "${input}" >/dev/null || return 1
  aws dynamodb wait table-exists --table-name "${dst}" --region "${AWS_REGION}" || return 1
  ttl="$(aws dynamodb describe-time-to-live --table-name "${src}" --region "${AWS_REGION}" --output json 2>/dev/null \
    | jq -r 'select(.TimeToLiveDescription.TimeToLiveStatus == "ENABLED") | .TimeToLiveDescription.AttributeName' 2>/dev/null)"
  if [ -n "${ttl}" ]; then
    aws dynamodb update-time-to-live --table-name "${dst}" --region "${AWS_REGION}" \
      --time-to-live-specification "Enabled=true,AttributeName=${ttl}" >/dev/null || true
  fi
}

# Shared table (from Terraform outputs) for each tenant AWS service.
tenant_shared_tables() {
  case "$1" in
    file-service) printf '%s\n' "${DDB_FILE_META}" "${DDB_FOLDERS}" "${DDB_VERSIONS}" "${DDB_SHARES}" ;;
    notification-service) printf '%s\n' "${DDB_NOTIF}" ;;
    audit-service) printf '%s\n' "${DDB_AUDIT}" ;;
  esac
}

# Mint the tenant's tables and IRSA roles; sets T_IRSA_JSON (service -> role ARN).
# Requires load_infra_outputs, AWS_ACCOUNT_ID and NS. Idempotent.
ensure_tenant_aws_resources() {
  local id="$1" oidc_url svc role t boundary
  T_IRSA_JSON="{}"
  oidc_url="$(resolve_oidc_url)"
  [ -n "${oidc_url}" ] || { warn "OIDC provider URL unavailable; tenant services get no AWS identity"; return 0; }
  boundary="arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${TENANT_IRSA_BOUNDARY_NAME}"
  for svc in ${TENANT_AWS_SERVICES}; do
    while IFS= read -r t; do
      [ -n "${t}" ] || continue
      clone_ddb_table "${t}" "$(tenant_ddb_table "${t}" "${id}")" "${id}" \
        || { err "failed to create tenant table for ${t}"; return 1; }
    done < <(tenant_shared_tables "${svc}")

    role="$(tenant_iam_role_name "${svc}" "${id}")"
    if aws iam get-role --role-name "${role}" >/dev/null 2>&1; then
      aws iam update-assume-role-policy --role-name "${role}" \
        --policy-document "$(tenant_irsa_trust_policy "${oidc_url}" "${NS}" "${svc}")" >/dev/null || return 1
    else
      aws iam create-role --role-name "${role}" --permissions-boundary "${boundary}" \
        --assume-role-policy-document "$(tenant_irsa_trust_policy "${oidc_url}" "${NS}" "${svc}")" \
        --tags "Key=demo/tenant,Value=$(sanitize_id "${id}")" "Key=Service,Value=${svc}" "Key=ManagedBy,Value=deploy-tenant" \
        >/dev/null || { err "failed to create IAM role ${role}"; return 1; }
    fi
    aws iam put-role-policy --role-name "${role}" --policy-name tenant-scope \
      --policy-document "$(tenant_irsa_policy "${svc}" "${id}")" >/dev/null \
      || { err "failed to scope IAM role ${role}"; return 1; }
    T_IRSA_JSON="$(echo "${T_IRSA_JSON}" | jq --arg s "${svc}" \
      --arg a "arn:aws:iam::${AWS_ACCOUNT_ID}:role/${role}" '. + {($s): $a}')"
    log "  IRSA: ${svc} -> ${role} (system:serviceaccount:${NS}:${svc} only)"
  done
}

# Reverse of ensure_tenant_aws_resources. Best-effort and idempotent.
delete_tenant_aws_resources() {
  local id="$1" svc role t
  for svc in ${TENANT_AWS_SERVICES}; do
    role="$(tenant_iam_role_name "${svc}" "${id}")"
    if aws iam get-role --role-name "${role}" >/dev/null 2>&1; then
      aws iam delete-role-policy --role-name "${role}" --policy-name tenant-scope >/dev/null 2>&1 || true
      if aws iam delete-role --role-name "${role}" >/dev/null 2>&1; then
        log "  deleted IAM role ${role}"
      else
        warn "  failed to delete IAM role ${role}"
      fi
    fi
    while IFS= read -r t; do
      [ -n "${t}" ] || continue
      t="$(tenant_ddb_table "${t}" "${id}")"
      aws dynamodb delete-table --table-name "${t}" --region "${AWS_REGION}" >/dev/null 2>&1 \
        && log "  deleted table ${t}" || true
    done < <(tenant_shared_tables "${svc}")
  done
}

# ---- PgBouncer userlist ------------------------------------------------------
# The shared pooler authenticates every client against one auth_file, so each
# tenant role needs an entry in the pgbouncer-auth Secret. jq filter over the
# Secret JSON: drop any line for $role, then append it again when PGB_PASSWORD
# (read from the environment, never an argv) is non-empty.
# shellcheck disable=SC2016  # jq program, not shell expansions
PGB_USERLIST_FILTER='
  .data["userlist.txt"] |= (
    (. // "" | @base64d) | split("\n")
    | map(select(length > 0 and (startswith("\"" + $role + "\" ") | not)))
    + (if ($ENV.PGB_PASSWORD // "") == "" then [] else ["\"" + $role + "\" \"" + $ENV.PGB_PASSWORD + "\""] end)
    | join("\n") + "\n" | @base64)
  | del(.metadata.managedFields)'

# pgbouncer_userlist_set ROLE, with PGB_PASSWORD in the environment (empty =
# remove). Read-modify-replace keyed on resourceVersion, so two tenant deploys
# racing on the Secret retry instead of dropping each other's entry.
pgbouncer_userlist_set() {
  local role="$1" ns="${PGBOUNCER_NAMESPACE:-otterworks-platform}" i cur
  for i in 1 2 3 4 5; do
    cur="$(kubectl -n "${ns}" get secret pgbouncer-auth -o json 2>/dev/null)" || return 1
    if printf '%s' "${cur}" | jq --arg role "${role}" "${PGB_USERLIST_FILTER}" | kubectl replace -f - >/dev/null 2>&1; then
      return 0
    fi
    sleep "$((i * 2))"
  done
  return 1
}

# Turn a per-tenant DB name (otterworks_a01) into an RFC-1123 fragment usable in
# Kubernetes resource names (otterworks-a01) so per-tenant Jobs/Secrets are named
# uniquely and concurrent teardowns don't collide on a shared resource name.
k8s_name_fragment() { printf '%s' "$1" | tr '[:upper:]_' '[:lower:]-'; }

# Create/replace a db-admin secret in a namespace WITHOUT ever putting the
# password on a process argv: the value is base64'd via a stdin pipe and the
# manifest is applied via stdin (heredoc), so it never appears in ps/cmdline.
# Requires DB_PASSWORD in the environment. Secret name defaults to
# tenant-db-admin but callers sharing a namespace (e.g. the reaper/teardown
# system namespace) MUST pass a unique name to avoid clobbering each other.
apply_db_admin_secret() {
  local ns="$1" name="${2:-tenant-db-admin}" b64
  b64="$(printf '%s' "${DB_PASSWORD}" | base64 | tr -d '\n')"
  kubectl -n "${ns}" apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ${name}
type: Opaque
data:
  PGPASSWORD: ${b64}
EOF
}

# Drop a per-tenant database via an in-cluster Job in ${run_ns}. Callers MUST
# delete the tenant namespace first so no application pods are still connected
# (otherwise DROP DATABASE races the pods' connection-pool reconnects). Requires
# load_infra_outputs to have set RDS_HOST/RDS_PORT/DB_USER, and DB_PASSWORD set.
drop_tenant_db() {
  local db="$1" run_ns="$2" role="${3:-${1}_app}" frag job secret
  frag="$(k8s_name_fragment "${db}")"
  job="tenant-db-drop-${frag}"
  secret="tenant-db-admin-${frag}"
  apply_db_admin_secret "${run_ns}" "${secret}"
  kubectl -n "${run_ns}" delete job "${job}" --ignore-not-found >/dev/null 2>&1 || true
  kubectl apply -n "${run_ns}" -f - >/dev/null <<YAML
apiVersion: batch/v1
kind: Job
metadata:
  name: ${job}
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 120
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: psql
          image: postgres:16-alpine
          env:
            - name: PGPASSWORD
              valueFrom: { secretKeyRef: { name: ${secret}, key: PGPASSWORD } }
          command: ["/bin/sh","-c"]
          args:
            - |
              CONN="host=${RDS_HOST} port=${RDS_PORT} dbname=otterworks user=${DB_USER} sslmode=prefer connect_timeout=10"
              psql "\$CONN" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"${db}\" WITH (FORCE)"
              psql "\$CONN" -v ON_ERROR_STOP=1 -c "DROP ROLE IF EXISTS \"${role}\""
          resources:
            requests: { cpu: 50m, memory: 64Mi }
            limits: { cpu: 200m, memory: 128Mi }
YAML
  local ok=1
  if kubectl -n "${run_ns}" wait --for=condition=complete "job/${job}" --timeout=90s >/dev/null 2>&1; then
    log "  database ${db} and role ${role} dropped."; ok=0
  else
    warn "  DB drop for ${db} did not confirm; last log lines:"
    kubectl -n "${run_ns}" logs "job/${job}" 2>/dev/null | tail -5 || true
  fi
  kubectl -n "${run_ns}" delete secret "${secret}" --ignore-not-found >/dev/null 2>&1 || true
  kubectl -n "${run_ns}" delete job "${job}" --ignore-not-found >/dev/null 2>&1 || true
  return "${ok}"
}

# Secret handling: values are collected into SECRET_KV and later written to a
# locked-down temp values file passed to helm via -f, so secret values never
# appear in the process argument list (ps / /proc/*/cmdline). Mirrors deploy-dev.sh.
add_secret() { SECRET_KV+=("$1" "$2"); }
urlencode()  { jq -rn --arg s "$1" '$s|@uri'; }

# Build per-service Helm --set flags (EXTRA_ARGS) + secret pairs (SECRET_KV) for
# a tenant. Requires these tenant-scoped globals to be set by the caller:
#   T_REDIS_HOST, T_MEILI_URL, T_DB_NAME, T_WIRE_EVENTING (true/false),
#   T_DB_USER/T_DB_PASSWORD (the tenant's own Postgres role -- never the RDS
#   master), T_IRSA_JSON and T_S3_PREFIX/T_DDB_* (from ensure_tenant_aws_resources)
build_helm_args() {
  local service=$1
  EXTRA_ARGS=()
  SECRET_KV=()

  # replicas=1 (cost control) and disable the per-service NetworkPolicy — the
  # tenant namespace ships ONE NetworkPolicy that allows intra-namespace traffic.
  EXTRA_ARGS+=(--set replicaCount=1 --set networkPolicy.enabled=false)
  # Force ClusterIP for EVERY service so no tenant gets its own LoadBalancer/ELB
  # (some charts, e.g. api-gateway, default to LoadBalancer). External access is
  # only ever through the ONE shared ingress. See docs/MULTI-TENANT-DEMO-PLAN.md §3.
  EXTRA_ARGS+=(--set service.type=ClusterIP)

  local role; role="$(tenant_irsa_arn "$service")"
  if [ -n "$role" ]; then EXTRA_ARGS+=(--set "serviceAccount.roleArn=${role}"); fi
  if [[ " ${JVM_SERVICES} " == *" ${service} "* ]]; then
    EXTRA_ARGS+=(--set resources.requests.memory=512Mi --set resources.limits.memory=1024Mi --set resources.limits.cpu=1000m)
  fi

  case "$service" in
    web-app|admin-dashboard)
      # SHARED ingress: frontends are ClusterIP (set above) + per-tenant ingress.
      EXTRA_ARGS+=(--set ingress.enabled=false)
      EXTRA_ARGS+=(--set-string config.API_GATEWAY_URL=http://api-gateway:8080)
      return 0 ;;
  esac

  local port="${CONTAINER_PORT[$service]:-}"
  if [ -n "$port" ]; then EXTRA_ARGS+=(--set "service.port=${port}" --set "service.targetPort=${port}"); fi
  EXTRA_ARGS+=(--set ingress.enabled=false)

  if [ -n "${JWT_SECRET}" ]; then
    case "$service" in
      api-gateway|auth-service|document-service|collab-service|admin-service)
        add_secret JWT_SECRET "${JWT_SECRET}" ;;
    esac
  fi

  local sns_topic=""; local sqs_notif=""
  if [ "${T_WIRE_EVENTING}" = "true" ]; then
    sns_topic="${SNS_TOPIC:-}"; sqs_notif="${SQS_NOTIF:-}"
  fi

  case "$service" in
    api-gateway) : ;;
    auth-service)
      EXTRA_ARGS+=(--set-string "config.SPRING_PROFILES_ACTIVE=prod")
      EXTRA_ARGS+=(--set-string "config.SPRING_DATASOURCE_URL=jdbc:postgresql://${DB_ENDPOINT_HOST}:${DB_ENDPOINT_PORT}/${T_DB_NAME}")
      EXTRA_ARGS+=(--set-string "config.SPRING_DATASOURCE_USERNAME=${T_DB_USER}")
      # Flyway runs on boot and holds a session-level advisory lock for the
      # length of the migration, so it gets its own datasource on the pooler's
      # session port; the application's own queries stay on the transaction one.
      EXTRA_ARGS+=(--set-string "config.SPRING_FLYWAY_URL=jdbc:postgresql://${DB_ENDPOINT_HOST}:${DB_SESSION_PORT}/${T_DB_NAME}")
      EXTRA_ARGS+=(--set-string "config.SPRING_FLYWAY_USER=${T_DB_USER}")
      add_secret SPRING_FLYWAY_PASSWORD "${T_DB_PASSWORD}"
      add_secret SPRING_DATASOURCE_PASSWORD "${T_DB_PASSWORD}" ;;
    file-service)
      EXTRA_ARGS+=(--set-string "config.AWS_REGION=${AWS_REGION}")
      EXTRA_ARGS+=(--set-string "config.S3_BUCKET=${S3_FILE_BUCKET}")
      EXTRA_ARGS+=(--set-string "config.S3_KEY_PREFIX=${T_S3_PREFIX}")
      EXTRA_ARGS+=(--set-string "config.DYNAMODB_TABLE=${T_DDB_FILE_META}")
      EXTRA_ARGS+=(--set-string "config.DYNAMODB_FOLDERS_TABLE=${T_DDB_FOLDERS}")
      EXTRA_ARGS+=(--set-string "config.DYNAMODB_VERSIONS_TABLE=${T_DDB_VERSIONS}")
      EXTRA_ARGS+=(--set-string "config.DYNAMODB_SHARES_TABLE=${T_DDB_SHARES}")
      EXTRA_ARGS+=(--set-string "config.REDIS_HOST=${T_REDIS_HOST}" --set-string "config.REDIS_PORT=6379")
      EXTRA_ARGS+=(--set-string "config.SNS_TOPIC_ARN=${sns_topic}") ;;
    document-service)
      EXTRA_ARGS+=(--set-string "config.REDIS_HOST=${T_REDIS_HOST}" --set-string "config.REDIS_PORT=6379")
      EXTRA_ARGS+=(--set-string "config.DOC_SVC_AWS_REGION=${AWS_REGION}")
      EXTRA_ARGS+=(--set-string "config.DOC_SVC_SNS_TOPIC_ARN=${sns_topic}")
      add_secret DOC_SVC_DATABASE_URL "postgresql+asyncpg://$(urlencode "${T_DB_USER}"):$(urlencode "${T_DB_PASSWORD}")@${DB_ENDPOINT_HOST}:${DB_ENDPOINT_PORT}/${T_DB_NAME}" ;;
    collab-service)
      EXTRA_ARGS+=(--set-string "config.HTTP_PORT=8084" --set-string "config.NODE_ENV=production")
      EXTRA_ARGS+=(--set-string "config.REDIS_HOST=${T_REDIS_HOST}" --set-string "config.REDIS_PORT=6379") ;;
    notification-service)
      EXTRA_ARGS+=(--set-string "config.AWS_REGION=${AWS_REGION}")
      EXTRA_ARGS+=(--set-string "config.REDIS_HOST=${T_REDIS_HOST}" --set-string "config.REDIS_PORT=6379")
      EXTRA_ARGS+=(--set-string "config.DYNAMODB_TABLE_NOTIFICATIONS=${T_DDB_NOTIF}")
      EXTRA_ARGS+=(--set-string "config.SNS_TOPIC_ARN=${sns_topic}")
      EXTRA_ARGS+=(--set-string "config.SQS_QUEUE_URL=${sqs_notif}") ;;
    search-service)
      EXTRA_ARGS+=(--set-string "config.AWS_REGION=${AWS_REGION}")
      EXTRA_ARGS+=(--set-string "config.REDIS_HOST=${T_REDIS_HOST}" --set-string "config.REDIS_PORT=6379")
      EXTRA_ARGS+=(--set-string "config.HOST=0.0.0.0" --set-string "config.PORT=8087")
      EXTRA_ARGS+=(--set-string "config.MEILISEARCH_URL=${T_MEILI_URL}")
      EXTRA_ARGS+=(--set-string "config.REQUIRE_AUTH=false" --set-string "config.SQS_ENABLED=false") ;;
    analytics-service)
      EXTRA_ARGS+=(--set-string "config.AWS_REGION=${AWS_REGION}")
      # Drop the nightly usage-rollup CronJob for ephemeral tenants: it is the
      # batch->event-driven demo's "before" state, unrelated to multi-tenant
      # isolation, and just burns ResourceQuota on short-lived tenants.
      EXTRA_ARGS+=(--set cronjob.enabled=false)
      EXTRA_ARGS+=(--set-string "config.ANALYTICS_HOST=0.0.0.0" --set-string "config.PORT=8088")
      # Third migration path, and the quietest: AnalyticsDb.migrate() runs Flyway
      # from the same DATABASE_URL as the Slick pool, and a failed migration
      # falls back to the in-memory store instead of crashing -- so getting this
      # wrong loses the tenant's analytics data without any pod ever going
      # unhealthy. Session port for the whole service, as with Rails. Slick here
      # opens connections per query rather than holding a pool, so this costs
      # the session pooler far less than the connection count suggests.
      EXTRA_ARGS+=(--set-string "config.DATABASE_URL=jdbc:postgresql://${DB_ENDPOINT_HOST}:${DB_SESSION_PORT}/${T_DB_NAME}")
      EXTRA_ARGS+=(--set-string "config.DATABASE_USER=${T_DB_USER}")
      add_secret DATABASE_PASSWORD "${T_DB_PASSWORD}" ;;
    admin-service)
      # Rails takes a session-level advisory lock in `db:migrate`, which runs
      # from the image's CMD on every boot and shares one connection URL with
      # the app -- so the whole service uses the session-mode port.
      EXTRA_ARGS+=(--set-string "config.DATABASE_HOST=${DB_ENDPOINT_HOST}" --set-string "config.DATABASE_PORT=${DB_SESSION_PORT}")
      EXTRA_ARGS+=(--set-string "config.DATABASE_USER=${T_DB_USER}")
      EXTRA_ARGS+=(--set-string "config.RAILS_ENV=production" --set-string "config.RAILS_LOG_TO_STDOUT=true")
      # Settings (auto-investigate, Devin credentials) and chaos flags live in
      # the tenant's Redis.
      EXTRA_ARGS+=(--set-string "config.REDIS_HOST=${T_REDIS_HOST}" --set-string "config.REDIS_PORT=6379")
      add_secret DATABASE_PASSWORD "${T_DB_PASSWORD}"
      add_secret SECRET_KEY_BASE "${SECRET_KEY_BASE}" ;;
    audit-service)
      EXTRA_ARGS+=(--set-string "config.Aws__Region=${AWS_REGION}")
      EXTRA_ARGS+=(--set-string "config.Aws__DynamoDbTable=${T_DDB_AUDIT}")
      EXTRA_ARGS+=(--set-string "config.Aws__S3ArchiveBucket=${S3_AUDIT_BUCKET}")
      EXTRA_ARGS+=(--set-string "config.Aws__S3KeyPrefix=${T_S3_PREFIX}") ;;
    report-service)
      EXTRA_ARGS+=(--set-string "config.DB_HOST=${DB_ENDPOINT_HOST}" --set-string "config.DB_PORT=${DB_ENDPOINT_PORT}")
      EXTRA_ARGS+=(--set-string "config.DB_NAME=${T_DB_NAME}" --set-string "config.DB_USER=${T_DB_USER}")
      add_secret DB_PASSWORD "${T_DB_PASSWORD}" ;;
  esac
}
