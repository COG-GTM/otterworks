#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Tenant-isolation tests for per-tenant IRSA (scripts/lib/tenant-common.sh) and
# the Terraform that backs it.
#
# A tenant namespace runs attendee-controlled code, so these pin down that:
#   * the shared per-service roles trust only the golden namespace (no wildcard);
#   * tenant roles trust exactly one ServiceAccount (StringEquals, no wildcard);
#   * tenant policies only reach the tenant's S3 prefix and its own tables;
#   * no tenant role gets Cognito/SES/SNS/SQS, and unlisted services get no role;
#   * Helm values point tenants at their own prefix/tables/role, never shared;
#   * legacy tenant/wildcard trust is stripped from shared roles, golden kept.
#
# Pure jq + bash with aws stubbed; runs anywhere.
# ------------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
nope() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else nope "$1 (expected '$3', got '$2')"; fi; }

# shellcheck source=../lib/tenant-common.sh
source "${REPO_ROOT}/scripts/lib/tenant-common.sh"
log()  { :; }
warn() { :; }

# shellcheck disable=SC2034  # read by the sourced library
AWS_REGION="us-east-1"
AWS_ACCOUNT_ID="111122223333"
TENANT_ROLE_PATH="/otterworks-tenant/"
S3_FILE_BUCKET="otterworks-files-dev"
S3_AUDIT_BUCKET="otterworks-audit-archive-dev"
DDB_FILE_META="otterworks-file-metadata-dev"
DDB_FOLDERS="otterworks-folders-dev"
DDB_VERSIONS="otterworks-file-versions-dev"
DDB_SHARES="otterworks-file-shares-dev"
DDB_NOTIF="otterworks-notifications-dev"
DDB_AUDIT="otterworks-audit-events-dev"
OIDC_HOST="oidc.eks.us-east-1.amazonaws.com/id/ABC"
OIDC_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/${OIDC_HOST}"

echo "# naming"
check "s3 prefix" "$(tenant_s3_prefix A01)" "tenants/a01/"
check "tenant table" "$(tenant_table_name "${DDB_FILE_META}" a01)" "otterworks-tenant-a01-file-metadata-dev"
check "role name" "$(tenant_role_name a01 file-service)" "otterworks-t-a01-file-service"
long="$(tenant_role_name "a-very-long-workshop-attendee-identifier-x" notification-service)"
if [ "${#long}" -le 64 ] && [ "${long}" = "$(tenant_role_name "a-very-long-workshop-attendee-identifier-x" notification-service)" ]; then
  ok "long ids give a deterministic role name within 64 chars (${long})"
else nope "long role name '${long}' (${#long} chars)"; fi
check "role arn under tenant path" "$(tenant_role_arn a01 audit-service)" \
  "arn:aws:iam::111122223333:role/otterworks-tenant/otterworks-t-a01-audit-service"

echo "# trust policy"
trust="$(tenant_trust_policy "${OIDC_ARN}" "https://${OIDC_HOST}" otterworks-a01 file-service)"
check "exactly one statement" "$(jq '.Statement | length' <<<"${trust}")" "1"
check "sub pinned with StringEquals" "$(jq -r --arg u "${OIDC_HOST}" '.Statement[0].Condition.StringEquals[$u+":sub"]' <<<"${trust}")" \
  "system:serviceaccount:otterworks-a01:file-service"
check "aud pinned" "$(jq -r --arg u "${OIDC_HOST}" '.Statement[0].Condition.StringEquals[$u+":aud"]' <<<"${trust}")" "sts.amazonaws.com"
check "no StringLike / wildcard" "$(jq '[.. | strings | select(contains("*"))] | length' <<<"${trust}") $(jq '.Statement[0].Condition | has("StringLike")' <<<"${trust}")" "0 false"
check "federated principal is the cluster OIDC provider" "$(jq -r '.Statement[0].Principal.Federated' <<<"${trust}")" "${OIDC_ARN}"

echo "# tenant policies"
fp="$(tenant_service_policy file-service a01)"
check "file-service objects only under tenant prefix" \
  "$(jq -c '[.Statement[] | select(.Sid=="TenantObjects") | .Resource[]]' <<<"${fp}")" \
  '["arn:aws:s3:::otterworks-files-dev/tenants/a01/*"]'
check "ListBucket on bucket with s3:prefix condition" \
  "$(jq -c '.Statement[] | select(.Sid=="TenantPrefixList") | [.Action, .Resource, .Condition.StringLike["s3:prefix"]]' <<<"${fp}")" \
  '["s3:ListBucket","arn:aws:s3:::otterworks-files-dev",["tenants/a01/","tenants/a01/*"]]'
check "object statement carries no ListBucket" \
  "$(jq '[.Statement[] | select(.Sid=="TenantObjects") | .Action[] | select(.=="s3:ListBucket")] | length' <<<"${fp}")" "0"
check "file-service tables are the tenant's own" \
  "$(jq -r '[.Statement[] | select(.Sid=="TenantTables") | .Resource[] | select(endswith("/index/*") | not) | sub(".*:table/"; "")] | join(",")' <<<"${fp}")" \
  "otterworks-tenant-a01-file-metadata-dev,otterworks-tenant-a01-folders-dev,otterworks-tenant-a01-file-versions-dev,otterworks-tenant-a01-file-shares-dev"
for svc in ${TENANT_IRSA_SERVICES}; do
  p="$(tenant_service_policy "${svc}" a01)"
  check "${svc}: every resource is tenant-scoped" \
    "$(jq '[.Statement[].Resource | if type=="array" then .[] else . end
            | select((test(":table/otterworks-tenant-a01-") or test("/tenants/a01/\\*$")
                      or (test("^arn:aws:s3:::[^/]+$")))
                     | not)] | length' <<<"${p}")" "0"
  check "${svc}: no shared table ARN" \
    "$(jq --arg a "${DDB_FILE_META}|${DDB_FOLDERS}|${DDB_VERSIONS}|${DDB_SHARES}|${DDB_NOTIF}|${DDB_AUDIT}" \
        '[.. | strings | select(test(":table/(" + $a + ")($|/)"))] | length' <<<"${p}")" "0"
  check "${svc}: no Cognito/SES/SNS/SQS/IAM action" \
    "$(jq '[.Statement[].Action | if type=="array" then .[] else . end | select(test("^(cognito-idp|ses|sns|sqs|iam|sts):"))] | length' <<<"${p}")" "0"
  check "${svc}: bare-bucket resources only for ListBucket with prefix" \
    "$(jq '[.Statement[] | select([.Resource] | flatten | any(test("^arn:aws:s3:::[^/]+$")))
            | select(.Action != "s3:ListBucket" or (.Condition.StringLike["s3:prefix"] | all(startswith("tenants/a01/"))) == false)] | length' <<<"${p}")" "0"
done
ap="$(tenant_service_policy audit-service a01)"
check "audit-service can only write its prefix of the archive" \
  "$(jq -c '[.Statement[] | select(.Sid=="TenantObjects") | .Action, .Resource]' <<<"${ap}")" \
  '[["s3:PutObject"],["arn:aws:s3:::otterworks-audit-archive-dev/tenants/a01/*"]]'
np="$(tenant_service_policy notification-service a01)"
check "notification-service gets no S3" "$(jq '[.Statement[] | select(.Sid | startswith("TenantObjects") or startswith("TenantPrefix"))] | length' <<<"${np}")" "0"
for svc in auth-service admin-service document-service search-service analytics-service api-gateway collab-service; do
  if tenant_service_policy "${svc}" a01 >/dev/null 2>&1 || is_tenant_irsa_service "${svc}"; then
    nope "${svc} must not get a tenant role"
  else ok "${svc} gets no tenant role"; fi
done
other="$(tenant_service_policy file-service b02)"
check "tenant b02 policy shares no resource with a01" \
  "$(jq -n --argjson a "${fp}" --argjson b "${other}" \
      '[$a.Statement[].Resource] | flatten as $ra | [$b.Statement[].Resource] | flatten
       | map(select(. as $r | $ra | index($r))) | map(select(test("^arn:aws:s3:::[^/]+$") | not)) | length')" "0"

echo "# table clone"
spec='{"Table":{"TableName":"otterworks-file-metadata-dev","AttributeDefinitions":[{"AttributeName":"id","AttributeType":"S"},{"AttributeName":"owner_id","AttributeType":"S"}],"KeySchema":[{"AttributeName":"id","KeyType":"HASH"}],"GlobalSecondaryIndexes":[{"IndexName":"owner-index","KeySchema":[{"AttributeName":"owner_id","KeyType":"HASH"}],"Projection":{"ProjectionType":"ALL"},"IndexStatus":"ACTIVE","ItemCount":3}],"TableStatus":"ACTIVE","ItemCount":9,"TableArn":"arn:x"}}'
input="$(tenant_table_create_input "${spec}" otterworks-tenant-a01-file-metadata-dev a01)"
check "clone keeps name/keys/GSI, on-demand, tagged" \
  "$(jq -c '[.TableName, .BillingMode, .KeySchema[0].AttributeName, .GlobalSecondaryIndexes[0].IndexName, (.GlobalSecondaryIndexes[0] | keys), (.Tags[] | select(.Key=="Tenant") | .Value)]' <<<"${input}")" \
  '["otterworks-tenant-a01-file-metadata-dev","PAY_PER_REQUEST","id","owner-index",["IndexName","KeySchema","Projection"],"a01"]'
check "clone drops runtime fields" "$(jq -c '[has("TableStatus"), has("ItemCount"), has("TableArn"), has("LocalSecondaryIndexes")]' <<<"${input}")" '[false,false,false,false]'

echo "# helm values"
# build_helm_args reads many unrelated per-service globals; leave them empty.
set +u
# shellcheck disable=SC2034  # read by build_helm_args
ATTENDEE_ID="A01"; T_DB_NAME="otterworks_a01"; T_REDIS_HOST="redis"; DB_USER="u"; DB_PASSWORD="p"
# shellcheck disable=SC2034
DB_ENDPOINT_HOST="db"; DB_ENDPOINT_PORT=5432; DB_SESSION_PORT=6433; SECRET_KEY_BASE="s"; JVM_SERVICES=""
has_arg() { local a; for a in "${EXTRA_ARGS[@]}"; do [ "$a" = "$1" ] && return 0; done; return 1; }
role_arg() { local a; for a in "${EXTRA_ARGS[@]}"; do case "$a" in serviceAccount.roleArn=*) printf '%s' "${a#*=}";; esac; done; }

TENANT_ROLES_READY=" file-service notification-service audit-service "
build_helm_args file-service
check "file-service role is the tenant role" "$(role_arg)" "arn:aws:iam::111122223333:role/otterworks-tenant/otterworks-t-a01-file-service"
has_arg "config.S3_KEY_PREFIX=tenants/a01/" && ok "file-service gets tenant S3 prefix" || nope "file-service S3_KEY_PREFIX"
has_arg "config.DYNAMODB_TABLE=otterworks-tenant-a01-file-metadata-dev" && ok "file-service metadata table is per-tenant" || nope "file-service DYNAMODB_TABLE"
has_arg "config.DYNAMODB_SHARES_TABLE=otterworks-tenant-a01-file-shares-dev" && ok "file-service shares table is per-tenant" || nope "file-service DYNAMODB_SHARES_TABLE"
build_helm_args audit-service
has_arg "config.Aws__DynamoDbTable=otterworks-tenant-a01-audit-events-dev" && ok "audit table is per-tenant" || nope "audit table"
has_arg "config.Aws__S3KeyPrefix=tenants/a01/" && ok "audit archive prefix is per-tenant" || nope "audit prefix"
build_helm_args notification-service
has_arg "config.DYNAMODB_TABLE_NOTIFICATIONS=otterworks-tenant-a01-notifications-dev" && ok "notifications table is per-tenant" || nope "notifications table"
for svc in auth-service admin-service document-service; do
  build_helm_args "${svc}"
  check "${svc} gets no role annotation" "$(role_arg)" ""
done
TENANT_ROLES_READY=" "
build_helm_args file-service
check "no role annotation until the tenant role is provisioned (never a shared fallback)" "$(role_arg)" ""

echo "# shared-role trust cleanup"
golden="system:serviceaccount:otterworks:file-service"
legacy="$(jq -cn --arg u "${OIDC_HOST}" --arg g "${golden}" '{Version:"2012-10-17",Statement:[
  {Effect:"Allow",Principal:{Federated:"x"},Action:"sts:AssumeRoleWithWebIdentity",
   Condition:{StringEquals:{($u+":sub"):$g,($u+":aud"):"sts.amazonaws.com"}}},
  {Effect:"Allow",Principal:{Federated:"x"},Action:"sts:AssumeRoleWithWebIdentity",
   Condition:{StringLike:{($u+":sub"):[$g,"system:serviceaccount:otterworks-*:file-service"]},StringEquals:{($u+":aud"):"sts.amazonaws.com"}}},
  {Effect:"Allow",Principal:{Federated:"x"},Action:"sts:AssumeRoleWithWebIdentity",
   Condition:{StringEquals:{($u+":sub"):"system:serviceaccount:otterworks-a01:file-service",($u+":aud"):"sts.amazonaws.com"}}},
  {Effect:"Allow",Principal:{Federated:"x"},Action:"sts:AssumeRoleWithWebIdentity",
   Condition:{StringLike:{($u+":sub"):"system:serviceaccount:otterworks-*:file-service"},StringEquals:{($u+":aud"):"sts.amazonaws.com"}}},
  {Effect:"Allow",Principal:{Federated:"x"},Action:"sts:AssumeRoleWithWebIdentity",
   Condition:{StringEquals:{($u+":sub"):"system:serviceaccount:otterworks-b02:file-service",($u+":aud"):"sts.amazonaws.com"}}}
]}')"
cleaned="$(shared_trust_without_tenant "${legacy}" "${OIDC_HOST}" otterworks-a01)"
subs="$(jq -r --arg u "${OIDC_HOST}" '[.Statement[].Condition | (.StringEquals[$u+":sub"], .StringLike[$u+":sub"]) | select(. != null) | if type=="array" then .[] else . end] | join(",")' <<<"${cleaned}")"
check "golden kept, a01 + wildcards removed, b02 untouched" "${subs}" \
  "${golden},${golden},system:serviceaccount:otterworks-b02:file-service"
check "statements left with no subject are dropped" "$(jq '.Statement | length' <<<"${cleaned}")" "3"
check "no wildcard survives" "$(jq '[.. | strings | select(contains("*"))] | length' <<<"${cleaned}")" "0"
check "aud conditions preserved" "$(jq --arg u "${OIDC_HOST}" '[.Statement[].Condition.StringEquals[$u+":aud"]] | unique' -c <<<"${cleaned}")" '["sts.amazonaws.com"]'
check "golden-only policy is a no-op" \
  "$(shared_trust_without_tenant "$(jq -c '.Statement |= [.[0]]' <<<"${legacy}")" "${OIDC_HOST}" otterworks-a01 | jq -cS .)" \
  "$(jq -cS '.Statement |= [.[0]]' <<<"${legacy}")"

echo "# provisioning (aws stubbed)"
AWS_LOG=""
aws() {
  AWS_LOG+="$*"$'\n'
  case "$1 $2" in
    "iam get-role") return 254 ;;
    "dynamodb describe-table") [[ "$*" == *"otterworks-tenant-"* ]] && return 254; printf '%s' "${spec}" ;;
    "dynamodb describe-time-to-live") printf 'DISABLED\tNone\n' ;;
  esac
  return 0
}
# shellcheck disable=SC2034
TENANT_BOUNDARY_ARN="arn:aws:iam::111122223333:policy/otterworks-tenant/otterworks-tenant-boundary-dev"
ensure_tenant_irsa a01 otterworks-a01 "${OIDC_ARN}" "${OIDC_HOST}"
check "all tenant services ready" "${TENANT_ROLES_READY}" " file-service notification-service audit-service "
check "every create-role carries the boundary and tenant path" \
  "$(grep '^iam create-role' <<<"${AWS_LOG}" | grep -c -- "--path /otterworks-tenant/ .*--permissions-boundary ${TENANT_BOUNDARY_ARN}")" "3"
check "six tenant tables created" "$(grep -c '^dynamodb create-table' <<<"${AWS_LOG}")" "6"
check "no shared role touched" "$(grep -c 'role-name otterworks-[a-z-]*-dev' <<<"${AWS_LOG}")" "0"
AWS_LOG=""; TENANT_BOUNDARY_ARN=""
ensure_tenant_irsa a01 otterworks-a01 "${OIDC_ARN}" "${OIDC_HOST}"
check "no boundary -> nothing created, no role annotated" "${TENANT_ROLES_READY}|$(grep -c 'create-role' <<<"${AWS_LOG}")" " |0"

echo "# terraform"
irsa="${REPO_ROOT}/infrastructure/terraform/modules/irsa/main.tf"
if grep -q 'StringLike' "${irsa}" || grep -q '\${var.namespace}-\*' "${irsa}"; then
  nope "shared IRSA trust must not use StringLike / namespace wildcard"
else ok "shared IRSA trust has no StringLike / namespace wildcard"; fi
grep -q 'values   = \["system:serviceaccount:${var.namespace}:${each.key}"\]' "${irsa}" \
  && ok "shared IRSA trust pins the golden namespace SA" || nope "shared IRSA trust golden subject"
main_tf="${REPO_ROOT}/infrastructure/terraform/main.tf"
grep -q 'resource "aws_iam_policy" "tenant_boundary"' "${main_tf}" && ok "tenant permissions boundary defined" || nope "tenant boundary"
boundary="$(sed -n '/resource "aws_iam_policy" "tenant_boundary"/,/^}/p' "${main_tf}")"
if grep -Eq 'cognito|ses:|sns:|sqs:|iam:|"\*"' <<<"${boundary}"; then nope "boundary grants nothing beyond S3/DynamoDB"
else ok "boundary grants nothing beyond S3/DynamoDB"; fi
dash="${REPO_ROOT}/demo-platform/infra/terraform/iam_dashboard.tf"
sed -n '/sid       = "TenantRoleCreate"/,/^  }/p' "${dash}" | grep -q 'iam:PermissionsBoundary' \
  && ok "control plane can only create tenant roles with the boundary" || nope "TenantRoleCreate boundary condition"
[ ! -e "${REPO_ROOT}/demo-platform/scripts/enable-tenant-irsa-wildcard.sh" ] \
  && ok "wildcard trust script removed" || nope "enable-tenant-irsa-wildcard.sh still present"

echo
echo "passed: ${PASS}  failed: ${FAIL}"
[ "${FAIL}" -eq 0 ]
