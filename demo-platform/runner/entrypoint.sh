#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# OtterWorks Demo Platform — runner entrypoint
#
# This image is launched as a Kubernetes Job by the ops dashboard (namespace
# otterworks-platform). It carries the repo + toolchain (aws/kubectl/helm/
# terraform/jq/psql) and executes ONE mutating operation, then exits.
#
# It is deliberately thin glue: the real work is done by the EXISTING tenant
# tooling in ../scripts (deploy-tenant.sh / teardown-tenant.sh / inject-bug.sh)
# and the reaper in ../reaper/reaper.sh. This entrypoint only:
#   1. validates the tenant branch label (TENANT_BRANCH; never checked out),
#   2. transitions status in the control table (deploying -> active | error),
#   3. runs the requested op via the existing scripts,
#   4. records the resolved coordinates (url/api_url/db_name/namespace/expires)
#      and appends AUDIT events.
#
# Environment (control-plane metadata; NON-secret):
#   OP            deploy | teardown | inject | reset | reap        (required)
#   TENANT_ID     attendee id (required for deploy/teardown/inject/reset)
#   TIER          A | B                                            (default A)
#   TTL           e.g. 8h, 30m, 2d, or `never` for a perpetual tenant (default 8h)
#   REDEPLOY      true when deploying over a live tenant (CD)   (default unset)
#   IMAGE_TAG     optional pinned image tag
#   HOST_SUFFIX   ingress host suffix              (default demo.otterworks.app)
#   SCENARIO      bug-catalog scenario (for OP=inject)
#   TENANT_BRANCH tenant branch (workshop-<id>); selects image tags only, never
#                 checked out -- all scripts/charts run from the bundled tree
#   CONTROL_TABLE DynamoDB control table         (default otterworks-demo-control)
#   AWS_REGION    (default us-east-1)   EKS_CLUSTER (default otterworks-dev)
#   REPO_DIR      the image's bundled repo tree           (default /workspace)
#   ACTOR         audit actor label                       (default runner)
#
# Secrets (from Kubernetes Secret refs in the Job spec — env only, NEVER argv):
#   DB_PASSWORD, JWT_SECRET, SECRET_KEY_BASE
#
# This script never echoes secret values and never passes them on a command line;
# the underlying scripts read them straight from the environment.
# ------------------------------------------------------------------------------
set -euo pipefail

REPO_DIR="${REPO_DIR:-/workspace}"
CONTROL_TABLE="${CONTROL_TABLE:-otterworks-demo-control}"
AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER="${EKS_CLUSTER:-otterworks-dev}"
HOST_SUFFIX="${HOST_SUFFIX:-demo.otterworks.app}"
TIER="${TIER:-A}"
TTL="${TTL:-8h}"
OP="${OP:-}"

log()  { echo "[runner] $*"; }
err()  { echo "[runner] ERROR: $*" >&2; }
die()  { err "$*"; exit 1; }

# --- tenant branch: a label, never a source of code ---------------------------
# Everything this runner executes -- scripts/, scripts/lib/, demo-platform/lib/,
# the reaper and the Helm charts deploy-tenant.sh renders -- comes from the tree
# baked into this image (REPO_DIR). The runner holds the shared DB admin
# password, a cluster-wide RBAC role and the dashboard's IAM role, while a
# tenant branch can be pushed by any workshop attendee with write access. So the
# branch is NEVER fetched or checked out here: it is only passed to
# deploy-tenant.sh to pick the tenant's own service images (tenant-<id> tags),
# which run inside the tenant's namespace, not in this Job. A branch's code
# reaches its tenant through those images, never through this runner.
#
# The name must be workshop-<id>/demo-<id> (or `main`) -- the same shape the
# dashboard enforces -- so it can't smuggle options or odd characters further.
validate_tenant_branch() {
  [ -n "${TENANT_BRANCH:-}" ] || return 0
  [[ "${TENANT_BRANCH}" =~ ^((workshop|demo)[-/][A-Za-z0-9][A-Za-z0-9._-]{0,62}|main)$ ]] \
    && [[ "${TENANT_BRANCH}" != *..* ]] \
    || die "refusing TENANT_BRANCH '${TENANT_BRANCH}': expected workshop-<id>, demo-<id> or main"
  if [ -n "${REPO_HTTPS_URL:-}" ] || [ -n "${GITHUB_TOKEN:-}" ]; then
    log "REPO_HTTPS_URL/GITHUB_TOKEN are ignored: the runner never checks out tenant branches"
  fi
  log "tenant branch ${TENANT_BRANCH} selects image tags only; running the image's bundled scripts from ${REPO_DIR}"
}

# Convert a compact TTL (8h/30m/2d) to an absolute expiry epoch. Pure integer
# arithmetic so it works with busybox `date` (no GNU `date -d` needed).
#
# `never` is a perpetual tenant. It still gets a real expiry ten years out: the
# reaper skips it on the control table's `persistent` flag, and this is the
# backstop if that check ever regresses.
expiry_epoch() {
  local ttl="$1" num unit mult now
  if [ "${ttl}" = "never" ]; then
    echo $(( $(date -u +%s) + 10 * 365 * 86400 ))
    return 0
  fi
  num="${ttl%%[!0-9]*}"; unit="${ttl##*[0-9]}"
  [ -n "${num}" ] || die "invalid TTL '${ttl}'"
  case "${unit}" in
    h|H|"") mult=3600 ;;
    m|M)    mult=60 ;;
    d|D)    mult=86400 ;;
    *)      die "invalid TTL unit in '${ttl}' (use h, m, or d)" ;;
  esac
  now="$(date -u +%s)"
  echo $(( now + num * mult ))
}

run_deploy() {
  [ -n "${TENANT_ID:-}" ] || die "OP=deploy requires TENANT_ID"
  : "${DB_PASSWORD:?OP=deploy requires DB_PASSWORD (from Secret)}"
  local sid ns db url api_url exp
  sid="$(sanitize_id "${TENANT_ID}")"
  ns="$(tenant_namespace "${TENANT_ID}")"
  db="$(tenant_db_name "${TENANT_ID}")"
  url="https://t-${sid}.${HOST_SUFFIX}"
  api_url="https://api-t-${sid}.${HOST_SUFFIX}"
  exp="$(expiry_epoch "${TTL}")"

  ctl_update_status "${TENANT_ID}" deploying
  local start_action="checkout"
  [ "${REDEPLOY:-}" = "true" ] && start_action="redeploy"
  ctl_audit "${TENANT_ID}" "${start_action}" "tier=${TIER} ttl=${TTL} branch=${TENANT_BRANCH:-} ns=${ns}"

  local args=(--tier "${TIER}" --ttl "${TTL}" --host-suffix "${HOST_SUFFIX}")
  [ -n "${IMAGE_TAG:-}" ] && args+=(--image-tag "${IMAGE_TAG}")
  # Prefer images built from this tenant's own branch (see deploy-tenant.sh's
  # tag resolution) over whatever was pushed to a service's repo most recently.
  [ -n "${TENANT_BRANCH:-}" ] && args+=(--branch "${TENANT_BRANCH}")
  # Secrets (DB_PASSWORD/JWT_SECRET/SECRET_KEY_BASE) are read from the env by the
  # script; they are NOT placed on this argv.
  if "${REPO_DIR}/scripts/deploy-tenant.sh" "${TENANT_ID}" "${args[@]}"; then
    ctl_set_active "${TENANT_ID}" "${url}" "${api_url}" "${db}" "${ns}" "${exp}"
    ctl_audit "${TENANT_ID}" deploy_ok "url=${url}"
    log "deploy complete for ${TENANT_ID} (${ns})"
  else
    ctl_update_status "${TENANT_ID}" error
    ctl_audit "${TENANT_ID}" deploy_fail "deploy-tenant.sh returned non-zero"
    die "deploy failed for ${TENANT_ID}"
  fi
}

run_teardown() {
  [ -n "${TENANT_ID:-}" ] || die "OP=teardown requires TENANT_ID"
  ctl_update_status "${TENANT_ID}" draining
  # teardown-tenant.sh reads DB_PASSWORD from the env to drop the per-tenant DB.
  "${REPO_DIR}/scripts/teardown-tenant.sh" "${TENANT_ID}" \
    || err "teardown-tenant.sh reported issues (continuing to free the id)"
  ctl_update_status "${TENANT_ID}" free
  # Release the reservation lock so the id is immediately re-checkout-able
  # (otherwise a new checkout waits for the lock's ~15min DynamoDB TTL).
  ctl_release_lock "${TENANT_ID}"
  ctl_audit "${TENANT_ID}" checkin "torn down and freed"
  log "teardown complete for ${TENANT_ID}"
}

run_inject() {
  [ -n "${TENANT_ID:-}" ] || die "OP=inject requires TENANT_ID"
  [ -n "${SCENARIO:-}" ]  || die "OP=inject requires SCENARIO"
  local args=("${TENANT_ID}" "${SCENARIO}")
  [ -n "${IMAGE_TAG:-}" ] && args+=(--image-tag "${IMAGE_TAG}")
  "${REPO_DIR}/scripts/inject-bug.sh" "${args[@]}"
  ctl_audit "${TENANT_ID}" inject "scenario=${SCENARIO}"
  log "inject '${SCENARIO}' applied to ${TENANT_ID}"
}

run_reset() {
  [ -n "${TENANT_ID:-}" ] || die "OP=reset requires TENANT_ID"
  "${REPO_DIR}/scripts/inject-bug.sh" "${TENANT_ID}" reset
  ctl_audit "${TENANT_ID}" reset "cleared chaos flags"
  log "reset complete for ${TENANT_ID}"
}

run_reap() {
  log "delegating to reaper v2"
  exec "${REPO_DIR}/demo-platform/reaper/reaper.sh"
}

main() {
  [ -n "${OP}" ] || die "OP is required (deploy|teardown|inject|reset|reap)"
  command -v aws >/dev/null || die "aws CLI not found in image"
  command -v jq  >/dev/null || die "jq not found in image"

  validate_tenant_branch

  # Shared naming + control-table helpers (from the image's bundled tree).
  # shellcheck source=/dev/null
  source "${REPO_DIR}/scripts/lib/tenant-common.sh"
  # shellcheck source=/dev/null
  source "${REPO_DIR}/demo-platform/lib/control-common.sh"

  # kubectl/helm auth: in-cluster use the pod ServiceAccount + RBAC (auth'ing as
  # the IRSA IAM role would require an aws-auth mapping this cluster lacks); only
  # write a kubeconfig when running standalone.
  if [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
    aws eks update-kubeconfig --name "${EKS_CLUSTER}" --region "${AWS_REGION}" >/dev/null 2>&1 || true
  fi

  case "${OP}" in
    deploy)   run_deploy ;;
    teardown) run_teardown ;;
    inject)   run_inject ;;
    reset)    run_reset ;;
    reap)     run_reap ;;
    *)        die "unknown OP '${OP}' (deploy|teardown|inject|reset|reap)" ;;
  esac
}

main "$@"
