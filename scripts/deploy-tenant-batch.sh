#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# OtterWorks - Batch Tenant Deploy (one persistent tenant per person)
#
# Deploys one tenant per name in a roster file by calling deploy-tenant.sh with
# a "firstname-lastname" id, so each person gets a standing environment at
# namespace otterworks-<firstname-lastname> and database
# otterworks_<firstname_lastname>.
#
# Tenants are PERSISTENT by default (--ttl none): no expiry is written and the
# namespace is labelled demo/persistent=true, which every reaper path skips.
# They are removed only by scripts/teardown-tenant.sh.
#
# Persistent is not the same as awake. A standing tenant still scales to zero
# after an hour of no ingress traffic, and nothing here wakes it again: these
# tenants have no control-table item, so the dashboard's check-out cannot reach
# them and the URL serves 503 until somebody runs scripts/tenant-scale.sh <id>
# up. Pass --always-on to exempt the roster from suspension, which is what makes
# every URL answer cold, at the cost of holding the whole fleet's compute and
# pod IPs.
#
# Resumable: a tenant whose deploy previously ran to completion is skipped unless
# --redeploy is passed, while one left half-built by an aborted run is retried, so
# a partial run can simply be re-run.
#
# Usage:
#   ./scripts/deploy-tenant-batch.sh [options] [NAME ...]
#
#   NAME ...            deploy only these people (default: the whole roster)
#   --roster FILE       roster file (default: scripts/tenant-roster.txt)
#   --ttl VALUE         lifetime passed to deploy-tenant.sh (default: none)
#   --concurrency N     tenants to deploy in parallel (default: 4)
#   --redeploy          also redeploy tenants that already deployed successfully
#   --dry-run           print the resolved ids and commands; touch nothing
#   --always-on         never scale these tenants to zero when idle
#   --no-preflight      deploy even if the cluster cannot hold the roster
#   --skip-db           no per-tenant Postgres database (the roster shares one)
#   --log-dir DIR       per-tenant logs (default: /tmp/otterworks-batch-<epoch>)
#   --tier A|B | --profile core|full | --host-suffix D | --image-tag T
#                       passed through to deploy-tenant.sh
#
# Required env: AWS creds (exported), DB_PASSWORD. Export a stable JWT_SECRET /
#   SECRET_KEY_BASE so a later redeploy does not invalidate issued sessions.
# ------------------------------------------------------------------------------
# No -e: one person's failed deploy must not abandon the rest of the roster.
set -uo pipefail

# `wait -n` (4.3) and "${ARRAY[@]+...}" on an empty array under set -u (4.4) are
# both used below, and macOS still ships bash 3.2 as /bin/bash. Left to itself
# that is a syntax error or an unbound-variable abort partway through an operator
# command, neither of which names the cause.
if [ "${BASH_VERSINFO[0]:-0}" -lt 4 ] || { [ "${BASH_VERSINFO[0]}" -eq 4 ] && [ "${BASH_VERSINFO[1]}" -lt 4 ]; }; then
  echo "ERROR: bash >= 4.4 required (this is ${BASH_VERSION}). On macOS: brew install bash, then run it with that bash." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Same name deploy-tenant.sh uses, for the same reason: lib/tenant-common.sh
# resolves the Terraform directory from it.
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=lib/tenant-common.sh
source "${SCRIPT_DIR}/lib/tenant-common.sh"

ROSTER="${SCRIPT_DIR}/tenant-roster.txt"
TTL="none"
CONCURRENCY=4
REDEPLOY=false
DRY_RUN=false
PREFLIGHT=true
ALWAYS_ON=false
LOG_DIR=""
# Same default as deploy-tenant.sh, from the same place: sizing the roster as
# `full` while the children deploy `core` would refuse rosters that do fit.
PROFILE="${TENANT_PROFILE:-full}"
NAMES=()
PASSTHROUGH=()

# Under set -u a value-less "--profile" would abort on `$2: unbound variable`
# instead of saying what is wrong.
needs_value() { if [ "$#" -lt 2 ] || [ -z "$2" ]; then err "$1 needs a value"; exit 1; fi; }

while [ $# -gt 0 ]; do
  case "$1" in
    --roster)      needs_value "$@"; ROSTER="$2"; shift 2 ;;
    --ttl)         needs_value "$@"; TTL="$2"; shift 2 ;;
    --concurrency) needs_value "$@"; CONCURRENCY="$2"; shift 2 ;;
    --log-dir)     needs_value "$@"; LOG_DIR="$2"; shift 2 ;;
    --redeploy)    REDEPLOY=true; shift ;;
    --dry-run)     DRY_RUN=true; shift ;;
    --always-on)   ALWAYS_ON=true; PASSTHROUGH+=("$1"); shift ;;
    --no-preflight) PREFLIGHT=false; shift ;;
    --tier|--profile|--host-suffix|--image-tag)
                   needs_value "$@"
                   [ "$1" = "--profile" ] && PROFILE="$2"
                   PASSTHROUGH+=("$1" "$2"); shift 2 ;;
    --skip-db)     PASSTHROUGH+=("$1"); shift ;;
    # Through the last line of the header block, which the comments above have
    # grown past twice now.
    -h|--help)     sed -n '2,/^# ---/p' "$0"; exit 0 ;;
    -*)            err "Unknown flag: $1"; exit 1 ;;
    *)             NAMES+=("$1"); shift ;;
  esac
done

[[ "${CONCURRENCY}" =~ ^[1-9][0-9]*$ ]] || { err "--concurrency must be a positive integer"; exit 1; }
# Checked here rather than left to the children: the sizing below reads anything
# that is not 'core' as 'full', so a typo would size the roster wrong and then
# fail 95 deploys one at a time on profile_services' error.
case "${PROFILE}" in
  core|full) ;;
  *) err "profile must be core or full (got '${PROFILE}')"; exit 1 ;;
esac

# A TTL other than "none" is not simply a shorter life: it is an unprotected one.
# The reaper identifies an orphan as a tenant namespace or database with no
# TENANT# control-table item, which only the dashboard's check-out writes, so
# every tenant this script deploys has that shape -- and demo/persistent=true, set
# only for a persistent tenant, is the single thing that makes the sweeps skip it.
# So the roster of a `--ttl 8h` batch is deleted by the next armed orphan sweep,
# database and S3 prefix included, long before the 8 hours are up. Not refused:
# the sweeps are off by default and a short-lived roster is a reasonable thing to
# ask for. But it should not be a surprise.
case "${TTL}" in
  none|never|infinite|persistent) ;;
  *)
    warn "--ttl ${TTL}: these tenants get an expiry but NOT demo/persistent=true, and a"
    warn "  script-deployed tenant has no control-table item, so an armed orphan sweep"
    warn "  (CONFIG#reaper sweep_orphans=true) treats the whole roster as junk and deletes it"
    warn "  -- namespaces, databases and S3 prefixes -- before the TTL expires."
    warn "  Use --ttl none for a standing roster, or keep the orphan sweeps disabled." ;;
esac

# A person's name in ASCII. Accents are transliterated rather than dashed out, so
# "João Esteves" is joao-esteves and not jo--o-esteves (sanitize_id replaces each
# byte of a multi-byte character).
#
# LC_ALL is pinned because //TRANSLIT is locale-dependent: glibc folds an accented
# letter to its base letter only under a UTF-8 locale, and emits '?' under C or
# POSIX. Unpinned, the same roster derives joao-esteves on one box and jo-o-esteves
# on another -- and these tenants are persistent, so the wrong one is a second
# standing namespace, database and S3 prefix that no reaper ever reclaims.
#
# A locale that does not exist is not an error either -- setlocale falls back to C
# and iconv still exits 0, having written '?' -- so the ambient locale is tried
# second (macOS has no C.UTF-8 but transliterates under en_US.UTF-8). Whatever
# comes back is the caller's to check: it rejects a '?', and equally the raw name
# returned when both attempts failed outright, which is what an iconv with no
# //TRANSLIT support at all (musl's) does.
tenant_ascii_from_name() {
  local ascii
  ascii="$(printf '%s' "$1" | LC_ALL=C.UTF-8 iconv -f UTF-8 -t ASCII//TRANSLIT 2>/dev/null)" || ascii=""
  case "${ascii}" in
    ""|*\?*)
      local ambient
      ambient="$(printf '%s' "$1" | iconv -f UTF-8 -t ASCII//TRANSLIT 2>/dev/null)" || ambient=""
      case "${ambient}" in
        ""|*\?*) [ -n "${ascii}" ] || ascii="${ambient:-$1}" ;;
        *) ascii="${ambient}" ;;
      esac ;;
  esac
  printf '%s' "${ascii}"
}

# //TRANSLIT can also spell an accent out as a quote or caret ("o -> o umlaut),
# hence the punctuation strip before the remaining runs of non-alphanumerics
# collapse to single dashes.
tenant_id_from_ascii() {
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E "s/[\"'\`^~]//g; s/[^a-z0-9]+/-/g; s/^-+//; s/-+$//"
}

# ---------- Build the roster ----------
# Checked here rather than with the rest of the preflight below: ids are derived
# next, and --dry-run (whose whole job is showing them) exits before preflight.
require_bins iconv

FROM="the command line"
if [ "${#NAMES[@]}" -eq 0 ]; then
  FROM="${ROSTER}"
  [ -f "${ROSTER}" ] || { err "Roster file not found: ${ROSTER}"; exit 1; }
  while IFS= read -r line; do
    line="${line%$'\r'}"                       # tolerate CRLF rosters
    line="$(printf '%s' "${line}" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
    case "${line}" in ""|\#*) continue ;; esac
    NAMES+=("${line}")
  done < "${ROSTER}"
fi
[ "${#NAMES[@]}" -gt 0 ] || { err "No names to deploy."; exit 1; }

IDS=()
declare -A NAME_OF_ID=()
INVALID=0
for name in "${NAMES[@]}"; do
  ascii="$(tenant_ascii_from_name "${name}")"
  # Two ways transliteration fails, and both have to be refused rather than
  # slugged: a '?' where glibc could not fold the letter, and a byte that is still
  # not ASCII, which is the untouched name coming back from an iconv that does not
  # implement //TRANSLIT. The second is the quieter one -- no '?' to spot, and
  # sanitize_id would dash out each byte of the character into a plausible-looking
  # id -- and both would give this person a second permanent environment under a
  # name nobody recognises.
  if [ "${ascii}" != "${ascii#*\?}" ] || [ -n "$(printf '%s' "${ascii}" | LC_ALL=C tr -d '[:print:]')" ]; then
    err "'${name}' did not transliterate to ASCII (got '${ascii}'): iconv here cannot fold it,"
    err "  so the id would not match the one another operator derives. Install a C.UTF-8 locale"
    err "  (or a GNU iconv), or spell the name in ASCII in the roster."
    INVALID=1; continue
  fi
  id="$(tenant_id_from_ascii "${ascii}")"
  if [ -z "${id}" ]; then
    err "Cannot derive a tenant id from '${name}'"; INVALID=1; continue
  fi
  # otterworks-<id> is a namespace, i.e. one RFC-1123 label (63 chars max).
  if [ "${#id}" -gt 52 ]; then
    err "Tenant id '${id}' is too long for namespace $(tenant_namespace "${id}") (max 63 chars)"
    INVALID=1; continue
  fi
  if [ -n "${NAME_OF_ID[${id}]:-}" ]; then
    err "'${name}' and '${NAME_OF_ID[${id}]}' both map to tenant id '${id}'; disambiguate them in the roster"
    INVALID=1; continue
  fi
  NAME_OF_ID["${id}"]="${name}"
  IDS+=("${id}")
done
[ "${INVALID}" -eq 0 ] || { err "Roster has errors (above); nothing deployed."; exit 1; }

log "${#IDS[@]} tenant(s) from ${FROM}:"
for id in "${IDS[@]}"; do printf '  %-28s <- %s\n' "$(tenant_namespace "${id}")" "${NAME_OF_ID[${id}]}"; done

# Measured footprint of one tenant, from demo-platform/docs/cost-and-scale.md.
case "${PROFILE}" in
  core) PODS_EACH=7;  MILLICPU_EACH=500 ;;
  *)    PODS_EACH=15; MILLICPU_EACH=1500 ;;
esac
PEAK_PODS=$(( ${#IDS[@]} * PODS_EACH ))
PEAK_CPU=$(( (${#IDS[@]} * MILLICPU_EACH + 999) / 1000 ))
if [ "${ALWAYS_ON}" = true ]; then
  log "Always-on: ${PEAK_PODS} pods / ~${PEAK_CPU} vCPU reserved permanently (${PROFILE} profile, no scale-to-zero)."
else
  log "Peak ${PEAK_PODS} pods / ~${PEAK_CPU} vCPU while the roster is awake (${PROFILE} profile); idle tenants scale to zero after an hour."
fi

# ---------- Capacity ----------
# Sized against the whole roster, not against how many people use it at once:
# a batch brings every tenant up together, and with --always-on they stay up.
# Pod IPs bind first -- the VPC CNI gives every pod a real subnet address, and a
# /24 node subnet holds ~250 of them.
#
# Defined up here so --dry-run can run it too, below.
capacity_preflight() {
  local want="$1" need_ips need_cpu n_subnets free_ips limit_cpu rc=0
  need_ips=$(( want * PODS_EACH ))
  need_cpu=$(( (want * MILLICPU_EACH + 999) / 1000 ))

  # Free addresses across every subnet Karpenter may launch into. Prefix
  # delegation books a /28 at a time, so this reads slightly pessimistic --
  # addresses reserved for a node's next pods count as allocated.
  #
  # A snapshot, and only that: another batch, a waking fleet or the next /28
  # reservation all move it between this read and the last pod scheduled. The
  # check is not trying to win that race -- it turns a roster that cannot
  # possibly fit into one message up front, instead of 95 deploys timing out on
  # Pending pods one at a time.
  #
  # The subnet count comes back with the sum because JMESPath sum([]) is 0, not
  # null: a cluster whose subnets carry no karpenter.sh/discovery tag would
  # otherwise measure "0 free" and be refused outright, blaming capacity for
  # what is a tagging or EKS_CLUSTER mismatch.
  read -r n_subnets free_ips <<< "$(aws ec2 describe-subnets --region "${AWS_REGION}" \
    --filters "Name=tag:karpenter.sh/discovery,Values=${EKS_CLUSTER}" \
    --query 'join(` `, [to_string(length(Subnets)), to_string(sum(Subnets[].AvailableIpAddressCount))])' \
    --output text 2>/dev/null | sed 's/\.[0-9]*//g')"
  if ! [[ "${n_subnets:-}" =~ ^[0-9]+$ ]]; then
    warn "Could not read subnet capacity from EC2; skipping the pod-IP check."
  elif [ "${n_subnets}" -eq 0 ]; then
    warn "No subnet is tagged karpenter.sh/discovery=${EKS_CLUSTER}; skipping the pod-IP check."
    warn "Nodes launch into subnets this cannot see, so the roster's ${need_ips} pod IPs are unverified."
  elif [[ "${free_ips}" =~ ^[0-9]+$ ]]; then
    log "Capacity: ${want} × ${PODS_EACH} pods = ${need_ips} pod IPs needed, ${free_ips} free in the node subnets."
    if [ "${free_ips}" -lt "${need_ips}" ]; then
      err "Not enough pod IPs for ${want} ${PROFILE} tenants (need ${need_ips}, have ${free_ips})."
      err "Pods would sit Pending and the deploys would time out one by one."
      err "Widen the node subnets first: apply aws_subnet.pods in platform/terraform (a /20 per AZ),"
      err "or deploy fewer people at a time. --no-preflight overrides this check."
      rc=1
    fi
  else
    warn "Could not read subnet capacity from EC2; skipping the pod-IP check."
  fi

  # Advisory: the NodePool ceiling counts node capacity, not requests, so it is
  # not a like-for-like comparison -- but being under it already means the
  # roster cannot fit.
  limit_cpu="$(kubectl get nodepool tenants -o jsonpath='{.spec.limits.cpu}' 2>/dev/null)"
  if [[ "${limit_cpu}" =~ ^[0-9]+$ ]] && [ "${limit_cpu}" -lt "${need_cpu}" ]; then
    warn "Karpenter NodePool 'tenants' is capped at ${limit_cpu} vCPU; ${want} ${PROFILE} tenants request ~${need_cpu}. Raise spec.limits.cpu."
  fi
  return "${rc}"
}

DEPLOY_ARGS=(--ttl "${TTL}" "${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}")
if [ "${DRY_RUN}" = true ]; then
  echo ""
  log "--dry-run: would run, ${CONCURRENCY} at a time:"
  for id in "${IDS[@]}"; do echo "  ${SCRIPT_DIR}/deploy-tenant.sh ${id} ${DEPLOY_ARGS[*]}"; done
  # "Will this roster fit" is most of what a dry run is asked, and the real run
  # refuses on the answer -- finding that out here, before committing to 95
  # deploys, is the point of the mode. Advisory: nothing is being deployed to
  # refuse, and it sizes the whole roster rather than the queue, since which
  # tenants are already up is not read in this mode.
  if [ "${PREFLIGHT}" = true ] && command -v aws >/dev/null 2>&1; then
    echo ""
    capacity_preflight "${#IDS[@]}" || true
  fi
  exit 0
fi

# ---------- Preflight ----------
require_bins aws kubectl helm terraform jq
[ -n "${DB_PASSWORD:-}" ] || { err "DB_PASSWORD must be set (shared RDS master password)."; exit 1; }
# deploy-tenant.sh mints a random JWT_SECRET / SECRET_KEY_BASE when unset, which
# is per-invocation: a redeploy would then invalidate every session and token
# the tenant had issued. Fine for a first run, worth knowing before a redeploy.
[ -n "${JWT_SECRET:-}" ] || warn "JWT_SECRET unset: each tenant gets a random one, and a redeploy will rotate it."
[ -n "${SECRET_KEY_BASE:-}" ] || warn "SECRET_KEY_BASE unset: each tenant gets a random one, and a redeploy will rotate it."
if [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
  aws eks update-kubeconfig --name "${EKS_CLUSTER}" --region "${AWS_REGION}" --alias "${EKS_CLUSTER}" >/dev/null \
    || { err "Could not reach EKS cluster ${EKS_CLUSTER} in ${AWS_REGION}."; exit 1; }
  # Written once here, for everyone. Each deploy-tenant.sh would otherwise write
  # it again, and several of them at once is a read-modify-write race on a single
  # file: a child can read a half-written kubeconfig and fail on the cluster
  # connection rather than on anything to do with its tenant.
  export OTTERWORKS_KUBECONFIG_READY=1
fi

# Same reasoning for the other shared file the children touch: load_infra_outputs
# inits infrastructure/terraform, and N of those into one .terraform/ directory
# corrupt each other. A child whose init lost the race reads empty outputs and
# deploys a tenant with no RDS/S3/DynamoDB wiring at all.
if terraform -chdir="${REPO_ROOT}/infrastructure/terraform" init -input=false >/dev/null 2>&1; then
  export OTTERWORKS_TF_INIT_READY=1
else
  warn "terraform init failed in infrastructure/terraform; each deploy will retry it on its own."
fi

# The images are the same for every tenant, so leaving latest_tag to the
# children asks ECR one question per service per tenant -- ~1200 for this
# roster. They are also load-bearing now: an empty answer is a service the child
# reports as not deployed, which withholds the completion marker, so a throttled
# lookup costs a whole tenant a re-run. Resolve each once here. It pins the
# roster to one set of images too, which a push landing mid-batch would
# otherwise split in half.
resolve_image_tags() {
  local svc tag
  while read -r svc; do
    [ -n "${svc}" ] || continue
    tag="$(aws ecr describe-images --repository-name "${ECR_PREFIX}${svc}" --region "${AWS_REGION}" \
             --query 'sort_by(imageDetails,&imagePushedAt)[-1].imageTags[0]' --output text 2>/dev/null)" || tag=""
    # A miss is left unset rather than exported: the child asks again and, if
    # ECR really has nothing, says so per tenant the way it did before.
    if [ -z "${tag}" ] || [ "${tag}" = "None" ]; then
      warn "no image in ECR for ${svc}; each deploy will resolve it on its own."
      continue
    fi
    export "OTTERWORKS_IMAGE_TAG_${svc//-/_}=${tag}"
  done < <(profile_services "${PROFILE}")
}

LOG_DIR="${LOG_DIR:-/tmp/otterworks-batch-$(date -u +%s)}"
mkdir -p "${LOG_DIR}/status"
log "Per-tenant logs: ${LOG_DIR}"


# ---------- Deploy ----------
# Status is written to a file per tenant rather than a shell variable: each
# deploy runs in a background subshell and cannot write back to this one.
deploy_one() {
  local id="$1" logfile="${LOG_DIR}/${id}.log"
  if "${SCRIPT_DIR}/deploy-tenant.sh" "${id}" "${DEPLOY_ARGS[@]}" >"${logfile}" 2>&1; then
    # deploy-tenant.sh collects per-service Helm failures instead of aborting, and
    # still exits 0; it withholds demo/deployed-at in that case, so the marker is
    # the only honest answer to "is this tenant complete", and the one a re-run
    # uses to decide what to retry.
    if tenant_deploy_finished "${id}"; then
      echo ok > "${LOG_DIR}/status/${id}"
      log "  [ok]   ${id}"
    else
      echo fail > "${LOG_DIR}/status/${id}"
      err "  [fail] ${id} — services missing, tenant incomplete; see ${logfile}"
      tail -3 "${logfile}" | sed 's/^/         /' >&2
    fi
  else
    echo fail > "${LOG_DIR}/status/${id}"
    err "  [fail] ${id} — see ${logfile}"
    tail -3 "${logfile}" | sed 's/^/         /' >&2
  fi
}

# A tenant counts as already deployed only if deploy-tenant.sh got all the way to
# the end for it (demo/deployed-at). Skipping on the namespace alone would strand
# exactly the people this script is meant to rescue: the namespace is created in
# the first seconds, so a deploy that died at the database, Helm or ingress step
# leaves one behind, and a re-run would report "skipped" over a half-built tenant.
tenant_deploy_finished() {
  [ -n "$(kubectl get ns "$(tenant_namespace "$1")" \
            -o jsonpath='{.metadata.annotations.demo/deployed-at}' 2>/dev/null)" ]
}

SKIPPED=()
RETRYING=()
QUEUE=()
for id in "${IDS[@]}"; do
  if [ "${REDEPLOY}" = false ] && kubectl get ns "$(tenant_namespace "${id}")" >/dev/null 2>&1; then
    if tenant_deploy_finished "${id}"; then
      SKIPPED+=("${id}")
      continue
    fi
    RETRYING+=("${id}")
  fi
  QUEUE+=("${id}")
done
[ "${#SKIPPED[@]}" -eq 0 ] || log "Skipping ${#SKIPPED[@]} deployed tenant(s) (pass --redeploy to redeploy them)."
[ "${#RETRYING[@]}" -eq 0 ] || warn "Retrying ${#RETRYING[@]} incomplete tenant(s) from an earlier run: ${RETRYING[*]}"

if [ "${#QUEUE[@]}" -gt 0 ]; then
  if [ "${PREFLIGHT}" = true ]; then
    capacity_preflight "${#QUEUE[@]}" || exit 1
  fi
  # After the partition, not before it: a re-run that finds every tenant already
  # deployed -- the ordinary end of the "re-run until the batch is clean" loop --
  # should not ask ECR thirteen questions in order to deploy nothing.
  resolve_image_tags
fi

log "Deploying ${#QUEUE[@]} tenant(s), ${CONCURRENCY} at a time..."
for id in "${QUEUE[@]+"${QUEUE[@]}"}"; do
  deploy_one "${id}" &
  # Counted from the job table rather than decremented on each `wait -n`: two
  # children finishing between iterations is one return and one decrement, so a
  # bookkeeping counter drifts below the requested concurrency and a 95-tenant
  # run finishes slower than it was asked to, with no sign of why.
  while [ "$(jobs -rp | wc -l)" -ge "${CONCURRENCY}" ]; do
    wait -n
  done
done
wait

# ---------- Summary ----------
OK=(); FAILED=()
for id in "${QUEUE[@]+"${QUEUE[@]}"}"; do
  if [ "$(cat "${LOG_DIR}/status/${id}" 2>/dev/null)" = "ok" ]; then OK+=("${id}"); else FAILED+=("${id}"); fi
done

echo ""
log "Batch complete: ${#OK[@]} deployed, ${#SKIPPED[@]} skipped, ${#FAILED[@]} failed."
if [ "${#FAILED[@]}" -gt 0 ]; then
  err "Failed: ${FAILED[*]}"
  err "Re-run the same command to retry only those (successful tenants are skipped)."
  exit 1
fi
case "${TTL}" in
  none|never|infinite|persistent)
    log "Tenants are persistent (ttl=${TTL}); remove one with ./scripts/teardown-tenant.sh <id>" ;;
  *)
    log "Tenants expire in ${TTL} and are then reaped; remove one early with ./scripts/teardown-tenant.sh <id>" ;;
esac
if [ "${ALWAYS_ON}" = true ]; then
  log "They are always-on: the idle scan will not scale them to zero."
else
  log "They scale to zero after an hour idle, and nothing wakes them again: a tenant"
  log "  deployed from here has no control-table item, so check-out cannot reach it and"
  log "  the URL serves 503 until './scripts/tenant-scale.sh <id> up'. Pass --always-on"
  log "  to keep them up."
fi
