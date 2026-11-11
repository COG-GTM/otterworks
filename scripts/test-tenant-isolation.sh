#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Unit tests for tenant credential/permission scoping in lib/tenant-common.sh.
#
# A tenant workload must never receive the RDS master credential or a shared
# AWS role, and the per-tenant IAM documents must not reach another tenant's
# data. kubectl/aws are not called; this runs anywhere with bash + jq.
# ------------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
nope() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else nope "$1 (expected '$3', got '$2')"; fi; }
truthy() { if [ "$2" = "true" ]; then ok "$1"; else nope "$1"; fi; }

# shellcheck source=lib/tenant-common.sh
source "${SCRIPT_DIR}/lib/tenant-common.sh"

# shellcheck disable=SC2034  # read by the sourced functions
{
  AWS_ACCOUNT_ID="111122223333"; AWS_REGION="us-east-1"
  DB_USER="otterworks_admin"; DB_PASSWORD="MASTER-SECRET"
  IRSA_JSON='{"file-service":"arn:aws:iam::111122223333:role/otterworks-file-service-dev","auth-service":"arn:aws:iam::111122223333:role/otterworks-auth-service-dev"}'
  S3_FILE_BUCKET="otterworks-files-dev"; S3_AUDIT_BUCKET="otterworks-audit-archive-dev"
  DDB_FILE_META="otterworks-file-metadata-dev"; DDB_FOLDERS="otterworks-folders-dev"
  DDB_VERSIONS="otterworks-file-versions-dev"; DDB_SHARES="otterworks-file-shares-dev"
  DDB_NOTIF="otterworks-notifications-dev"; DDB_AUDIT="otterworks-audit-events-dev"
  DB_ENDPOINT_HOST="pgbouncer"; DB_ENDPOINT_PORT=6432; DB_SESSION_PORT=6433
  T_REDIS_HOST="redis"; T_MEILI_URL="http://meilisearch:7700"; T_WIRE_EVENTING=false
  JWT_SECRET="jwt"; SECRET_KEY_BASE="skb"
  T_DB_NAME="otterworks_alice"; T_DB_USER="$(tenant_db_role alice)"; T_DB_PASSWORD="ALICE-SECRET"
  T_S3_PREFIX="$(tenant_s3_prefix alice)"
  T_DDB_FILE_META="$(tenant_ddb_table "${DDB_FILE_META}" alice)"; T_DDB_FOLDERS="$(tenant_ddb_table "${DDB_FOLDERS}" alice)"
  T_DDB_VERSIONS="$(tenant_ddb_table "${DDB_VERSIONS}" alice)"; T_DDB_SHARES="$(tenant_ddb_table "${DDB_SHARES}" alice)"
  T_DDB_NOTIF="$(tenant_ddb_table "${DDB_NOTIF}" alice)"; T_DDB_AUDIT="$(tenant_ddb_table "${DDB_AUDIT}" alice)"
  T_IRSA_JSON='{"file-service":"arn:aws:iam::111122223333:role/otterworks-t-abc-file-service"}'
}

echo "naming:"
check "tenant DB role" "$(tenant_db_role alice)" "otterworks_alice_app"
long_id="$(printf 'a%.0s' $(seq 1 60))"
r="$(tenant_db_role "$(sanitize_id "${long_id}")")"
truthy "DB role fits Postgres' 63-byte identifier limit" "$([ "${#r}" -le 63 ] && echo true)"
r="$(tenant_iam_role_name notification-service "${long_id}")"
truthy "IAM role name fits 64 chars" "$([ "${#r}" -le 64 ] && echo true)"
truthy "IAM role names differ per tenant" "$([ "$(tenant_iam_role_name file-service alice)" != "$(tenant_iam_role_name file-service bob)" ] && echo true)"
truthy "IAM role names carry the runner-scoped prefix" "$(case "$(tenant_iam_role_name file-service alice)" in otterworks-t-*) echo true ;; esac)"
check "S3 prefix ends in a slash (alice never matches alice2)" "$(tenant_s3_prefix alice)" "tenants/alice/"

echo "helm args carry only tenant-scoped credentials:"
for svc in "${ALL_SERVICES[@]}"; do
  build_helm_args "${svc}"
  all="${EXTRA_ARGS[*]} ${SECRET_KV[*]}"
  case "${all}" in *MASTER-SECRET*) nope "${svc}: master password leaked" ;; *) ok "${svc}: no master password" ;; esac
  case "${all}" in *"=${DB_USER} "*|*"=${DB_USER}") nope "${svc}: master user wired" ;; *) ok "${svc}: no master user" ;; esac
  case "${all}" in *otterworks-${svc}-dev*) nope "${svc}: shared IRSA role wired" ;; *) ok "${svc}: no shared IRSA role" ;; esac
done
build_helm_args auth-service
truthy "auth-service uses the tenant role" "$(printf '%s\n' "${EXTRA_ARGS[@]}" | grep -qx "config.SPRING_DATASOURCE_USERNAME=otterworks_alice_app" && echo true)"
truthy "auth-service gets the tenant password" "$(printf '%s\n' "${SECRET_KV[@]}" | grep -qx "ALICE-SECRET" && echo true)"
build_helm_args document-service
truthy "document-service URL uses the tenant role" "$(printf '%s\n' "${SECRET_KV[@]}" | grep -q '^postgresql+asyncpg://otterworks_alice_app:ALICE-SECRET@' && echo true)"
build_helm_args file-service
truthy "file-service runs as its tenant role" "$(printf '%s\n' "${EXTRA_ARGS[@]}" | grep -qx "serviceAccount.roleArn=arn:aws:iam::111122223333:role/otterworks-t-abc-file-service" && echo true)"
truthy "file-service writes under the tenant prefix" "$(printf '%s\n' "${EXTRA_ARGS[@]}" | grep -qx "config.S3_KEY_PREFIX=tenants/alice/" && echo true)"
truthy "file-service uses the tenant table" "$(printf '%s\n' "${EXTRA_ARGS[@]}" | grep -qx "config.DYNAMODB_TABLE=otterworks-file-metadata-dev-t-alice" && echo true)"
build_helm_args auth-service
truthy "services without a tenant role get no AWS identity" "$(printf '%s\n' "${EXTRA_ARGS[@]}" | grep -q "serviceAccount.roleArn" || echo true)"

echo "trust policy:"
doc="$(tenant_irsa_trust_policy oidc.eks.example/id/X otterworks-alice file-service)"
check "exact service-account subject" "$(echo "${doc}" | jq -r '.Statement[0].Condition.StringEquals["oidc.eks.example/id/X:sub"]')" "system:serviceaccount:otterworks-alice:file-service"
check "no StringLike / wildcard condition" "$(echo "${doc}" | jq '[.. | objects | select(has("StringLike"))] | length')" "0"
check "single statement" "$(echo "${doc}" | jq '.Statement | length')" "1"

echo "permission policies:"
for svc in ${TENANT_AWS_SERVICES}; do
  pol="$(tenant_irsa_policy "${svc}" alice)"
  check "${svc}: no bare * resource" "$(echo "${pol}" | jq '[.Statement[].Resource[] | select(. == "*")] | length')" "0"
  check "${svc}: no cognito/sns/sqs/ses/iam" "$(echo "${pol}" | jq '[.Statement[].Action[] | select(test("^(cognito-idp|sns|sqs|ses|iam):"))] | length')" "0"
  check "${svc}: tables are this tenant's only" "$(echo "${pol}" | jq '[.Statement[].Resource[] | select(startswith("arn:aws:dynamodb")) | select(test("-t-alice(/index/\\*)?$") | not)] | length')" "0"
  check "${svc}: objects are under tenants/alice/ only" "$(echo "${pol}" | jq '[.Statement[] | select(.Action | index("s3:ListBucket") | not) | .Resource[] | select(startswith("arn:aws:s3")) | select(test("/tenants/alice/\\*$") | not)] | length')" "0"
  check "${svc}: no wildcard in table names" "$(echo "${pol}" | jq '[.Statement[].Resource[] | select(startswith("arn:aws:dynamodb")) | sub("/index/\\*$"; "") | select(contains("*"))] | length')" "0"
done
pol="$(tenant_irsa_policy file-service alice)"
check "file-service list is prefix-conditioned" "$(echo "${pol}" | jq -r '.Statement[] | select(.Action == ["s3:ListBucket"]) | .Condition.StringLike["s3:prefix"][0]')" "tenants/alice/*"
check "file-service reaches its 4 tables (+ indexes)" "$(echo "${pol}" | jq '[.Statement[] | select(.Sid == "TenantTables") | .Resource[]] | length')" "8"
truthy "unknown service gets no policy" "$(tenant_irsa_policy auth-service alice >/dev/null 2>&1 || echo true)"

echo "pgbouncer userlist:"
secret='{"metadata":{"name":"pgbouncer-auth","resourceVersion":"7","managedFields":[{}]},"data":{"userlist.txt":"'"$(printf '"otterworks_admin" "m"\n"otterworks_bob_app" "b"\n' | base64 -w0)"'"}}'
out="$(printf '%s' "${secret}" | PGB_PASSWORD="p1" jq --arg role otterworks_alice_app "${PGB_USERLIST_FILTER}")"
check "adds the tenant line" "$(echo "${out}" | jq -r '.data["userlist.txt"] | @base64d')" "$(printf '"otterworks_admin" "m"\n"otterworks_bob_app" "b"\n"otterworks_alice_app" "p1"')"
check "keeps resourceVersion for optimistic concurrency" "$(echo "${out}" | jq -r '.metadata.resourceVersion')" "7"
out="$(printf '%s' "${out}" | PGB_PASSWORD="p2" jq --arg role otterworks_alice_app "${PGB_USERLIST_FILTER}")"
check "replaces, never duplicates" "$(echo "${out}" | jq -r '.data["userlist.txt"] | @base64d' | grep -c otterworks_alice_app)" "1"
out="$(printf '%s' "${out}" | PGB_PASSWORD="" jq --arg role otterworks_alice_app "${PGB_USERLIST_FILTER}")"
check "removes on empty password" "$(echo "${out}" | jq -r '.data["userlist.txt"] | @base64d')" "$(printf '"otterworks_admin" "m"\n"otterworks_bob_app" "b"')"
out="$(printf '%s' "${secret}" | PGB_PASSWORD="" jq --arg role otterworks_bob "${PGB_USERLIST_FILTER}")"
check "a role name that prefixes another leaves it alone" "$(echo "${out}" | jq -r '.data["userlist.txt"] | @base64d' | grep -c otterworks_bob_app)" "1"

echo "shared Terraform roles:"
irsa_tf="${REPO_ROOT}/infrastructure/terraform/modules/irsa/main.tf"
truthy "no namespace wildcard in the shared role trust" "$(grep -q 'namespace}-\*' "${irsa_tf}" || echo true)"
truthy "shared role trust matches StringEquals" "$(grep -A3 'condition {' "${irsa_tf}" | grep -A1 'StringEquals' | grep -q ':sub' && echo true)"
truthy "wildcard trust script is gone" "$([ ! -e "${REPO_ROOT}/demo-platform/scripts/enable-tenant-irsa-wildcard.sh" ] && echo true)"

echo "${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
