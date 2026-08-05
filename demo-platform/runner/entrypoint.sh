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
#   1. checks out the requested OtterWorks git branch (TENANT_BRANCH),
#   2. transitions status in the control table (deploying -> active | error),
#   3. runs the requested op via the existing scripts,
#   4. records the resolved coordinates (url/api_url/db_name/namespace/expires)
#      and appends AUDIT events.
#
# Environment (control-plane metadata; NON-secret):
#   OP            deploy | teardown | inject | reset | seed | reap  (required)
#   TENANT_ID     attendee id (required for deploy/teardown/inject/reset/seed)
#   TIER          A | B                                            (default A)
#   TTL           e.g. 8h, 30m, 2d, or `never` for a perpetual tenant (default 8h)
#   REDEPLOY      true when deploying over a live tenant (CD)   (default unset)
#   IMAGE_TAG     optional pinned image tag
#   HOST_SUFFIX   ingress host suffix              (default demo.otterworks.app)
#   SCENARIO      bug-catalog scenario (for OP=inject)
#   SCALE         seed breadth multiplier (for OP=seed)          (default 1.0)
#   DEPARTMENTS   seed departments, or `all` (for OP=seed)       (default all)
#   SEED_FORCE    true to restart a seed that is still loading   (default false)
#   SEED_WAIT     true to block until the seed Job finishes      (default false)
#   SEED_TIMEOUT  seconds to wait when SEED_WAIT=true            (default 3600)
#   SEED_REPO_URL/SEED_REPO_REF  repo the seed Job clones the generator from.
#                 It clones ANONYMOUSLY, so this must be a public repo/ref
#                 (defaults in render-seed-job.sh), not REPO_HTTPS_URL.
#   TENANT_BRANCH git branch to check out (e.g. workshop-<id>)
#   CONTROL_TABLE DynamoDB control table         (default otterworks-demo-control)
#   AWS_REGION    (default us-east-1)   EKS_CLUSTER (default otterworks-dev)
#   REPO_DIR      checked-out repo path                   (default /workspace)
#   REPO_REMOTE   git remote name                         (default origin)
#   ACTOR         audit actor label                       (default runner)
#
# Secrets (from Kubernetes Secret refs in the Job spec — env only, NEVER argv):
#   DB_PASSWORD, JWT_SECRET, SECRET_KEY_BASE, DRIVE_EMAIL/DRIVE_PASSWORD (seed)
#
# This script never echoes secret values and never passes them on a command line;
# the underlying scripts read them straight from the environment.
# ------------------------------------------------------------------------------
set -euo pipefail

REPO_DIR="${REPO_DIR:-/workspace}"
REPO_REMOTE="${REPO_REMOTE:-origin}"
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

# --- git checkout of the requested branch (deploy uses the tenant's branch) ----
# Fetching a participant branch (workshop-<id>) needs git auth. If GITHUB_TOKEN
# (from a Secret) and REPO_HTTPS_URL are provided, we fetch over HTTPS via a
# credential helper that reads the token from the env — never on argv or in logs.
# Without them we fall back to the tree baked into the image (the golden app);
# code-level variants then rely on --image-tag rather than a branch checkout.
configure_git_auth() {
  git config --global --add safe.directory "${REPO_DIR}" >/dev/null 2>&1 || true
  [ -n "${GITHUB_TOKEN:-}" ] || return 0
  local url="${REPO_HTTPS_URL:-}"
  [ -n "${url}" ] || return 0
  local helper="/tmp/git-cred-helper.sh"
  # The helper echoes the token from the env at call time; the value is never
  # written to disk or passed on a command line.
  cat > "${helper}" <<'HELPER'
#!/bin/sh
echo "username=x-access-token"
echo "password=${GITHUB_TOKEN}"
HELPER
  chmod 700 "${helper}"
  git config --global credential.helper "${helper}" >/dev/null 2>&1 || true
  ( cd "${REPO_DIR}" && git remote set-url "${REPO_REMOTE}" "${url}" >/dev/null 2>&1 ) || true
}

checkout_branch() {
  [ -n "${TENANT_BRANCH:-}" ] || { log "no TENANT_BRANCH set; using image's bundled checkout"; return 0; }
  configure_git_auth
  log "checking out branch ${TENANT_BRANCH} in ${REPO_DIR}"
  ( cd "${REPO_DIR}" \
    && git fetch --prune "${REPO_REMOTE}" >/dev/null 2>&1 \
    && ( git checkout "${TENANT_BRANCH}" >/dev/null 2>&1 \
         || git checkout -b "${TENANT_BRANCH}" "${REPO_REMOTE}/${TENANT_BRANCH}" >/dev/null 2>&1 ) \
    && git reset --hard "${REPO_REMOTE}/${TENANT_BRANCH}" >/dev/null 2>&1 ) \
    && { log "checked out ${TENANT_BRANCH}"; return 0; }
  err "branch checkout of ${TENANT_BRANCH} failed; continuing with the image's bundled tree (set GITHUB_TOKEN + REPO_HTTPS_URL to enable participant-branch checkouts)"
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

# Seed the RetailCo enterprise drive into a live tenant by stamping
# testdata/generated/retail-drive/seed-loader.job.tpl.yaml into the tenant's own
# namespace (the generator writes through that tenant's api-gateway, so it has
# to run there rather than in otterworks-platform).
run_seed() {
  [ -n "${TENANT_ID:-}" ] || die "OP=seed requires TENANT_ID"
  local sid ns scale departments job manifest
  sid="$(sanitize_id "${TENANT_ID}")"
  ns="$(tenant_namespace "${TENANT_ID}")"
  scale="${SCALE:-1.0}"
  departments="${DEPARTMENTS:-all}"
  job="retail-drive-seed-loader"

  # The same ceiling the dashboard route applies, repeated because a runner Job
  # can be created by hand: above it the corpus outlives the tenant's TTL and
  # fills a bucket shared with every other tenant. The renderer stays uncapped --
  # applying it needs cluster access, which is licence enough.
  awk -v s="${scale}" 'BEGIN { exit !(s > 0 && s <= 2) }' 2>/dev/null ||
    die "invalid SCALE '${scale}' (0 < scale <= 2)"

  # Unset-only default, so an explicitly empty SEED_TIMEOUT is rejected here
  # rather than becoming a bash arithmetic error in wait_for_seed later.
  case "${SEED_TIMEOUT-3600}" in
    ''|*[!0-9]*) die "invalid SEED_TIMEOUT '${SEED_TIMEOUT}' (seconds)" ;;
  esac

  kubectl get namespace "${ns}" >/dev/null 2>&1 ||
    die "namespace ${ns} does not exist -- deploy tenant ${TENANT_ID} before seeding it"

  # Decide whether this seed may proceed before changing anything, so that a
  # refused seed leaves the tenant exactly as it found it.
  #
  # A loader that is still uploading is not collateral: replacing it discards
  # however long it has been running, so that takes an explicit SEED_FORCE. An
  # unreadable Job is treated the same way -- "the API server did not answer"
  # must not be mistaken for "nothing is running" when the next step deletes it.
  if [ "${SEED_FORCE:-false}" != "true" ]; then
    case "$(seed_job_state "${ns}" "${job}")" in
      ABSENT|*Complete*|*Failed*) ;;
      UNREADABLE)
        die "cannot tell whether a seed is already loading ${ns} (job/${job} is unreadable) -- retry, or re-run with SEED_FORCE=true" ;;
      *)
        die "a seed is already loading ${ns} (job/${job}) -- wait for it, or re-run with SEED_FORCE=true to restart it from scratch" ;;
    esac
  fi

  # Render before anything is written: the renderer validates SCALE, DEPARTMENTS
  # and the repo overrides, and a rejected input must not leave behind a Secret
  # that replaced the operator's one.
  manifest="$(TENANT_NAMESPACE="${ns}" \
              REPO_URL="${SEED_REPO_URL:-}" REPO_REF="${SEED_REPO_REF:-}" \
                "${REPO_DIR}/testdata/generated/retail-drive/render-seed-job.sh" \
                  "${sid}" "${scale}" "${departments}")" ||
    die "could not render the seed Job for ${ns}"

  # Read-only, before the delete: without credentials on the runner and without
  # a Secret already in the namespace there is no seed to be had, and finding
  # that out after the delete would have thrown away a running loader for a run
  # that never starts.
  [ -n "${DRIVE_EMAIL:-}" ] && [ -n "${DRIVE_PASSWORD:-}" ] ||
    kubectl -n "${ns}" get secret retail-drive-seed >/dev/null 2>&1 ||
    die "$(no_seed_secret_msg "${ns}")"

  # A Job's pod template is immutable, so a re-seed at a different scale cannot
  # be an `apply` over the previous run. Deleting first keeps re-seeding
  # idempotent -- which the generator itself is.
  log "removing any previous seed Job in ${ns}"
  if ! delete_loader_job "${ns}" "${job}"; then
    # Audited like the failures below it: the delete has already set a deletion
    # timestamp (and may have taken the pod), so the previous run is over even
    # though this one never started.
    [ "${SEED_FORCE:-false}" = "true" ] ||
      die_without_loader "could not remove the previous seed Job in ${ns} within 120s -- its pod may be stuck Terminating; re-run with SEED_FORCE=true"
    # The pod outlived the delete: a lost node or a finalizer, which is exactly
    # the case an operator would clear with `kubectl delete pod --force`. Doing
    # it here is the point of force -- without cluster access there is no other
    # way back, and the alternative is a tenant that can never be seeded again.
    # Before the second delete rather than instead of it, so the Job object is
    # really gone before its immutable replacement is applied.
    log "force: the previous loader pod is not terminating; removing it outright"
    kubectl -n "${ns}" delete pod -l "app.kubernetes.io/name=${job}" \
      --ignore-not-found --force --grace-period=0 >/dev/null 2>&1 || true
    delete_loader_job "${ns}" "${job}" ||
      die_without_loader "could not remove the previous seed Job in ${ns} even with SEED_FORCE=true -- it needs direct cluster access"
  fi

  # After the delete, so that a seed refused or aborted before this point has not
  # replaced an operator-created Secret (which, per the README, can invalidate a
  # drive account registered with a different password). Still before the apply,
  # because the loader pod reads the Secret at start-up.
  ensure_seed_secret "${ns}"

  log "seeding ${TENANT_ID} (${ns}) at scale ${scale}, departments ${departments}"
  printf '%s\n' "${manifest}" | kubectl apply -f - >/dev/null ||
    die_without_loader "could not create job/${job} in ${ns}; the previous loader is gone"

  ctl_audit "${TENANT_ID}" seed "ns=${ns} scale=${scale} departments=${departments}"
  log "seed Job created; follow it with: kubectl -n ${ns} logs -f job/${job}"

  [ "${SEED_WAIT:-false}" = "true" ] || return 0
  wait_for_seed "${ns}" "${job}"
}

# The loader reads DRIVE_EMAIL / DRIVE_PASSWORD from a Secret in the tenant's
# namespace. When the runner was given the credentials we materialise it --
# overwriting an operator-created Secret, so the platform's drive account wins
# over a hand-made one -- and when it was not, that hand-made Secret must
# already be in the namespace.
#
# The values go to kubectl on STDIN, never on an argv (`kubectl create secret
# --from-literal` would put them in /proc/<pid>/cmdline) and never into a file.
no_seed_secret_msg() {
  printf '%s' "secret retail-drive-seed is missing in $1 and DRIVE_EMAIL/DRIVE_PASSWORD were not provided -- create it with: kubectl -n $1 create secret generic retail-drive-seed --from-literal=DRIVE_EMAIL='<email>' --from-literal=DRIVE_PASSWORD='<password>'"
}

# For every failure from the delete of the old loader onwards: the namespace is
# left with no loader, or with one that is on its way out, and the runner pod's
# log is the only other trace of it -- which ages out with the runner Job.
die_without_loader() {
  ctl_audit "${TENANT_ID}" seed_fail "$1"
  die "$1"
}

# Foreground cascade so the old loader pod is really gone (not merely orphaned
# to the GC) before its replacement is admitted against the tenant's
# ResourceQuota. Bounded, because that wait is on a pod which may never
# terminate, and an unbounded one keeps this runner Job active forever -- which
# the dashboard reads as "a seed is already running" for every later attempt.
delete_loader_job() {
  kubectl -n "$1" delete job "$2" \
    --ignore-not-found --cascade=foreground --wait=true --timeout=120s >/dev/null
}

ensure_seed_secret() {
  local ns="$1"
  if [ -n "${DRIVE_EMAIL:-}" ] && [ -n "${DRIVE_PASSWORD:-}" ]; then
    log "upserting the retail-drive-seed Secret in ${ns}"
    # `if`, not `|| die`: the heredoc has to stay attached to the kubectl call,
    # and an unguarded failure here would end the runner with kubectl's stderr
    # and no indication of which step it came from.
    if kubectl apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: retail-drive-seed
  namespace: ${ns}
type: Opaque
data:
  DRIVE_EMAIL: $(printf '%s' "${DRIVE_EMAIL}" | base64 | tr -d '\n')
  DRIVE_PASSWORD: $(printf '%s' "${DRIVE_PASSWORD}" | base64 | tr -d '\n')
EOF
    then
      return 0
    fi
    die_without_loader "could not write the retail-drive-seed Secret in ${ns}"
  fi

  # Re-checked rather than assumed from the pre-flight above, because this is
  # also the guarantee the apply that follows depends on.
  kubectl -n "${ns}" get secret retail-drive-seed >/dev/null 2>&1 ||
    die_without_loader "$(no_seed_secret_msg "${ns}")"
}

# Print the loader Job's true conditions (empty while it is still running), or
# one of two sentinels: ABSENT for a Job the API server says is not there, and
# UNREADABLE for a read that failed for any other reason -- throttling, a token
# refresh, a transient 500. Callers must keep those apart: they act on "nothing
# is running" by deleting the Job.
#
# stderr is captured separately, never folded into the value: kubectl warnings
# on the success path would otherwise be substring-matched alongside the
# conditions, and a stray "Failed"/"Complete" in a banner would decide whether a
# running loader gets deleted.
seed_job_state() {
  local out err
  err="${TMPDIR:-/tmp}/seed-job-state.$$"
  if out="$(kubectl -n "$1" get job "$2" \
              -o jsonpath='{.status.conditions[?(@.status=="True")].type}' 2>"${err}")"; then
    rm -f "${err}"
    printf '%s' "${out}"
    return 0
  fi
  case "$(cat "${err}" 2>/dev/null)" in
    *NotFound*|*not\ found*) printf 'ABSENT' ;;
    *) printf 'UNREADABLE' ;;
  esac
  rm -f "${err}"
}

# Poll rather than `kubectl wait --for=condition=complete`, which sits out the
# whole timeout on a Job that has already failed.
wait_for_seed() {
  local ns="$1" job="$2" deadline
  deadline=$(( $(date -u +%s) + ${SEED_TIMEOUT:-3600} ))
  log "waiting for ${job} in ${ns} (timeout ${SEED_TIMEOUT:-3600}s)"
  while [ "$(date -u +%s)" -lt "${deadline}" ]; do
    # A Job that has gone missing is never going to complete, so say so rather
    # than polling it until the timeout. A read that merely failed is retried.
    case "$(seed_job_state "${ns}" "${job}")" in
      *Complete*)  log "seed complete for ${TENANT_ID}"; return 0 ;;
      *Failed*)    ctl_audit "${TENANT_ID}" seed_fail "loader failed in ${ns}"; die "seed Job failed in ${ns} -- kubectl -n ${ns} logs job/${job}" ;;
      ABSENT)      die "job/${job} is gone from ${ns} -- it was deleted while the seed was running" ;;
      UNREADABLE)  log "warning: could not read job/${job} in ${ns}; retrying" ;;
    esac
    sleep 15
  done
  die "seed Job did not finish within ${SEED_TIMEOUT:-3600}s -- it is still running: kubectl -n ${ns} logs -f job/${job}"
}

run_reap() {
  log "delegating to reaper v2"
  exec "${REPO_DIR}/demo-platform/reaper/reaper.sh"
}

main() {
  [ -n "${OP}" ] || die "OP is required (deploy|teardown|inject|reset|seed|reap)"
  command -v aws >/dev/null || die "aws CLI not found in image"
  command -v jq  >/dev/null || die "jq not found in image"

  checkout_branch

  # Shared naming + control-table helpers (from the checked-out repo).
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
    seed)     run_seed ;;
    reap)     run_reap ;;
    *)        die "unknown OP '${OP}' (deploy|teardown|inject|reset|seed|reap)" ;;
  esac
}

main "$@"
