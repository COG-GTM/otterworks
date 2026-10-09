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
#       * shared S3 bucket under a tenants/<ID>/ prefix + per-tenant DynamoDB
#         tables, reached through per-tenant IRSA roles (never the shared ones)
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

require_bins() {
  for bin in "$@"; do
    command -v "$bin" >/dev/null 2>&1 || { err "$bin not found"; exit 1; }
  done
}

# Load shared application-infra Terraform outputs (RDS/Redis/S3/DynamoDB/SNS/SQS
# and the inputs for per-tenant IRSA roles). Same source of truth as deploy-dev.sh.
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
  TENANT_BOUNDARY_ARN="$(terraform -chdir="$d" output -raw tenant_permissions_boundary_arn 2>/dev/null || echo "")"
  TENANT_ROLE_PATH="$(terraform -chdir="$d" output -raw tenant_role_path 2>/dev/null || echo "/otterworks-tenant/")"
  OIDC_PROVIDER_ARN="$(terraform -chdir="$d" output -raw oidc_provider_arn 2>/dev/null || echo "")"
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

# ---------- Per-tenant IRSA + data stores ----------
# Tenant code is attendee-controlled, so a tenant ServiceAccount must never hold
# the shared per-service roles (those trust only the golden namespace and grant
# whole buckets/tables). Instead each tenant gets, for the few services that
# touch AWS data directly:
#   * its own IAM role, trusted by exactly system:serviceaccount:<ns>:<svc>
#     (StringEquals, no wildcard), created under TENANT_ROLE_PATH with the
#     Terraform-managed permissions boundary;
#   * an inline policy limited to s3://<bucket>/tenants/<ID>/* (ListBucket only
#     with an s3:prefix condition) and to its own DynamoDB tables;
#   * its own copies of the DynamoDB tables (otterworks-tenant-<ID>-<table>).
# Services not listed get no role at all: in particular nothing tenant-side can
# reach the Cognito admin APIs, SES, SNS or the shared SQS queues.
TENANT_IRSA_SERVICES="file-service notification-service audit-service"
TENANT_ROLE_POLICY_NAME="tenant-scope"

tenant_s3_prefix() { printf 'tenants/%s/' "$(sanitize_id "$1")"; }

# <shared table name> <tenant id>
tenant_table_name() { printf 'otterworks-tenant-%s-%s' "$(sanitize_id "$2")" "${1#otterworks-}"; }

# <tenant id> <service>. IAM role names cap at 64 chars; long ids fall back to a
# stable hash so the name stays deterministic for teardown.
tenant_role_name() {
  local sid name; sid="$(sanitize_id "$1")"
  name="otterworks-t-${sid}-$2"
  if [ "${#name}" -gt 64 ]; then
    name="otterworks-t-$(printf '%s' "${sid}" | sha256sum | cut -c1-12)-$2"
  fi
  printf '%s' "${name}"
}

# <tenant id> <service>
tenant_role_arn() {
  printf 'arn:aws:iam::%s:role%s%s' "${AWS_ACCOUNT_ID}" "${TENANT_ROLE_PATH:-/otterworks-tenant/}" "$(tenant_role_name "$1" "$2")"
}

is_tenant_irsa_service() { [[ " ${TENANT_IRSA_SERVICES} " == *" $1 "* ]]; }

# Shared tables a tenant service gets a private copy of (one per line).
tenant_service_tables() {
  case "$1" in
    file-service)         printf '%s\n' "${DDB_FILE_META}" "${DDB_FOLDERS}" "${DDB_VERSIONS}" "${DDB_SHARES}" ;;
    notification-service) printf '%s\n' "${DDB_NOTIF}" ;;
    audit-service)        printf '%s\n' "${DDB_AUDIT}" ;;
  esac
}

# <oidc provider arn> <oidc issuer host> <namespace> <service>
tenant_trust_policy() {
  jq -cn --arg arn "$1" --arg url "${2#https://}" --arg sub "system:serviceaccount:$3:$4" '{
    Version: "2012-10-17",
    Statement: [{
      Effect: "Allow",
      Principal: { Federated: $arn },
      Action: "sts:AssumeRoleWithWebIdentity",
      Condition: { StringEquals: { ($url + ":sub"): $sub, ($url + ":aud"): "sts.amazonaws.com" } }
    }]
  }'
}

# <bucket or ""> <s3 prefix> <s3 actions csv> <dynamodb actions csv> <table>...
_tenant_policy_json() {
  local bucket=$1 prefix=$2 s3a=$3 ddba=$4; shift 4
  local tables; tables="$(printf '%s\n' "$@" | sed '/^$/d' | jq -R . | jq -cs .)"
  jq -cn --arg b "${bucket}" --arg p "${prefix}" --arg s3a "${s3a}" --arg ddba "${ddba}" \
    --arg tarn "arn:aws:dynamodb:${AWS_REGION}:${AWS_ACCOUNT_ID}:table/" --argjson t "${tables}" '
    ($s3a | split(",") | map(select(. != ""))) as $a |
    { Version: "2012-10-17",
      Statement: (
        (if $b == "" or ($a | length) == 0 then [] else
          [{ Sid: "TenantObjects", Effect: "Allow",
             Action: ($a - ["ListBucket"] | map("s3:" + .)),
             Resource: ["arn:aws:s3:::" + $b + "/" + $p + "*"] }]
          + (if ($a | index("ListBucket")) == null then [] else
              [{ Sid: "TenantPrefixList", Effect: "Allow", Action: "s3:ListBucket",
                 Resource: ("arn:aws:s3:::" + $b),
                 Condition: { StringLike: { "s3:prefix": [$p, $p + "*"] } } }] end)
        end)
        + (if ($t | length) == 0 then [] else
            [{ Sid: "TenantTables", Effect: "Allow",
               Action: ($ddba | split(",") | map("dynamodb:" + .)),
               Resource: [$t[] | ($tarn + .), ($tarn + . + "/index/*")] }] end)
      ) }'
}

# <service> <tenant id>: the inline policy for that tenant's role. Actions
# mirror the shared role minus everything not tenant-scopable.
tenant_service_policy() {
  local svc=$1 id=$2 prefix t tables=()
  prefix="$(tenant_s3_prefix "${id}")"
  while IFS= read -r t; do
    [ -n "${t}" ] && tables+=("$(tenant_table_name "${t}" "${id}")")
  done < <(tenant_service_tables "${svc}")
  case "${svc}" in
    file-service)
      _tenant_policy_json "${S3_FILE_BUCKET}" "${prefix}" "GetObject,PutObject,DeleteObject,ListBucket" \
        "GetItem,PutItem,UpdateItem,DeleteItem,Query,Scan" "${tables[@]}" ;;
    notification-service)
      _tenant_policy_json "" "" "" "GetItem,PutItem,UpdateItem,DeleteItem,Query" "${tables[@]}" ;;
    audit-service)
      _tenant_policy_json "${S3_AUDIT_BUCKET}" "${prefix}" "PutObject" \
        "PutItem,GetItem,Query,Scan,BatchWriteItem" "${tables[@]}" ;;
    *) return 1 ;;
  esac
}

# <describe-table json> <new table name> <tenant sid>: create-table input that
# clones the shared table's keys and indexes, on-demand billing.
tenant_table_create_input() {
  printf '%s' "$1" | jq -c --arg n "$2" --arg sid "$3" '.Table | {
      TableName: $n,
      BillingMode: "PAY_PER_REQUEST",
      AttributeDefinitions: .AttributeDefinitions,
      KeySchema: .KeySchema,
      Tags: [{Key: "Project", Value: "otterworks"}, {Key: "Tenant", Value: $sid}, {Key: "ManagedBy", Value: "deploy-tenant"}]
    }
    + (if (.GlobalSecondaryIndexes // []) | length > 0 then
        {GlobalSecondaryIndexes: [.GlobalSecondaryIndexes[] | {IndexName, KeySchema, Projection}]} else {} end)
    + (if (.LocalSecondaryIndexes // []) | length > 0 then
        {LocalSecondaryIndexes: [.LocalSecondaryIndexes[] | {IndexName, KeySchema, Projection}]} else {} end)'
}

# <shared table> <tenant id>
ensure_tenant_table() {
  local shared=$1 id=$2 name spec ttl
  name="$(tenant_table_name "${shared}" "${id}")"
  if aws dynamodb describe-table --region "${AWS_REGION}" --table-name "${name}" >/dev/null 2>&1; then
    return 0
  fi
  spec="$(aws dynamodb describe-table --region "${AWS_REGION}" --table-name "${shared}" --output json 2>/dev/null)" \
    || { warn "  cannot describe ${shared}; tenant table ${name} not created"; return 1; }
  aws dynamodb create-table --region "${AWS_REGION}" \
    --cli-input-json "$(tenant_table_create_input "${spec}" "${name}" "$(sanitize_id "${id}")")" >/dev/null \
    || { warn "  failed to create ${name}"; return 1; }
  aws dynamodb wait table-exists --region "${AWS_REGION}" --table-name "${name}" || true
  ttl="$(aws dynamodb describe-time-to-live --region "${AWS_REGION}" --table-name "${shared}" \
    --query 'TimeToLiveDescription.[TimeToLiveStatus,AttributeName]' --output text 2>/dev/null || echo "")"
  if [ "${ttl%%[[:space:]]*}" = "ENABLED" ]; then
    aws dynamodb update-time-to-live --region "${AWS_REGION}" --table-name "${name}" \
      --time-to-live-specification "Enabled=true,AttributeName=${ttl##*[[:space:]]}" >/dev/null 2>&1 || true
  fi
  log "  created tenant table ${name}"
}

# <tenant id> <namespace> <oidc provider arn> <oidc issuer host>
# Creates/refreshes the tenant's tables and roles. Sets TENANT_ROLES_READY to
# the services whose role is in place; build_helm_args only annotates those.
ensure_tenant_irsa() {
  local id=$1 ns=$2 oidc_arn=$3 oidc_host=$4 svc name t trust policy ok
  TENANT_ROLES_READY=" "
  if [ -z "${TENANT_BOUNDARY_ARN:-}" ] || [ -z "${oidc_arn}" ] || [ -z "${oidc_host}" ]; then
    warn "Tenant IRSA inputs unavailable (boundary/OIDC); tenant services get NO AWS role (AWS-backed features will fail)."
    return 0
  fi
  for svc in ${TENANT_IRSA_SERVICES}; do
    ok=true
    while IFS= read -r t; do
      [ -n "${t}" ] || continue
      ensure_tenant_table "${t}" "${id}" || ok=false
    done < <(tenant_service_tables "${svc}")
    name="$(tenant_role_name "${id}" "${svc}")"
    trust="$(tenant_trust_policy "${oidc_arn}" "${oidc_host}" "${ns}" "${svc}")"
    policy="$(tenant_service_policy "${svc}" "${id}")"
    if aws iam get-role --role-name "${name}" >/dev/null 2>&1; then
      aws iam update-assume-role-policy --role-name "${name}" --policy-document "${trust}" >/dev/null || ok=false
    else
      aws iam create-role --role-name "${name}" --path "${TENANT_ROLE_PATH:-/otterworks-tenant/}" \
        --assume-role-policy-document "${trust}" \
        --permissions-boundary "${TENANT_BOUNDARY_ARN}" \
        --tags "Key=Project,Value=otterworks" "Key=Tenant,Value=$(sanitize_id "${id}")" "Key=ManagedBy,Value=deploy-tenant" \
        >/dev/null || ok=false
    fi
    aws iam put-role-policy --role-name "${name}" --policy-name "${TENANT_ROLE_POLICY_NAME}" \
      --policy-document "${policy}" >/dev/null 2>&1 || ok=false
    if [ "${ok}" = true ]; then
      TENANT_ROLES_READY+="${svc} "
      log "  IRSA: ${name} -> ${ns}:${svc}"
    else
      warn "  IRSA: failed to provision ${name}; ${svc} will run without an AWS role"
    fi
  done
}

# <tenant id>: delete the tenant's roles. Safe when they are already gone.
delete_tenant_irsa_roles() {
  local id=$1 svc name
  for svc in ${TENANT_IRSA_SERVICES}; do
    name="$(tenant_role_name "${id}" "${svc}")"
    aws iam get-role --role-name "${name}" >/dev/null 2>&1 || continue
    aws iam delete-role-policy --role-name "${name}" --policy-name "${TENANT_ROLE_POLICY_NAME}" >/dev/null 2>&1 || true
    aws iam delete-role --role-name "${name}" >/dev/null \
      && log "  deleted IRSA role ${name}" || warn "  failed to delete IRSA role ${name}"
  done
}

# <tenant id>: delete the tenant's DynamoDB tables and S3 prefixes. Returns
# non-zero if any table that exists could not be deleted.
delete_tenant_data_stores() {
  local id=$1 svc t name prefix b out rc=0
  for svc in ${TENANT_IRSA_SERVICES}; do
    while IFS= read -r t; do
      [ -n "${t}" ] || continue
      name="$(tenant_table_name "${t}" "${id}")"
      if out="$(aws dynamodb delete-table --region "${AWS_REGION}" --table-name "${name}" 2>&1 >/dev/null)"; then
        log "  deleted tenant table ${name}"
      elif [[ "${out}" != *ResourceNotFoundException* ]]; then
        warn "  failed to delete tenant table ${name}: ${out}"; rc=1
      fi
    done < <(tenant_service_tables "${svc}")
  done
  prefix="$(tenant_s3_prefix "${id}")"
  for b in "${S3_FILE_BUCKET:-}" "${S3_AUDIT_BUCKET:-}"; do
    [ -n "${b}" ] || continue
    aws s3 rm "s3://${b}/${prefix}" --recursive --only-show-errors >/dev/null 2>&1 \
      || { warn "  failed to empty s3://${b}/${prefix}"; rc=1; }
  done
  return "${rc}"
}

# <namespace> <oidc issuer host>: strip statements naming this namespace's SAs
# from the SHARED per-service roles. Those roles now trust only the golden
# namespace; this removes trust added by older deploys or by the retired
# enable-tenant-irsa-wildcard.sh, so a re-deployed or torn-down tenant cannot
# keep reaching shared data. Statements trusting any other subject are kept.
remove_shared_role_tenant_trust() {
  local ns=$1 url=${2#https://} svc role doc new
  [ -n "${url}" ] || { warn "OIDC URL unavailable; skipping shared-role trust cleanup."; return 0; }
  for svc in ${TENANT_SHARED_ROLE_SERVICES:-file-service document-service notification-service search-service analytics-service audit-service auth-service admin-service api-gateway collab-service}; do
    role="otterworks-${svc}-${ENVIRONMENT:-dev}"
    doc="$(aws iam get-role --role-name "${role}" --query 'Role.AssumeRolePolicyDocument' --output json 2>/dev/null || echo "")"
    [ -n "${doc}" ] || continue
    new="$(shared_trust_without_tenant "${doc}" "${url}" "${ns}")"
    if [ "$(echo "${doc}" | jq -cS .)" != "$(echo "${new}" | jq -cS .)" ]; then
      aws iam update-assume-role-policy --role-name "${role}" --policy-document "${new}" >/dev/null \
        && log "  removed ${ns} trust from shared role ${role}" \
        || warn "  failed to clean trust for ${role}"
    fi
  done
}

# <trust doc> <oidc host> <namespace>: drop :sub values that match this
# namespace exactly, or any otterworks-* style wildcard; drop statements left
# with no :sub. Pure, so it is unit-tested.
shared_trust_without_tenant() {
  printf '%s' "$1" | jq --arg url "$2" --arg ns "$3" '
    def norm: if type == "array" then . else [.] end;
    def keep: (startswith("system:serviceaccount:" + $ns + ":") or contains("*")) | not;
    def subs: [("StringEquals", "StringLike") as $op | (.Condition[$op][$url + ":sub"] // empty)];
    .Statement |= map(
      (subs | length) as $had
      | reduce ("StringEquals", "StringLike") as $op (.;
          if (.Condition[$op][$url + ":sub"] // null) == null then .
          else (.Condition[$op][$url + ":sub"] | norm | map(select(keep))) as $k
            | if ($k | length) == 0 then .Condition[$op] |= del(.[$url + ":sub"])
              else .Condition[$op][$url + ":sub"] = (if ($k | length) == 1 then $k[0] else $k end) end
          end)
      | select($had == 0 or (subs | length) > 0)
      | if (.Condition.StringLike // null) == {} then del(.Condition.StringLike) else . end)'
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
  local db="$1" run_ns="$2" frag job secret
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
          resources:
            requests: { cpu: 50m, memory: 64Mi }
            limits: { cpu: 200m, memory: 128Mi }
YAML
  local ok=1
  if kubectl -n "${run_ns}" wait --for=condition=complete "job/${job}" --timeout=90s >/dev/null 2>&1; then
    log "  database ${db} dropped."; ok=0
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
#   T_REDIS_HOST, T_MEILI_URL, T_DB_NAME, T_WIRE_EVENTING (true/false)
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

  # Only the tenant's own role, and only once ensure_tenant_irsa provisioned it.
  # Never the shared per-service roles: they are not tenant-scoped.
  if is_tenant_irsa_service "$service" && [[ "${TENANT_ROLES_READY:-}" == *" ${service} "* ]]; then
    EXTRA_ARGS+=(--set "serviceAccount.roleArn=$(tenant_role_arn "${ATTENDEE_ID}" "${service}")")
  fi
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
      EXTRA_ARGS+=(--set-string "config.SPRING_DATASOURCE_USERNAME=${DB_USER}")
      # Flyway runs on boot and holds a session-level advisory lock for the
      # length of the migration, so it gets its own datasource on the pooler's
      # session port; the application's own queries stay on the transaction one.
      EXTRA_ARGS+=(--set-string "config.SPRING_FLYWAY_URL=jdbc:postgresql://${DB_ENDPOINT_HOST}:${DB_SESSION_PORT}/${T_DB_NAME}")
      EXTRA_ARGS+=(--set-string "config.SPRING_FLYWAY_USER=${DB_USER}")
      add_secret SPRING_FLYWAY_PASSWORD "${DB_PASSWORD}"
      add_secret SPRING_DATASOURCE_PASSWORD "${DB_PASSWORD}" ;;
    file-service)
      EXTRA_ARGS+=(--set-string "config.AWS_REGION=${AWS_REGION}")
      EXTRA_ARGS+=(--set-string "config.S3_BUCKET=${S3_FILE_BUCKET}")
      EXTRA_ARGS+=(--set-string "config.S3_KEY_PREFIX=$(tenant_s3_prefix "${ATTENDEE_ID}")")
      EXTRA_ARGS+=(--set-string "config.DYNAMODB_TABLE=$(tenant_table_name "${DDB_FILE_META}" "${ATTENDEE_ID}")")
      EXTRA_ARGS+=(--set-string "config.DYNAMODB_FOLDERS_TABLE=$(tenant_table_name "${DDB_FOLDERS}" "${ATTENDEE_ID}")")
      EXTRA_ARGS+=(--set-string "config.DYNAMODB_VERSIONS_TABLE=$(tenant_table_name "${DDB_VERSIONS}" "${ATTENDEE_ID}")")
      EXTRA_ARGS+=(--set-string "config.DYNAMODB_SHARES_TABLE=$(tenant_table_name "${DDB_SHARES}" "${ATTENDEE_ID}")")
      EXTRA_ARGS+=(--set-string "config.REDIS_HOST=${T_REDIS_HOST}" --set-string "config.REDIS_PORT=6379")
      EXTRA_ARGS+=(--set-string "config.SNS_TOPIC_ARN=${sns_topic}") ;;
    document-service)
      EXTRA_ARGS+=(--set-string "config.REDIS_HOST=${T_REDIS_HOST}" --set-string "config.REDIS_PORT=6379")
      EXTRA_ARGS+=(--set-string "config.DOC_SVC_AWS_REGION=${AWS_REGION}")
      EXTRA_ARGS+=(--set-string "config.DOC_SVC_SNS_TOPIC_ARN=${sns_topic}")
      add_secret DOC_SVC_DATABASE_URL "postgresql+asyncpg://$(urlencode "${DB_USER}"):$(urlencode "${DB_PASSWORD}")@${DB_ENDPOINT_HOST}:${DB_ENDPOINT_PORT}/${T_DB_NAME}" ;;
    collab-service)
      EXTRA_ARGS+=(--set-string "config.HTTP_PORT=8084" --set-string "config.NODE_ENV=production")
      EXTRA_ARGS+=(--set-string "config.REDIS_HOST=${T_REDIS_HOST}" --set-string "config.REDIS_PORT=6379") ;;
    notification-service)
      EXTRA_ARGS+=(--set-string "config.AWS_REGION=${AWS_REGION}")
      EXTRA_ARGS+=(--set-string "config.REDIS_HOST=${T_REDIS_HOST}" --set-string "config.REDIS_PORT=6379")
      EXTRA_ARGS+=(--set-string "config.DYNAMODB_TABLE_NOTIFICATIONS=$(tenant_table_name "${DDB_NOTIF}" "${ATTENDEE_ID}")")
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
      EXTRA_ARGS+=(--set-string "config.DATABASE_USER=${DB_USER}")
      add_secret DATABASE_PASSWORD "${DB_PASSWORD}" ;;
    admin-service)
      # Rails takes a session-level advisory lock in `db:migrate`, which runs
      # from the image's CMD on every boot and shares one connection URL with
      # the app -- so the whole service uses the session-mode port.
      EXTRA_ARGS+=(--set-string "config.DATABASE_HOST=${DB_ENDPOINT_HOST}" --set-string "config.DATABASE_PORT=${DB_SESSION_PORT}")
      EXTRA_ARGS+=(--set-string "config.DATABASE_USER=${DB_USER}")
      EXTRA_ARGS+=(--set-string "config.RAILS_ENV=production" --set-string "config.RAILS_LOG_TO_STDOUT=true")
      # Settings (auto-investigate, Devin credentials) and chaos flags live in
      # the tenant's Redis.
      EXTRA_ARGS+=(--set-string "config.REDIS_HOST=${T_REDIS_HOST}" --set-string "config.REDIS_PORT=6379")
      add_secret DATABASE_PASSWORD "${DB_PASSWORD}"
      add_secret SECRET_KEY_BASE "${SECRET_KEY_BASE}" ;;
    audit-service)
      EXTRA_ARGS+=(--set-string "config.Aws__Region=${AWS_REGION}")
      EXTRA_ARGS+=(--set-string "config.Aws__DynamoDbTable=$(tenant_table_name "${DDB_AUDIT}" "${ATTENDEE_ID}")")
      EXTRA_ARGS+=(--set-string "config.Aws__S3ArchiveBucket=${S3_AUDIT_BUCKET}")
      EXTRA_ARGS+=(--set-string "config.Aws__S3KeyPrefix=$(tenant_s3_prefix "${ATTENDEE_ID}")") ;;
    report-service)
      EXTRA_ARGS+=(--set-string "config.DB_HOST=${DB_ENDPOINT_HOST}" --set-string "config.DB_PORT=${DB_ENDPOINT_PORT}")
      EXTRA_ARGS+=(--set-string "config.DB_NAME=${T_DB_NAME}" --set-string "config.DB_USER=${DB_USER}")
      add_secret DB_PASSWORD "${DB_PASSWORD}" ;;
  esac
}
