#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# OtterWorks Demo Platform — Reaper v2 (schedule-driven, GCs EVERYTHING)
#
# SUPERSEDES the basic namespace-only TTL reaper embedded in
# scripts/tenant-platform-baseline.sh (which deletes tenant namespaces but
# leaves orphan RDS databases, S3 objects, DynamoDB items and IRSA trust behind).
# Once this reaper is deployed via demo-platform/helm, the baseline reaper is
# redundant and should be considered replaced.
#
# Runs inside the demo-runner image (OP=reap) on the schedule stored in the
# control table (CONFIG#reaper). Each run:
#   1. read CONFIG#reaper (enabled / grace_seconds / sweep_orphans). If disabled,
#      exit.
#   2. scan TENANT#*/META; for every tenant with expires_at + grace_seconds < now
#      run a full, idempotent teardown of ALL its resources:
#        (a) namespace otterworks-<id>          -> via scripts/teardown-tenant.sh
#        (b) RDS database otterworks_<id>        -> via scripts/teardown-tenant.sh
#                                                   (reuses drop_tenant_db)
#        (c) tenant S3 object prefix in shared buckets
#        (d) tenant DynamoDB items in shared app tables
#        (e) legacy exact-match IRSA trust       -> via scripts/teardown-tenant.sh
#                                                   (PRESERVES the shared
#                                                    StringLike otterworks-* rule)
#        (f) tenant Route53 records (best effort; external-dns also GCs these)
#        (g) delete TENANT#<id> + LOCK#<id> control items and append an AUDIT reap
#   3. if sweep_orphans: independently list live namespaces / DBs / S3 prefixes /
#      DynamoDB partitions and GC any with NO matching TENANT# control item.
#   4. if sweep_infra: sweep the AWS resources Kubernetes creates implicitly and
#      Terraform therefore does not track (load balancers, target groups,
#      unattached EBS, idle EIPs, stale Route53 records). See infra-sweep.sh.
#
# Everything here is idempotent and retry-safe: re-running against an
# already-clean tenant is a series of no-ops. Secrets are read from the env only
# (DB_PASSWORD) and never appear on an argv or in logs.
# ------------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export REPO_ROOT

# Shared tenant naming / infra-output loading / drop_tenant_db / apply secret.
# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/lib/tenant-common.sh"
# shellcheck source=/dev/null
source "${REPO_ROOT}/demo-platform/lib/control-common.sh"
# Infrastructure-layer orphan GC (load balancers, target groups, EBS, EIP, DNS).
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/infra-sweep.sh"
# Scale-to-zero for tenants taking no ingress traffic.
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/idle-suspend.sh"

CONTROL_TABLE="${CONTROL_TABLE:-otterworks-demo-control}"
AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER="${EKS_CLUSTER:-otterworks-dev}"
HOST_SUFFIX="${HOST_SUFFIX:-demo.otterworks.app}"
SHARED_S3_PREFIX="${SHARED_S3_PREFIX:-otterworks-}"
SHARED_DDB_PREFIX="${SHARED_DDB_PREFIX:-otterworks-}"
# Convention for a tenant's object prefix inside the shared S3 buckets. Only this
# prefix namespace is swept for orphans, so shared/non-tenant keys are never
# touched. The per-tenant reap also clears the bare "<id>/" prefix for safety.
S3_TENANT_ROOT="${S3_TENANT_ROOT:-tenants/}"
# Reaper is OFF unless CONFIG#reaper says enabled=true (fail-safe: never mass
# delete on a misconfigured/absent config). Override the fallback with env.
REAPER_ENABLED_DEFAULT="${REAPER_ENABLED_DEFAULT:-false}"

require_bins aws kubectl jq

# In-cluster (reaper CronJob) use the pod ServiceAccount + RBAC; only build a
# kubeconfig when running standalone (auth'ing as the IRSA role would need an
# aws-auth mapping the cluster doesn't have).
if [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
  aws eks update-kubeconfig --name "${EKS_CLUSTER}" --region "${AWS_REGION}" >/dev/null 2>&1 || true
fi

# ------------------------------------------------------------------------------
# Per-resource GC helpers (all idempotent / best-effort)
# ------------------------------------------------------------------------------

# (c) Remove the tenant's object prefix from every shared bucket.
gc_s3() {
  local sid="$1" bucket prefix
  for bucket in $(list_shared_buckets); do
    for prefix in "${S3_TENANT_ROOT}${sid}/" "${sid}/"; do
      aws s3 rm "s3://${bucket}/${prefix}" --recursive >/dev/null 2>&1 || true
    done
  done
}

# (d) Delete the tenant's items from every shared DynamoDB app table. A tenant
# "owns" items whose hash key is exactly "<sid>" or begins with "<sid>#"
# (the tenant-partition convention). Single-value keys that are not partitioned
# this way (e.g. plain user ids) are left alone. Pagination is ignored (demo
# scale is small-N); add LastEvaluatedKey handling if tables grow large.
gc_ddb_partition() {
  local table="$1" sid="$2" hk rk names proj items key
  hk="$(ddb_hash_key "${table}")"; [ -n "${hk}" ] || return 0
  rk="$(ddb_range_key "${table}")"
  if [ -n "${rk}" ]; then
    names="$(jq -n --arg hk "${hk}" --arg rk "${rk}" '{"#hk":$hk,"#rk":$rk}')"; proj="#hk,#rk"
  else
    names="$(jq -n --arg hk "${hk}" '{"#hk":$hk}')"; proj="#hk"
  fi
  items="$(aws dynamodb scan --table-name "${table}" --region "${AWS_REGION}" \
      --filter-expression "#hk = :id OR begins_with(#hk, :idp)" \
      --expression-attribute-names "${names}" \
      --expression-attribute-values \
        "$(jq -n --arg id "${sid}" --arg idp "${sid}#" '{":id":{S:$id},":idp":{S:$idp}}')" \
      --projection-expression "${proj}" --output json 2>/dev/null | jq -c '.Items[]?' 2>/dev/null)"
  [ -n "${items}" ] || return 0
  while IFS= read -r key; do
    [ -n "${key}" ] || continue
    # The projected item IS the key map (hash [+range]); use it verbatim.
    aws dynamodb delete-item --table-name "${table}" --region "${AWS_REGION}" \
      --key "${key}" >/dev/null 2>&1 || true
  done <<EOF
${items}
EOF
}

gc_ddb() {
  local sid="$1" table
  for table in $(list_shared_ddb_tables); do
    [ "${table}" = "${CONTROL_TABLE}" ] && continue
    gc_ddb_partition "${table}" "${sid}"
  done
}

# (f) Delete the tenant's Route53 records if a matching hosted zone exists.
# external-dns already removes ingress-managed records when the namespace is
# deleted; this is belt-and-suspenders for records it did not own.
gc_route53() {
  local sid="$1" domain="${HOST_SUFFIX}" zone_id host
  zone_id="$(aws route53 list-hosted-zones-by-name --dns-name "${domain}" --output json 2>/dev/null \
    | jq -r --arg d "${domain}." '.HostedZones[]? | select(($d|endswith(.Name))) | .Id' \
    | head -1 | sed 's#/hostedzone/##')"
  [ -n "${zone_id}" ] || return 0
  for host in "t-${sid}.${domain}" "api-t-${sid}.${domain}"; do
    delete_r53_record "${zone_id}" "${host}"
  done
}

delete_r53_record() {
  local zone="$1" name="$2" rrs rec batch
  rrs="$(aws route53 list-resource-record-sets --hosted-zone-id "${zone}" \
      --query "ResourceRecordSets[?Name=='${name}.']" --output json 2>/dev/null || echo '[]')"
  [ "$(echo "${rrs}" | jq 'length' 2>/dev/null || echo 0)" -gt 0 ] || return 0
  while IFS= read -r rec; do
    [ -n "${rec}" ] || continue
    batch="$(jq -n --argjson r "${rec}" '{Changes:[{Action:"DELETE",ResourceRecordSet:$r}]}')"
    aws route53 change-resource-record-sets --hosted-zone-id "${zone}" \
      --change-batch "${batch}" >/dev/null 2>&1 || true
  done <<EOF
$(echo "${rrs}" | jq -c '.[]')
EOF
}

# Why the last tenant_is_persistent said yes: the label, or a label it could not
# read. Both keep the tenant, but only one of them is a decision somebody made.
PERSISTENT_REASON=""

# A tenant deployed with `deploy-tenant.sh <id> --ttl none` is long-lived (a
# standing per-person environment, not a workshop seat) and has no expiry to
# compare against. It also has no control-table item unless the dashboard
# created one, so without this it would read as an orphan and be swept.
# Checked against the live namespace so the guard holds for every GC path.
tenant_is_persistent() {
  local ns out err errfile rc
  ns="$(tenant_namespace "$1")"
  PERSISTENT_REASON="demo/persistent=true"
  # The two streams are kept apart: the label decides whether the tenant is
  # deleted, and kubectl writes to stderr on a *successful* call often enough
  # (API-server Warning headers, exec-plugin deprecation notices) that folding
  # them together would make a protected tenant compare unequal to "true".
  errfile="$(mktemp)"
  out="$(kubectl get ns "${ns}" -o jsonpath='{.metadata.labels.demo/persistent}' 2>"${errfile}")"; rc=$?
  err="$(cat "${errfile}")"; rm -f "${errfile}"
  if [ "${rc}" -eq 0 ]; then
    [ "${out}" = "true" ]
    return
  fi
  # A namespace that is genuinely gone is the orphan the sweeps exist for.
  case "${err}" in *NotFound*|*"not found"*) return 1 ;; esac
  # Every other failure (API unreachable, throttled by ~100 sequential lookups,
  # expired credentials, missing RBAC) means "unknown", not "not persistent".
  # sweep_orphan_s3 and sweep_orphan_ddb delete data on this answer alone, so an
  # unreadable label has to keep the tenant.
  warn "cannot read demo/persistent on ${ns} (${err//$'\n'/ }); treating '$1' as persistent"
  PERSISTENT_REASON="demo/persistent unreadable"
  return 0
}

# Full idempotent GC for one tenant id. `reason` ends up in the AUDIT detail.
gc_tenant() {
  local id="$1" reason="${2:-expired}" sid ns db
  sid="$(sanitize_id "${id}")"
  ns="$(tenant_namespace "${id}")"
  db="$(tenant_db_name "${id}")"
  # 2, not 0: callers ignore it, except reap_expired, whose tally would otherwise
  # report a persistent tenant as reaped.
  if tenant_is_persistent "${id}"; then
    log "tenant '${id}' is persistent (${PERSISTENT_REASON}); NOT reaping (${reason})"
    return 2
  fi
  log "reaping tenant '${id}' (${reason}) -> ns=${ns} db=${db}"

  # (a) namespace, (b) RDS DB, (e) legacy IRSA trust — reuse the existing
  # teardown script (it is safe when the namespace is already gone and preserves
  # the shared otterworks-* StringLike trust).
  "${REPO_ROOT}/scripts/teardown-tenant.sh" "${id}" \
    || warn "  teardown-tenant.sh reported issues for ${id} (continuing GC)"

  gc_s3 "${sid}"          # (c)
  gc_ddb "${sid}"         # (d)
  gc_route53 "${sid}"     # (f)
  ctl_delete_tenant "${id}"                       # (g)
  ctl_audit "${id}" reap "reaped:${reason} ns=${ns} db=${db}"
  log "  tenant '${id}' reaped."
}

# ------------------------------------------------------------------------------
# Listing helpers (shared resources)
# ------------------------------------------------------------------------------
list_shared_buckets() {
  aws s3api list-buckets \
    --query "Buckets[?starts_with(Name, '${SHARED_S3_PREFIX}')].Name" \
    --output text 2>/dev/null | tr '\t' '\n'
}
list_shared_ddb_tables() {
  aws dynamodb list-tables --region "${AWS_REGION}" --output json 2>/dev/null \
    | jq -r --arg p "${SHARED_DDB_PREFIX}" '.TableNames[]? | select(startswith($p))'
}
ddb_hash_key() {
  aws dynamodb describe-table --table-name "$1" --region "${AWS_REGION}" --output json 2>/dev/null \
    | jq -r '.Table.KeySchema[]? | select(.KeyType=="HASH") | .AttributeName'
}
ddb_range_key() {
  aws dynamodb describe-table --table-name "$1" --region "${AWS_REGION}" --output json 2>/dev/null \
    | jq -r '.Table.KeySchema[]? | select(.KeyType=="RANGE") | .AttributeName // empty'
}

# ------------------------------------------------------------------------------
# 1. Reap expired tenants (control table is desired state)
# ------------------------------------------------------------------------------
reap_expired() {
  local grace="$1" now items count
  now="$(date -u +%s)"
  items="$(aws dynamodb scan --table-name "${CONTROL_TABLE}" --region "${AWS_REGION}" \
      --filter-expression "SK = :meta AND begins_with(PK, :tp)" \
      --expression-attribute-values '{":meta":{"S":"META"},":tp":{"S":"TENANT#"}}' \
      --output json 2>/dev/null | jq -c '.Items[]?' 2>/dev/null)"
  count=0
  while IFS= read -r item; do
    [ -n "${item}" ] || continue
    local id exp
    id="$(echo "${item}"  | jq -r '.id.S // (.PK.S | sub("^TENANT#";""))')"
    # Missing/blank expires_at => tenant is reserved or still deploying (its
    # expiry is written only by ctl_set_active on a successful deploy). Never
    # treat that as "expired at epoch 0"; skip it so an in-flight tenant is not
    # torn down mid-setup.
    exp="$(echo "${item}" | jq -r '.expires_at.N // empty')"
    [ -n "${id}" ] || continue
    if ! [[ "${exp}" =~ ^[0-9]+$ ]]; then
      log "tenant '${id}' has no valid expires_at; skipping (not reaping)"
      continue
    fi
    if [ "$(( exp + grace ))" -lt "${now}" ]; then
      gc_tenant "${id}" "expired(expires_at=${exp}+grace=${grace}<now=${now})" \
        && count=$(( count + 1 ))
    else
      log "tenant '${id}' not yet expired (expires_at=${exp}, grace=${grace})"
    fi
  done <<EOF
${items}
EOF
  log "expired-reap pass complete (${count} tenant(s) reaped)."
}

# ------------------------------------------------------------------------------
# 3. Orphan sweep (cluster/AWS is actual state; GC anything with no TENANT# item)
# ------------------------------------------------------------------------------
sweep_orphan_namespaces() {
  local ns id gc_rc
  for ns in $(kubectl get ns -l app.kubernetes.io/managed-by=otterworks-tenant \
                -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
    case "${ns}" in otterworks-platform|otterworks-system|otterworks) continue ;; esac
    id="${ns#otterworks-}"
    [ -n "${id}" ] || continue
    if ! ctl_tenant_exists "${id}"; then
      # The persistence check is gc_tenant's, not a second one here: every
      # standing tenant is item-less by design, so announcing the orphan before
      # the guard runs both doubles the label lookups over ~95 tenants and
      # reports a collection that did not happen. 2 is "persistent, kept", and
      # gc_tenant has already said so.
      gc_rc=0; gc_tenant "${id}" "orphan-namespace" || gc_rc=$?
      [ "${gc_rc}" = "2" ] || warn "orphan namespace ${ns} (no TENANT# item) -> GC"
    fi
  done
}

# List per-tenant databases (otterworks_<id>) via an in-cluster psql Job, reusing
# the shared secret-application helper (password via stdin, never argv).
list_tenant_dbs() {
  [ -n "${RDS_HOST:-}" ] || return 0
  [ -n "${DB_PASSWORD:-}" ] || return 0
  local ns="${SYSTEM_NAMESPACE}" job="tenant-db-list" secret="tenant-db-admin-list"
  kubectl get ns "${ns}" >/dev/null 2>&1 || kubectl create ns "${ns}" >/dev/null 2>&1 || true
  apply_db_admin_secret "${ns}" "${secret}"
  kubectl -n "${ns}" delete job "${job}" --ignore-not-found >/dev/null 2>&1 || true
  # RDS_HOST/RDS_PORT/DB_USER are set by tenant-common.sh:load_infra_outputs.
  # shellcheck disable=SC2153
  kubectl apply -n "${ns}" -f - >/dev/null 2>&1 <<YAML
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
              psql "\$CONN" -tAc "SELECT datname FROM pg_database WHERE datname LIKE 'otterworks\\_%'"
          resources:
            requests: { cpu: 50m, memory: 64Mi }
            limits: { cpu: 200m, memory: 128Mi }
YAML
  kubectl -n "${ns}" wait --for=condition=complete "job/${job}" --timeout=90s >/dev/null 2>&1 || true
  kubectl -n "${ns}" logs "job/${job}" 2>/dev/null | grep -E '^otterworks_' || true
  kubectl -n "${ns}" delete secret "${secret}" --ignore-not-found >/dev/null 2>&1 || true
  kubectl -n "${ns}" delete job "${job}" --ignore-not-found >/dev/null 2>&1 || true
}

sweep_orphan_dbs() {
  local db id gc_rc
  for db in $(list_tenant_dbs); do
    [ "${db}" = "otterworks" ] && continue
    id="${db#otterworks_}"
    [ -n "${id}" ] || continue
    if ! ctl_tenant_exists "${id}"; then
      # As above: gc_tenant owns the persistence check, and the sweep only
      # announces an orphan it actually collected.
      gc_rc=0; gc_tenant "${id}" "orphan-database" || gc_rc=$?
      [ "${gc_rc}" = "2" ] || warn "orphan database ${db} (no TENANT# item) -> GC"
    fi
  done
}

sweep_orphan_s3() {
  local bucket p id
  for bucket in $(list_shared_buckets); do
    for p in $(aws s3api list-objects-v2 --bucket "${bucket}" \
                 --prefix "${S3_TENANT_ROOT}" --delimiter "/" \
                 --query 'CommonPrefixes[].Prefix' --output text 2>/dev/null); do
      [ "${p}" = "None" ] && continue
      id="${p#"${S3_TENANT_ROOT}"}"; id="${id%/}"
      [ -n "${id}" ] || continue
      if ! ctl_tenant_exists "${id}" && ! tenant_is_persistent "${id}"; then
        warn "orphan S3 prefix s3://${bucket}/${p} (no TENANT# item) -> GC"
        aws s3 rm "s3://${bucket}/${p}" --recursive >/dev/null 2>&1 || true
      fi
    done
  done
}

sweep_orphan_ddb() {
  local table hk id
  for table in $(list_shared_ddb_tables); do
    [ "${table}" = "${CONTROL_TABLE}" ] && continue
    hk="$(ddb_hash_key "${table}")"; [ -n "${hk}" ] || continue
    # Distinct tenant partitions only: hash keys shaped "<id>#..." (see gc_ddb).
    for id in $(aws dynamodb scan --table-name "${table}" --region "${AWS_REGION}" \
                  --projection-expression "#hk" \
                  --expression-attribute-names "$(jq -n --arg hk "${hk}" '{"#hk":$hk}')" \
                  --output json 2>/dev/null \
                | jq -r --arg hk "${hk}" '.Items[]?[$hk].S // empty' \
                | grep '#' | sed 's/#.*//' | sort -u); do
      [ -n "${id}" ] || continue
      if ! ctl_tenant_exists "${id}" && ! tenant_is_persistent "${id}"; then
        warn "orphan DDB partition '${id}' in ${table} (no TENANT# item) -> GC"
        gc_ddb_partition "${table}" "${id}"
      fi
    done
  done
}

sweep_orphans() {
  log "orphan sweep starting..."
  sweep_orphan_namespaces
  sweep_orphan_dbs
  sweep_orphan_s3
  sweep_orphan_ddb
  log "orphan sweep complete."
}

# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------
main() {
  log "reaper v2 run at $(date -u +%Y-%m-%dT%H:%M:%SZ) (table=${CONTROL_TABLE})"
  local cfg enabled grace sweep infra infra_delete idle
  cfg="$(ctl_get "CONFIG#reaper" "CONFIG")"
  enabled="$(echo "${cfg}" | jq -r --arg d "${REAPER_ENABLED_DEFAULT}" '.Item.enabled.BOOL // ($d=="true")')"
  grace="$(echo "${cfg}"   | jq -r '.Item.grace_seconds.N // "0"')"
  sweep="$(echo "${cfg}"   | jq -r '.Item.sweep_orphans.BOOL // false')"
  infra="$(echo "${cfg}"   | jq -r '.Item.sweep_infra.BOOL // false')"
  infra_delete="$(echo "${cfg}" | jq -r '.Item.sweep_infra_delete.BOOL // false')"
  idle="$(echo "${cfg}"    | jq -r '.Item.suspend_idle.BOOL // false')"
  IDLE_AFTER_SECONDS="$(echo "${cfg}" | jq -r --arg d "${IDLE_AFTER_SECONDS}" '.Item.idle_after_seconds.N // $d')"

  if [ "${enabled}" != "true" ]; then
    log "CONFIG#reaper disabled (or absent); nothing to do. Exiting."
    exit 0
  fi
  log "config: enabled=${enabled} grace_seconds=${grace} sweep_orphans=${sweep} sweep_infra=${infra} sweep_infra_delete=${infra_delete} suspend_idle=${idle}"

  # Load shared infra outputs (RDS endpoint, bucket/table names) for GC.
  load_infra_outputs

  reap_expired "${grace}"

  # Suspend before sweeping: a tenant that is merely idle should be scaled to
  # zero, not deleted. Only TTL expiry deletes a tenant.
  if [ "${idle}" = "true" ]; then
    suspend_idle_tenants
  else
    log "suspend_idle disabled; skipping idle scan."
  fi

  if [ "${sweep}" = "true" ]; then
    sweep_orphans
  else
    log "sweep_orphans disabled; skipping orphan sweep."
  fi

  # The infra sweep deletes AWS resources rather than Kubernetes ones, so it is
  # gated separately from the tenant sweep and in two stages: sweep_infra runs
  # it, sweep_infra_delete arms it. Running it report-only first is the intended
  # workflow, because this account also holds resources this platform did not
  # create.
  #
  # DRY_RUN is set from the control table on both paths rather than left to
  # infra-sweep.sh's own default. Otherwise the scheduled run could never delete
  # anything -- the CronJob sets no DRY_RUN, so it would report forever while
  # the dashboard showed the sweep as on.
  if [ "${infra}" = "true" ]; then
    # shellcheck disable=SC2034  # read by act() in the sourced infra-sweep.sh
    if [ "${infra_delete}" = "true" ]; then
      DRY_RUN=false
      log "infrastructure sweep armed: orphans matching an ownership tag will be deleted."
    else
      DRY_RUN=true
      log "infrastructure sweep in report-only mode (set sweep_infra_delete to arm it)."
    fi
    infra_sweep
  else
    log "sweep_infra disabled; skipping infrastructure orphan sweep."
  fi

  log "reaper v2 run complete."
}

# Allow the GC helpers to be sourced (test-persistent-tenant.sh) without running
# a reap pass; the CronJob and the runner both execute this file directly.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  main "$@"
fi
