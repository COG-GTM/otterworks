#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Tests for the batch deploy's capacity preflight and its lifecycle flags.
#
# A batch brings the whole roster up at once, so the fleet is bounded by total
# pod IPs rather than by concurrent use -- permanently so with --always-on,
# where nothing ever scales back to zero. Deploying past that ceiling does not
# fail fast: pods sit Pending and each tenant times out in turn, half the roster
# in and half out. These tests pin the check that stops it, pin that it stays
# out of the way when there is room or when the operator overrides it, and pin
# that staying awake is something the operator asks for.
#
# The batch script is run for real, from a copy whose deploy-tenant.sh, aws and
# kubectl are stubs; nothing here touches an account or a cluster.
# ------------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
nope() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else nope "$1 (expected '$3', got '$2')"; fi; }
said() { if grep -q -- "$2" "${WORK}/out"; then ok "$1"; else nope "$1 (not in output: '$2')"; fi; }

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
mkdir -p "${WORK}/scripts/lib" "${WORK}/bin"
cp "${SCRIPT_DIR}/deploy-tenant-batch.sh" "${WORK}/scripts/"
cp "${SCRIPT_DIR}/lib/tenant-common.sh" "${WORK}/scripts/lib/"

# Records the tenants a run would have deployed. Like the real script it clears
# demo/deployed-at on the way in and stamps it on the way out, withholding it --
# while still exiting 0 -- for a tenant named in INCOMPLETE, which is what a
# failed Helm install leaves.
cat > "${WORK}/scripts/deploy-tenant.sh" <<'EOS'
#!/usr/bin/env bash
echo "deploy:$1 $* tag=${OTTERWORKS_IMAGE_TAG_api_gateway:-unset}" >> "${DEPLOY_LOG}"
rm -f "${MARKER_DIR}/otterworks-$1"
case " ${INCOMPLETE:-} " in *" $1 "*) exit 0 ;; esac
: > "${MARKER_DIR}/otterworks-$1"
EOS

# What EC2 reports across the karpenter.sh/discovery subnets: the number matched
# and the free addresses in them. Both come back from JMESPath as floats, hence
# the ".0"; N_SUBNETS unset means the call itself produced nothing.
#
# Where a real JMESPath is available, --query is answered by evaluating the
# expression the script actually sent against canned subnet JSON, rather than by
# printing what its author expected the expression to produce. That distinction
# is not academic: `join(` `, ...)` -- a JSON literal holding a bare space, which
# is not valid JSON -- evaluates to the empty string, so the two numbers arrived
# glued together and the check silently measured nothing on every run, while a
# stub that fabricated two fields passed the whole suite.
cat > "${WORK}/bin/aws" <<'EOS'
#!/usr/bin/env bash
case "$*" in
  *describe-images*)
    echo "${*##*--repository-name }" | sed 's/ .*//' >> "${ECR_LOG}"
    echo "v1"; exit 0 ;;
  *describe-subnets*)
    [ -n "${N_SUBNETS-}" ] || { [ -n "${FREE_IPS}" ] || exit 0; N_SUBNETS=2; }
    if [ -n "${JMESPATH_OK:-}" ]; then
      query=""
      while [ $# -gt 0 ]; do
        [ "$1" = "--query" ] && { query="$2"; break; }
        shift
      done
      # --output text on a string result prints the string. AvailableIpAddress-
      # Count is a number, and awscli renders the sum as a float, which is what
      # the script's trailing sed is for.
      N_SUBNETS="${N_SUBNETS}" FREE_IPS="${FREE_IPS:-0}" python3 -c '
import json, os, sys
import jmespath
n, free = int(os.environ["N_SUBNETS"]), int(os.environ["FREE_IPS"])
subnets = [{"AvailableIpAddressCount": free if i == 0 else 0} for i in range(n)]
out = jmespath.search(sys.argv[1], json.loads(json.dumps({"Subnets": subnets})))
print("None" if out is None else out)
' "${query}"
      exit 0
    fi
    printf '%s.0 %s.0\n' "${N_SUBNETS}" "${FREE_IPS:-0}"; exit 0 ;;
  *) exit 0 ;;
esac
EOS

# EXISTING_NS is the namespaces the cluster already has, and MARKER_DIR holds a
# file per namespace carrying demo/deployed-at -- a file rather than a variable
# because the child deploy adds and removes them as a run progresses. Default:
# an empty cluster, and a NodePool wide enough not to warn.
cat > "${WORK}/bin/kubectl" <<'EOS'
#!/usr/bin/env bash
matches() { for n in $1; do case "$2" in *"${n}"*) return 0 ;; esac; done; return 1; }
case "$*" in
  *"get --raw /healthz"*)              [ -z "${NO_CLUSTER:-}" ]; exit $? ;;
  *"get nodepool"*)                    echo 400; exit 0 ;;
  *"annotations.demo/deployed-at"*)
    for f in "${MARKER_DIR}"/*; do
      [ -e "${f}" ] || continue
      case "$*" in *"${f##*/}"*) echo "2026-01-01T00:00:00Z"; exit 0 ;; esac
    done
    exit 0 ;;
  *"get ns"*)                          matches "${EXISTING_NS:-}" "$*"; exit $? ;;
  *)                                   exit 0 ;;
esac
EOS

for stub in helm terraform; do printf '#!/usr/bin/env bash\nexit 0\n' > "${WORK}/bin/${stub}"; done
chmod +x "${WORK}/scripts/deploy-tenant.sh" "${WORK}/bin"/*

export PATH="${WORK}/bin:${PATH}"
export DB_PASSWORD=stub JWT_SECRET=stub SECRET_KEY_BASE=stub
export DEPLOY_LOG="${WORK}/deploy.log"
export MARKER_DIR="${WORK}/markers"; mkdir -p "${MARKER_DIR}"
export FREE_IPS="" EXISTING_NS="" DEPLOYED_NS="" INCOMPLETE=""
# The stub answers --query for real where jmespath is importable (it ships with
# awscli), and falls back to canned fields where it is not, so the suite still
# runs on a box without it -- with one property fewer pinned, hence the note.
if python3 -c 'import jmespath' 2>/dev/null; then
  export JMESPATH_OK=1
else
  echo "  note - python3 jmespath unavailable: --query is answered from canned fields, not evaluated"
fi
export ECR_LOG="${WORK}/ecr.log"; : > "${ECR_LOG}"

# Two full-profile tenants: 30 pod IPs.
run_batch() {
  : > "${DEPLOY_LOG}"
  : > "${ECR_LOG}"
  rm -f "${MARKER_DIR}"/*
  # The state an earlier run left on the cluster.
  for n in ${DEPLOYED_NS:-}; do : > "${MARKER_DIR}/otterworks-${n}"; done
  "${WORK}/scripts/deploy-tenant-batch.sh" "$@" "Ada Lovelace" "Grace Hopper" >"${WORK}/out" 2>&1
  echo "$?"
}
# Sorted: the batch deploys concurrently, so completion order is not fixed.
deployed() { sed 's/ .*//' "${DEPLOY_LOG}" | sort | tr '\n' ' ' | sed 's/ $//'; }
deploy_flags() { grep -c -- '--always-on' "${DEPLOY_LOG}"; }

echo "batch deploy capacity preflight"

FREE_IPS=12; rc="$(run_batch)"
check "refuses a roster the node subnets cannot hold" "${rc}" "1"
check "deploys nothing when it refuses" "$(deployed)" ""
said "says which limit was hit" "Not enough pod IPs"

FREE_IPS=4000; rc="$(run_batch)"
check "deploys when there is room" "${rc}" "0"
check "deploys every tenant" "$(deployed)" "deploy:ada-lovelace deploy:grace-hopper"

# The roster is documented as operator-editable and plenty of editors do not add
# a final newline. `read` returns non-zero on that last line having already read
# it, so the loop drops the person -- one name short, silently, and the run's own
# "N tenant(s)" line agrees with itself.
printf 'Ada Lovelace\nGrace Hopper' > "${WORK}/roster-no-eol.txt"
: > "${DEPLOY_LOG}"; : > "${ECR_LOG}"; rm -f "${MARKER_DIR}"/*
FREE_IPS=4000 "${WORK}/scripts/deploy-tenant-batch.sh" \
  --roster "${WORK}/roster-no-eol.txt" >"${WORK}/out" 2>&1
check "reads the last name in a roster saved without a trailing newline" \
  "$(deployed)" "deploy:ada-lovelace deploy:grace-hopper"

FREE_IPS=12; rc="$(run_batch --no-preflight)"
check "--no-preflight overrides the refusal" "${rc}" "0"
check "--no-preflight still deploys everyone" "$(deployed)" "deploy:ada-lovelace deploy:grace-hopper"

# An unreadable subnet count must not become an outage of the deploy path: the
# check is advisory when it cannot measure.
FREE_IPS=""; rc="$(run_batch)"
check "proceeds when EC2 capacity cannot be read" "${rc}" "0"
said "warns that it could not measure" "Could not read subnet capacity"

# JMESPath sum([]) is 0, not null, so a cluster whose subnets carry no discovery
# tag measures "0 free" -- a number, and one no roster fits in. Refusing on it
# blames capacity for what is a tagging or EKS_CLUSTER mismatch.
export N_SUBNETS=0; FREE_IPS=0; rc="$(run_batch)"
check "does not refuse a roster when no subnet carries the discovery tag" "${rc}" "0"
said "  and says the tag is what is missing" "No subnet is tagged karpenter.sh/discovery"
unset N_SUBNETS

# core tenants are 7 pods, not 15, so the same subnet holds more of them.
FREE_IPS=20; rc="$(run_batch --profile core)"
check "sizes the roster by profile" "${rc}" "0"

# deploy-tenant.sh reads TENANT_PROFILE as its own default, so sizing that ignored
# it would refuse a roster the tenants it goes on to deploy would have fitted in.
FREE_IPS=20; rc="$(TENANT_PROFILE=core run_batch)"
check "sizes by TENANT_PROFILE when --profile is not given" "${rc}" "0"

# The tag is the same for every tenant, and a throttled lookup costs the tenant
# a service: one question per service, not per service per tenant.
FREE_IPS=4000; rc="$(run_batch --profile core)"
check "resolves each service's image tag once for the whole roster" "$(wc -l < "${ECR_LOG}" | tr -d ' ')" "5"
check "  and hands it to the deploys" "$(grep -c 'tag=v1' "${DEPLOY_LOG}")" "2"

# ...and not at all when the partition leaves nothing to deploy, which is how a
# re-run of a finished roster ends.
EXISTING_NS="otterworks-ada-lovelace otterworks-grace-hopper"
DEPLOYED_NS="ada-lovelace grace-hopper"
rc="$(run_batch)"
check "asks ECR nothing when every tenant is already deployed" "$(wc -l < "${ECR_LOG}" | tr -d ' ')" "0"
check "  and still succeeds" "${rc}" "0"
EXISTING_NS=""; DEPLOYED_NS=""

# ...nor when the operator has already named the tag: deploy-tenant.sh prefers
# --image-tag over anything resolved here, so the answers would be thrown away.
rc="$(run_batch --profile core --image-tag v9)"
check "asks ECR nothing when --image-tag names the tag" "$(wc -l < "${ECR_LOG}" | tr -d ' ')" "0"
check "  and passes the pinned tag down" "$(grep -c -- '--image-tag v9' "${DEPLOY_LOG}")" "2"

# --dry-run is where a 95-name roster is sanity-checked, and whether it fits is
# most of that question -- but it is advisory here: refusing to print a plan
# helps nobody.
FREE_IPS=12; rc="$(run_batch --dry-run)"
check "--dry-run reports a roster that will not fit" "${rc}" "0"
said "  naming the limit the real run would refuse on" "Not enough pod IPs"
check "  and deploys nothing" "$(deployed)" ""

# The point of the mode is agreeing with the real run. A tenant already deployed
# is already holding its pod IPs, so sizing the whole roster after a partial
# batch refuses one the real run (which sizes the queue) would accept.
EXISTING_NS="otterworks-ada-lovelace"
DEPLOYED_NS="ada-lovelace"
FREE_IPS=20; rc="$(run_batch --dry-run)"
check "--dry-run sizes the un-deployed remainder, not the whole roster" "${rc}" "0"
if grep -q -- "Not enough pod IPs" "${WORK}/out"; then
  nope "  and does not refuse a roster the real run would accept"
else
  ok "  and does not refuse a roster the real run would accept"
fi
said "  saying which tenants it left out" "Skipping 1 deployed tenant"
# The command list is what the operator reads to decide the plan is right, so it
# has to be the same run the footprint is sized against -- not the whole roster
# printed above "Skipping 1".
if grep -q -- "deploy-tenant.sh ada-lovelace" "${WORK}/out"; then
  nope "  and lists only the tenants it would deploy"
else
  ok "  and lists only the tenants it would deploy"
fi
said "  still listing the ones it would" "deploy-tenant.sh grace-hopper"

# Nothing left to deploy is a plan too, and an empty list under "would run" reads
# as a failure to produce one.
EXISTING_NS="otterworks-ada-lovelace otterworks-grace-hopper"
DEPLOYED_NS="ada-lovelace grace-hopper"
rc="$(run_batch --dry-run)"
check "--dry-run on a finished roster succeeds" "${rc}" "0"
said "  and says there is nothing to do" "nothing to do"

# Unless there is no cluster to ask. --dry-run writes no kubeconfig, so on a
# fresh shell every namespace read fails and the roster reads as untouched --
# which must not be reported as a measurement of what is left to deploy.
NO_CLUSTER=1 FREE_IPS=20; export NO_CLUSTER
rc="$(run_batch --dry-run)"
check "--dry-run without a cluster connection says so" "${rc}" "0"
said "  rather than reporting the roster as undeployed" "how much of the roster is already deployed is unknown"
unset NO_CLUSTER
EXISTING_NS=""; DEPLOYED_NS=""

# Staying awake is opt-in. Without the flag a tenant idles like any other, which
# is the whole point of it being a flag: the exemption holds its compute and pod
# IPs whether or not anyone opens the URL.
FREE_IPS=4000; rc="$(run_batch)"
check "does not make tenants always-on by default" "$(deploy_flags)" "0"
said "  and says they will idle" "scale to zero after an hour idle"

rc="$(run_batch --always-on)"
check "--always-on succeeds" "${rc}" "0"
check "  passes the flag to every tenant" "$(deploy_flags)" "2"
said "  and says the fleet is permanently reserved" "reserved permanently"

# A TTL that is not "none" buys an expiry and loses the demo/persistent label,
# which is the only thing standing between a script-deployed tenant and the
# orphan sweep. That roster is deleted long before its TTL, so the run says so.
FREE_IPS=4000; rc="$(run_batch --ttl 8h)"
check "--ttl 8h still deploys" "${rc}" "0"
said "  and warns the orphan sweep would delete the roster first" "orphan sweep"

rc="$(run_batch)"
check "the default TTL succeeds" "${rc}" "0"
if grep -q -- "orphan sweep" "${WORK}/out"; then
  nope "does not warn about the orphan sweep for a persistent roster"
else
  ok "does not warn about the orphan sweep for a persistent roster"
fi

# Resuming a half-finished roster. deploy-tenant.sh creates the namespace in its
# first seconds, so "namespace exists" is also what a deploy that died at the
# database or Helm step leaves behind: skipping on that alone would report the
# roster complete while leaving those people with a shell of a tenant.
FREE_IPS=4000
EXISTING_NS="otterworks-ada-lovelace" DEPLOYED_NS="ada-lovelace"
rc="$(run_batch)"
check "skips a tenant that finished deploying" "$(deployed)" "deploy:grace-hopper"
check "  and succeeds" "${rc}" "0"
said "  and counts it as deployed, not attempted" "Skipping 1 deployed tenant"

DEPLOYED_NS=""
rc="$(run_batch)"
check "retries a tenant left half-built by an earlier run" "$(deployed)" \
  "deploy:ada-lovelace deploy:grace-hopper"
said "  and says so" "Retrying 1 incomplete tenant"
EXISTING_NS=""

# A tenant whose services did not all install is not deployed, however the child
# script exited: it is the one a re-run has to pick up, so the batch cannot call
# the roster complete over it.
INCOMPLETE="ada-lovelace"; rc="$(run_batch)"
check "fails a tenant that came back without every service" "${rc}" "1"
said "  and names it as incomplete" "services missing, tenant incomplete"
said "  and reports the other one deployed" "1 deployed"

# ...including when the tenant deployed cleanly once before. The marker is set
# with `kubectl annotate`, so the namespace re-apply does not prune it: if the
# child did not clear it, this run would be judged complete on the strength of
# the previous one and the roster would report a service-less tenant as fine.
DEPLOYED_NS="ada-lovelace grace-hopper"; rc="$(run_batch --redeploy)"
check "a redeploy that loses a service is not covered by the old marker" "${rc}" "1"
said "  and still names it incomplete" "services missing, tenant incomplete"
DEPLOYED_NS=""; INCOMPLETE=""

"${WORK}/scripts/deploy-tenant-batch.sh" --profile >"${WORK}/out" 2>&1; rc="$?"
check "rejects a flag with no value" "${rc}" "1"
said "  and says which flag" "--profile needs a value"

# Sizing reads anything that is not 'core' as 'full', so a typo would size the
# roster wrong here and then fail every deploy separately in the children.
FREE_IPS=999; rc="$(run_batch --profile ful)"
check "rejects an unknown profile up front" "${rc}" "1"
said "  and names the one it got" "got 'ful'"
check "  deploying nothing" "$(deployed)" ""
FREE_IPS=999; rc="$(TENANT_PROFILE=ful run_batch)"
check "rejects an unknown TENANT_PROFILE too" "${rc}" "1"

# An accented name has to derive the same id on every operator's box: these
# tenants are persistent, so a second spelling is a standing namespace, database
# and S3 prefix that nothing ever reclaims. iconv's //TRANSLIT is locale-
# dependent -- under C/POSIX glibc writes '?' where a UTF-8 locale folds the
# accent -- and a batch is as likely to be run from cron, where LANG is unset.
FREE_IPS=4000
run_named() {
  : > "${DEPLOY_LOG}"; rm -f "${MARKER_DIR}"/*
  "${WORK}/scripts/deploy-tenant-batch.sh" "$@" >"${WORK}/out" 2>&1
  echo "$?"
}
rc="$(LC_ALL=POSIX run_named "João Esteves")"
check "transliterates an accented name under a non-UTF-8 locale" "${rc}" "0"
check "  to the same id a UTF-8 locale gives" "$(deployed)" "deploy:joao-esteves"

# And where no locale can (a box with no C.UTF-8, or musl's iconv): refuse, so
# nobody gets a permanent tenant under a name they cannot recognise.
cat > "${WORK}/bin/iconv" <<'EOS'
#!/usr/bin/env bash
sed 's/[^ -~]/?/g'
EOS
chmod +x "${WORK}/bin/iconv"
rc="$(run_named "João Esteves")"
check "refuses a name nothing on the box can transliterate" "${rc}" "1"
said "  and says why" "did not transliterate to ASCII"
check "  deploying nothing" "$(deployed)" ""
rm -f "${WORK}/bin/iconv"

# The quieter failure: an iconv that rejects //TRANSLIT outright (musl's) writes
# nothing and exits nonzero, so there is no '?' to catch -- the name comes back
# untouched and slugging would dash out each byte of the 'ã' into the
# plausible-looking, and wrong, jo-o-esteves.
cat > "${WORK}/bin/iconv" <<'EOS'
#!/usr/bin/env bash
echo "iconv: conversions from UTF-8 to ASCII//TRANSLIT are not supported" >&2
exit 1
EOS
chmod +x "${WORK}/bin/iconv"
rc="$(run_named "João Esteves")"
check "refuses a name when iconv cannot transliterate at all" "${rc}" "1"
said "  rather than deriving an id from the raw name" "did not transliterate to ASCII"
check "  deploying nothing" "$(deployed)" ""
# An ASCII name needs no transliteration, so the same broken iconv is no reason
# to refuse the rest of the roster.
rc="$(run_named "Jake Cosme")"
check "  but still deploys a name that was already ASCII" "$(deployed)" "deploy:jake-cosme"
check "  succeeding" "${rc}" "0"
rm -f "${WORK}/bin/iconv"

# --- load_infra_outputs reads the state once ----------------------------------
# The values wired here are the tenant's database, buckets and IRSA roles: get
# one wrong and the tenant comes up looking healthy and talking to nothing. The
# read is one `terraform output -json` rather than eleven `-raw` calls, so what
# has to hold is that every value still arrives, that a missing output is empty
# rather than the string "null" (which would reach a ConfigMap), and that a
# state that cannot be read says so instead of wiring blanks silently.
(
  TFDIR="${WORK}/tfhome"; mkdir -p "${TFDIR}/infrastructure/terraform" "${TFDIR}/bin"
  cat > "${TFDIR}/bin/terraform" <<'EOS'
#!/usr/bin/env bash
echo "$*" >> "${TF_CALLS}"
[ -z "${TF_FAIL:-}" ] || exit 1
case "$*" in
  *"output -json"*) cat "${TF_JSON}" ;;
  *) exit 0 ;;
esac
EOS
  chmod +x "${TFDIR}/bin/terraform"
  printf '#!/usr/bin/env bash\nexit 1\n' > "${TFDIR}/bin/kubectl"  # no pgbouncer
  chmod +x "${TFDIR}/bin/kubectl"
  export PATH="${TFDIR}/bin:${PATH}"
  export REPO_ROOT="${TFDIR}" TF_CALLS="${TFDIR}/calls" TF_JSON="${TFDIR}/out.json"
  mkdir -p "${TFDIR}/infrastructure/terraform/.terraform"
  export OTTERWORKS_TF_INIT_READY=1
  # shellcheck disable=SC1090
  . "${WORK}/scripts/lib/tenant-common.sh"

  cat > "${TF_JSON}" <<'EOS'
{
  "rds_endpoint":                 {"value": "otterworks.abc.us-east-1.rds.amazonaws.com:5432"},
  "s3_file_bucket":               {"value": "otterworks-files-dev"},
  "s3_audit_archive_bucket":      {"value": "otterworks-audit-dev"},
  "dynamodb_file_metadata_table": {"value": "otterworks-file-metadata"},
  "dynamodb_audit_events_table":  {"value": "otterworks-audit-events"},
  "dynamodb_notifications_table": {"value": "otterworks-notifications"},
  "dynamodb_folders_table":       {"value": "otterworks-folders"},
  "dynamodb_file_versions_table": {"value": "otterworks-file-versions"},
  "dynamodb_file_shares_table":   {"value": "otterworks-file-shares"},
  "irsa_role_arns":               {"value": {"file-service": "arn:aws:iam::1:role/fs"}}
}
EOS
  : > "${TF_CALLS}"
  load_infra_outputs >/dev/null 2>&1
  check "wires the RDS host and port from one state read" "${RDS_HOST}:${RDS_PORT}" \
    "otterworks.abc.us-east-1.rds.amazonaws.com:5432"
  check "  the buckets" "${S3_FILE_BUCKET} ${S3_AUDIT_BUCKET}" "otterworks-files-dev otterworks-audit-dev"
  check "  every DynamoDB table" \
    "${DDB_FILE_META} ${DDB_AUDIT} ${DDB_NOTIF} ${DDB_FOLDERS} ${DDB_VERSIONS} ${DDB_SHARES}" \
    "otterworks-file-metadata otterworks-audit-events otterworks-notifications otterworks-folders otterworks-file-versions otterworks-file-shares"
  check "  and the IRSA role ARNs" "$(irsa_arn file-service)" "arn:aws:iam::1:role/fs"
  check "asks Terraform for the outputs once, not once per value" \
    "$(grep -c 'output -json' "${TF_CALLS}")" "1"

  # An output the state does not have. Empty is the answer the per-value reads
  # gave; "null" would be wired into a ConfigMap and resolved as a hostname.
  echo '{"rds_endpoint": {"value": "db:5432"}}' > "${TF_JSON}"
  load_infra_outputs >/dev/null 2>&1
  check "a missing output is empty, not the string null" "${S3_FILE_BUCKET}" ""
  check "  and a missing irsa_role_arns is an empty object" "${IRSA_JSON}" "{}"

  # A state that cannot be read at all: nothing wired, and said out loud --
  # this is the run that would otherwise deploy 95 tenants pointed at nothing.
  export TF_FAIL=1
  # Not `$(load_infra_outputs)`: the values it sets are the assertion, and a
  # command substitution would set them in a subshell and leave the ones from
  # the successful load above in place -- a test that passes on stale state.
  load_infra_outputs >"${TFDIR}/warn" 2>&1
  check "an unreadable state wires nothing" "${RDS_HOST}${S3_FILE_BUCKET}${DDB_AUDIT}" ""
  if grep -q "Terraform outputs unavailable" "${TFDIR}/warn"; then ok "  and warns about it"
  else nope "  and warns about it (said: $(cat "${TFDIR}/warn"))"; fi
  echo "${PASS} ${FAIL}" > "${WORK}/tf-tally"
)
read -r sub_pass sub_fail < "${WORK}/tf-tally"
PASS="${sub_pass}"; FAIL="${sub_fail}"

# --- update_irsa_trust tells "no such role" from "could not ask" --------------
# The pass reads one IAM trust policy per service per tenant, serialised across
# the batch by the trust lock, so a throttled GetRole is a normal event on a
# 95-name roster. Read as "role not found" it is invisible: the deploy carries
# on, the tenant is marked deployed, and that namespace is trusted by nothing --
# its pods fail every AWS call, and a re-run skips it.
(
  IRSADIR="${WORK}/irsa"; mkdir -p "${IRSADIR}/bin"
  cat > "${IRSADIR}/bin/aws" <<'EOS'
#!/usr/bin/env bash
case "$*" in
  *"describe-cluster"*) echo "https://oidc.eks.us-east-1.amazonaws.com/id/ABC"; exit 0 ;;
  *"get-role"*)
    case "${GET_ROLE:-ok}" in
      missing)   echo "An error occurred (NoSuchEntity) when calling the GetRole operation" >&2; exit 254 ;;
      throttled) echo "An error occurred (Throttling) when calling the GetRole operation" >&2; exit 254 ;;
    esac
    echo '{"Statement":[{"Effect":"Allow","Principal":{"Federated":"arn:aws:iam::1:oidc-provider/x"},"Action":"sts:AssumeRoleWithWebIdentity","Condition":{}}]}'
    exit 0 ;;
  *"update-assume-role-policy"*) exit "${PUT_RC:-0}" ;;
esac
exit 0
EOS
  chmod +x "${IRSADIR}/bin/aws"
  printf '#!/usr/bin/env bash\nexit 1\n' > "${IRSADIR}/bin/terraform"   # no local state
  chmod +x "${IRSADIR}/bin/terraform"
  export PATH="${IRSADIR}/bin:${PATH}"
  # shellcheck disable=SC2034  # all read by the extracted function
  REPO_ROOT="${IRSADIR}"; NS="otterworks-ada-lovelace"; EKS_CLUSTER="c"; AWS_REGION="us-east-1"
  IRSA_JSON='{"file-service":"arn:aws:iam::1:role/fs"}'
  log()  { echo "$*"; }
  warn() { echo "WARN: $*"; }
  err()  { echo "ERR: $*" >&2; }
  eval "$(sed -n '/^update_irsa_trust()/,/^}/p' "${SCRIPT_DIR}/deploy-tenant.sh")"

  rc=0; update_irsa_trust >"${IRSADIR}/out" 2>&1 || rc=$?
  check "trusts the namespace and reports the pass done" "${rc}" "0"

  # 3 is the status the caller records in INCOMPLETE, so the tenant is not
  # stamped deployed and the next batch run repairs it instead of skipping it.
  rc=0; GET_ROLE=throttled update_irsa_trust >"${IRSADIR}/out" 2>&1 || rc=$?
  check "a throttled read leaves the tenant incomplete" "${rc}" "3"
  if grep -q "could not read" "${IRSADIR}/out"; then ok "  and says the policy was unreadable"
  else nope "  and says the policy was unreadable (said: $(cat "${IRSADIR}/out"))"; fi
  if grep -q "not found" "${IRSADIR}/out"; then nope "  not that the role is absent"
  else ok "  not that the role is absent"; fi

  # A role that genuinely does not exist is not this tenant's problem: the other
  # ten still get their trust, and the deploy is complete.
  rc=0; GET_ROLE=missing update_irsa_trust >"${IRSADIR}/out" 2>&1 || rc=$?
  check "an absent role is skipped, not a failure" "${rc}" "0"

  # Writing the policy can fail for its own reasons -- and did, silently, before:
  # a warn in the log and a tenant stamped deployed with no trust.
  rc=0; PUT_RC=1 update_irsa_trust >"${IRSADIR}/out" 2>&1 || rc=$?
  check "a failed trust write leaves the tenant incomplete" "${rc}" "3"
  echo "${PASS} ${FAIL}" > "${WORK}/irsa-tally"
)
read -r sub_pass sub_fail < "${WORK}/irsa-tally"
PASS="${sub_pass}"; FAIL="${sub_fail}"

echo ""
echo "  ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
