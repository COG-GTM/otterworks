#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Safety tests for the infrastructure orphan sweep.
#
# Every deletion this sweep makes is justified by "the owning cluster no longer
# exists", so the live-cluster lookup is load-bearing: if a failed lookup were
# read as "no clusters exist", the whole live estate would look orphaned and an
# armed run would delete the shared ingress. These tests pin that invariant.
#
# The aws CLI is stubbed; nothing here touches a real account.
# ------------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
nope() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else nope "$1 (expected '$3', got '$2')"; fi; }

AWS_LIST_CLUSTERS_RC=0
AWS_LIST_CLUSTERS_OUT="otterworks-dev"
DELETED=""

# Stub the CLI. The account is modelled as holding exactly one Classic ELB: the
# shared ingress, tagged to the live cluster. It must survive every scenario
# below -- if a lookup failure were read as "no clusters", this is the resource
# that would be deleted out from under every tenant.
aws() {
  local args="$*"
  case "${args}" in
    *"eks list-clusters"*)
      printf '%s' "${AWS_LIST_CLUSTERS_OUT}"; return "${AWS_LIST_CLUSTERS_RC}" ;;
    *"elb describe-load-balancers"*"--load-balancer-names"*)
      printf '3'; return 0 ;;                     # backend count
    *"elb describe-load-balancers"*)
      printf 'shared-ingress'; return 0 ;;
    *"elb describe-tags"*)
      printf '[{"Key":"kubernetes.io/cluster/otterworks-dev","Value":"owned"},'
      printf '{"Key":"kubernetes.io/service-name","Value":"ingress-nginx/ingress-nginx-controller"}]'
      return 0 ;;
    *delete*|*release-address*)
      DELETED="${DELETED} ${args}"; return 0 ;;
    *) return 0 ;;
  esac
}
kubectl() { return 0; }

# Armed, so that any deletion the sweep decides on is actually recorded by the
# stub. A prefix assignment would be reverted once `source` returns.
export DRY_RUN=false
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/infra-sweep.sh"

echo "infra-sweep safety"

# The dangerous case: a throttled or credential-less lookup must not read as
# "nothing is live".
AWS_LIST_CLUSTERS_RC=255
AWS_LIST_CLUSTERS_OUT="An error occurred (ThrottlingException): Rate exceeded"
DELETED=""
infra_sweep >/dev/null 2>&1
check "deletes nothing when the cluster lookup fails" "${DELETED# }" ""

AWS_LIST_CLUSTERS_RC=255
infra_sweep >/dev/null 2>&1
check "reports failure to its caller" "$?" "1"

# A genuinely empty account is a real answer and must still be swept.
AWS_LIST_CLUSTERS_RC=0
AWS_LIST_CLUSTERS_OUT=""
infra_sweep >/dev/null 2>&1
check "still runs when the account genuinely has no clusters" "$?" "0"

AWS_LIST_CLUSTERS_OUT="otterworks-dev"
DELETED=""
infra_sweep >/dev/null 2>&1
check "runs normally when the lookup succeeds" "$?" "0"
check "  and spares the live cluster's shared ingress" "${DELETED# }" ""

# A live cluster must never be treated as an orphan.
# shellcheck disable=SC2034  # read by cluster_is_live from the sourced sweep
LIVE_CLUSTERS="otterworks-dev"
cluster_is_live "otterworks-dev" && r=live || r=dead
check "recognises a live cluster" "${r}" "live"
cluster_is_live "otterworks-deleted" && r=live || r=dead
check "recognises a cluster that is gone" "${r}" "dead"

# ELBv2 ARNs end in .../loadbalancer/<type>/<name>/<id>. Real ARN of the shared
# ingress NLB; the name is what `describe-load-balancers` reports and what an
# operator can actually look up, the trailing segment is an opaque id.
arn="arn:aws:elasticloadbalancing:us-east-1:000000000000:loadbalancer/net/otterworks-shared-ingress/a589c9578aa918fa"
name="${arn##*loadbalancer/}"; name="${name#*/}"; name="${name%%/*}"
check "parses the load balancer name out of an ELBv2 ARN" "${name}" "otterworks-shared-ingress"

echo "${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
