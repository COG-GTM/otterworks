#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Provision demo tenants from the command line, through the dashboard.
#
# This is the scripted equivalent of clicking around ops.otterworks.app, and it
# is deliberately the *only* path a provisioner needs: the dashboard runs the
# actual work as a runner Job under the control plane's IRSA role, so the caller
# needs no cluster access and no AWS permissions beyond reading the passcode.
# See infra/terraform/iam_provisioner.tf for the credential this expects
# (`de-demo-provisioner`).
#
# The passcode comes from Secrets Manager, or from DASHBOARD_PASSCODE if it is
# already in the environment. It is never passed on a process argv: the login
# body is written to curl on stdin, and the session cookie lands in a jar with
# 0600 permissions that is removed on exit.
#
# Usage:
#   tenant.sh list
#   tenant.sh checkout <id> [branch] [ttl]     # branch defaults to workshop-<id>
#   tenant.sh checkin  <id>
#   tenant.sh extend   <id> <ttl>
#   tenant.sh status   <id>
#
# Examples:
#   tenant.sh checkout derek                   # -> workshop-derek, 8h
#   tenant.sh checkout derek workshop-derek 24h
#   OPS_HOST=https://ops.example.app tenant.sh list
# ------------------------------------------------------------------------------
set -euo pipefail

OPS_HOST="${OPS_HOST:-https://ops.otterworks.app}"
AWS_REGION="${AWS_REGION:-us-east-1}"
PASSCODE_SECRET_ID="${PASSCODE_SECRET_ID:-otterworks/dev/dashboard/passcode}"
DEFAULT_TTL="${DEFAULT_TTL:-8h}"

log()  { echo "[tenant] $*"; }
fail() { echo "[tenant] ERROR: $*" >&2; exit 1; }

for bin in curl jq; do
  command -v "${bin}" >/dev/null 2>&1 || fail "${bin} is required"
done

JAR="$(mktemp)"
chmod 600 "${JAR}"
cleanup() { rm -f "${JAR}"; }
trap cleanup EXIT

# ------------------------------------------------------------------------------

login() {
  local passcode
  passcode="${DASHBOARD_PASSCODE:-}"

  if [ -z "${passcode}" ]; then
    command -v aws >/dev/null 2>&1 ||
      fail "aws is required to read ${PASSCODE_SECRET_ID} (or set DASHBOARD_PASSCODE)"
    passcode="$(aws secretsmanager get-secret-value \
                  --region "${AWS_REGION}" \
                  --secret-id "${PASSCODE_SECRET_ID}" \
                  --query SecretString --output text 2>/dev/null)" ||
      fail "cannot read ${PASSCODE_SECRET_ID} -- is this credential the provisioner user?"
  fi

  [ -n "${passcode}" ] || fail "passcode is empty"

  local code
  code="$(jq -nc --arg p "${passcode}" '{passcode:$p}' |
            curl -sS -o /dev/null -w '%{http_code}' \
                 -c "${JAR}" -X POST "${OPS_HOST}/api/auth/login" \
                 -H 'content-type: application/json' --data-binary @-)"

  case "${code}" in
    200|204) ;;
    401) fail "passcode rejected by ${OPS_HOST}" ;;
    429) fail "rate limited by ${OPS_HOST} -- too many failed logins, wait and retry" ;;
    *)   fail "login to ${OPS_HOST} returned HTTP ${code}" ;;
  esac
}

# Fails on any non-2xx so a rejected checkout is an error rather than a silent
# no-op that leaves the caller believing a tenant exists.
api() {
  local method="$1" path="$2" body="${3:-}"
  local out code

  if [ -n "${body}" ]; then
    out="$(printf '%s' "${body}" |
             curl -sS -w '\n%{http_code}' -b "${JAR}" -X "${method}" "${OPS_HOST}${path}" \
                  -H 'content-type: application/json' --data-binary @-)"
  else
    out="$(curl -sS -w '\n%{http_code}' -b "${JAR}" -X "${method}" "${OPS_HOST}${path}")"
  fi

  code="$(printf '%s' "${out}" | tail -n1)"
  out="$(printf '%s' "${out}" | sed '$d')"

  case "${code}" in
    2*) printf '%s' "${out}" ;;
    409) fail "conflict: $(printf '%s' "${out}" | jq -r '.error // .' 2>/dev/null || printf '%s' "${out}")" ;;
    *)   fail "${method} ${path} returned HTTP ${code}: ${out}" ;;
  esac
}

# Aligned without `column`, which is not in every base image (and is absent
# from the slim images an agent platform is likely to run this in).
table() {
  jq -r '(if type == "array" then . else [.] end)
         | .[]
         | [.id, .status, (.branch // "-"), (.url // "-")]
         | @tsv' |
    awk -F'\t' '{ printf "%-14s %-10s %-22s %s\n", $1, $2, $3, $4 }'
}

# ------------------------------------------------------------------------------

cmd="${1:-}"
[ -n "${cmd}" ] || fail "usage: tenant.sh <list|checkout|checkin|extend|status> [args]"
shift || true

case "${cmd}" in
  list)
    login
    api GET /api/tenants | table
    ;;

  checkout)
    id="${1:-}"
    [ -n "${id}" ] || fail "usage: tenant.sh checkout <id> [branch] [ttl]"
    branch="${2:-workshop-${id}}"
    ttl="${3:-${DEFAULT_TTL}}"

    login
    log "checking out '${id}' from ${branch} (ttl ${ttl})..."
    api POST /api/tenants/checkout \
      "$(jq -nc --arg id "${id}" --arg b "${branch}" --arg t "${ttl}" \
              '{id:$id, branch:$b, ttl:$t, owner:"cli"}')" | table

    log "deploying -- takes a few minutes; watch with: tenant.sh status ${id}"
    ;;

  checkin)
    id="${1:-}"
    [ -n "${id}" ] || fail "usage: tenant.sh checkin <id>"

    login
    log "checking in '${id}' (namespace, database, DNS and IRSA trust are removed)..."
    api POST "/api/tenants/${id}/checkin" '{}' | table
    ;;

  extend)
    id="${1:-}" ttl="${2:-}"
    if [ -z "${id}" ] || [ -z "${ttl}" ]; then fail "usage: tenant.sh extend <id> <ttl>"; fi

    login
    api POST "/api/tenants/${id}/extend" "$(jq -nc --arg t "${ttl}" '{ttl:$t}')" | table
    ;;

  status)
    id="${1:-}"
    [ -n "${id}" ] || fail "usage: tenant.sh status <id>"

    login
    api GET "/api/tenants/${id}" |
      jq -r '"id       : \(.id)",
             "status   : \(.status)",
             "branch   : \(.branch // "-")",
             "url      : \(.url // "-")",
             "api      : \(.apiUrl // "-")",
             "expires  : \(if .expiresAt then (.expiresAt | todate) else "-" end)",
             "pods     : \(.live.readyPods // 0)/\(.live.totalPods // 0) ready"'
    ;;

  *)
    fail "unknown command '${cmd}' -- expected list, checkout, checkin, extend or status"
    ;;
esac
