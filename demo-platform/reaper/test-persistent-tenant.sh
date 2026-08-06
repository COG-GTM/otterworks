#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Safety tests for the persistent-tenant guard in the reaper.
#
# A tenant deployed with `deploy-tenant.sh <id> --ttl none` is a standing
# per-person environment: it has no expiry, and (unless the dashboard created
# one) no control-table item either. "No control item" is exactly the signal the
# orphan sweep deletes on, so without the demo/persistent guard an armed sweep
# would drop every one of those namespaces, their databases and their S3 data.
# These tests pin that invariant from both directions.
#
# The aws CLI, kubectl and teardown-tenant.sh are stubbed; nothing here touches
# a real account or cluster.
# ------------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
nope() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else nope "$1 (expected '$3', got '$2')"; fi; }

PERSISTENT_LABEL=""     # what `kubectl get ns` reports for demo/persistent
CTL_ITEM_ID=""          # the one tenant id the control table has a TENANT# item for
NS_LOOKUP_ERR=""        # when set, the namespace lookup fails with this on stderr
NS_LOOKUP_WARN=""       # printed on stderr by a lookup that still succeeds
DELETED=""              # every destructive call the reaper attempted

kubectl() {
  case "$*" in
    *"labels.demo/persistent"*)
      if [ -n "${NS_LOOKUP_ERR}" ]; then echo "${NS_LOOKUP_ERR}" >&2; return 1; fi
      [ -z "${NS_LOOKUP_WARN}" ] || echo "${NS_LOOKUP_WARN}" >&2
      printf '%s' "${PERSISTENT_LABEL}"; return 0 ;;
    *"get ns -l app.kubernetes.io/managed-by=otterworks-tenant"*)
      printf 'otterworks-ada-lovelace'; return 0 ;;
    *) return 0 ;;
  esac
}

aws() {
  case "$*" in
    # No TENANT#<id> item unless CTL_ITEM_ID names one: a tenant deployed straight
    # from the script has none, so ctl_tenant_exists is false and only the
    # persistence guard protects it.
    *"get-item"*)
      if [ -n "${CTL_ITEM_ID}" ] && [ "$*" != "${*//TENANT#${CTL_ITEM_ID}\"/}" ]; then
        printf '{"Item":{"PK":{"S":"TENANT#%s"},"SK":{"S":"META"}}}' "${CTL_ITEM_ID}"
      else
        printf '{}'
      fi
      return 0 ;;
    *"s3api list-buckets"*)  printf 'otterworks-files-dev'; return 0 ;;
    *"list-objects-v2"*)     printf 'tenants/ada-lovelace/'; return 0 ;;
    *"s3 rm"*)               DELETED="${DELETED} $*"; return 0 ;;
    *"delete-item"*)         DELETED="${DELETED} $*"; return 0 ;;
    *) return 0 ;;
  esac
}

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/reaper.sh"

# Redirect the teardown the reaper shells out to, so a "reap" is observable
# without deleting anything. Set after sourcing: reaper.sh computes REPO_ROOT.
FAKE_ROOT="$(mktemp -d)"
trap 'rm -rf "${FAKE_ROOT}"' EXIT
mkdir -p "${FAKE_ROOT}/scripts"
cat > "${FAKE_ROOT}/scripts/teardown-tenant.sh" <<'EOS'
#!/usr/bin/env bash
echo "teardown:$1" >> "${TEARDOWN_LOG}"
EOS
chmod +x "${FAKE_ROOT}/scripts/teardown-tenant.sh"
# shellcheck disable=SC2034  # read by gc_tenant from the sourced reaper
REPO_ROOT="${FAKE_ROOT}"
export TEARDOWN_LOG="${FAKE_ROOT}/teardown.log"
: > "${TEARDOWN_LOG}"

echo "reaper persistent-tenant guard"

PERSISTENT_LABEL="true"
tenant_is_persistent ada-lovelace && r=yes || r=no
check "recognises a persistent tenant" "${r}" "yes"

PERSISTENT_LABEL=""
tenant_is_persistent ada-lovelace && r=yes || r=no
check "recognises an ordinary tenant" "${r}" "no"

# kubectl writes to stderr on plenty of successful calls -- API-server Warning
# headers, exec-plugin deprecation notices. Folded into the value, any of them
# makes the label compare unequal to "true" and the tenant is deleted.
PERSISTENT_LABEL="true"
NS_LOOKUP_WARN="Warning: v1 Namespace is deprecated in this cluster"
tenant_is_persistent ada-lovelace && r=yes || r=no
check "  even when the lookup also prints a warning" "${r}" "yes"
NS_LOOKUP_WARN=""

# The guard sits in gc_tenant, which is the single choke point for the expiry
# reap, the orphan-namespace sweep and the orphan-database sweep alike.
PERSISTENT_LABEL="true"
: > "${TEARDOWN_LOG}"
gc_tenant ada-lovelace "expired" >/dev/null 2>&1; rc=$?
check "never tears down a persistent tenant" "$(cat "${TEARDOWN_LOG}")" ""
# reap_expired tallies on this, so "skipped" has to be distinguishable from
# "reaped" or the pass reports deletions that never happened.
check "  and reports the skip to its caller" "${rc}" "2"

PERSISTENT_LABEL=""
: > "${TEARDOWN_LOG}"
gc_tenant ada-lovelace "expired" >/dev/null 2>&1; rc=$?
check "still tears down an expired ordinary tenant" "$(cat "${TEARDOWN_LOG}")" "teardown:ada-lovelace"
check "  and reports it reaped" "${rc}" "0"

# A persistent tenant has no TENANT# item, which is what the orphan sweep
# deletes on -- the case that would otherwise wipe the whole roster.
PERSISTENT_LABEL="true"
: > "${TEARDOWN_LOG}"
out="$(sweep_orphan_namespaces 2>&1)"
check "orphan-namespace sweep spares a persistent tenant" "$(cat "${TEARDOWN_LOG}")" ""
case "${out}" in *"orphan namespace"*) r=yes ;; *) r=no ;; esac
check "  and does not announce a collection it did not make" "${r}" "no"

PERSISTENT_LABEL=""
: > "${TEARDOWN_LOG}"
sweep_orphan_namespaces >/dev/null 2>&1
check "orphan-namespace sweep still GCs a genuine orphan" "$(cat "${TEARDOWN_LOG}")" "teardown:ada-lovelace"

# The database sweep goes through gc_tenant, so the data was never at risk --
# but every standing tenant is item-less by design, and announcing ~95 orphans
# it will not collect buries the one real orphan in the same log.
list_tenant_dbs() { echo "otterworks_ada_lovelace"; }
PERSISTENT_LABEL="true"
: > "${TEARDOWN_LOG}"
out="$(sweep_orphan_dbs 2>&1)"
check "orphan-database sweep spares a persistent tenant" "$(cat "${TEARDOWN_LOG}")" ""
case "${out}" in *"orphan database"*) r=yes ;; *) r=no ;; esac
check "  and does not announce it as an orphan" "${r}" "no"

PERSISTENT_LABEL=""
: > "${TEARDOWN_LOG}"
sweep_orphan_dbs >/dev/null 2>&1
check "orphan-database sweep still GCs a genuine orphan" "$(cat "${TEARDOWN_LOG}")" "teardown:ada-lovelace"

# And it has to ask about the tenant in the spelling the control table uses. A
# database name writes '_' where the id has '-', so stripping the prefix alone
# asks about a tenant that cannot exist -- and for every hyphenated id, which is
# now every id the roster derives, the answer is "orphan". gc_tenant re-sanitises
# what it is handed, so the namespace and database it deletes are the live
# tenant's; only the TENANT# item, looked up under the mis-spelling, survives.
CTL_ITEM_ID="ada-lovelace"
: > "${TEARDOWN_LOG}"
sweep_orphan_dbs >/dev/null 2>&1
check "orphan-database sweep spares a live tenant with a hyphenated id" "$(cat "${TEARDOWN_LOG}")" ""
CTL_ITEM_ID=""

# Its data is guarded separately: the S3 and DynamoDB sweeps delete objects
# directly rather than going through gc_tenant.
PERSISTENT_LABEL="true"
DELETED=""
sweep_orphan_s3 >/dev/null 2>&1
check "orphan-S3 sweep spares a persistent tenant's prefix" "${DELETED# }" ""

PERSISTENT_LABEL=""
DELETED=""
sweep_orphan_s3 >/dev/null 2>&1
check "orphan-S3 sweep still clears a genuine orphan's prefix" \
  "${DELETED# }" "s3 rm s3://otterworks-files-dev/tenants/ada-lovelace/ --recursive"

# An unreadable label is not a licence to delete. The S3/DynamoDB sweeps have no
# second opinion to fall back on -- a persistent tenant has no TENANT# item by
# design -- so a throttled, unauthorised or unreachable API has to keep the data.
PERSISTENT_LABEL="true"
NS_LOOKUP_ERR="error: You must be logged in to the server (Unauthorized)"
tenant_is_persistent ada-lovelace && r=yes || r=no
check "treats an unreadable label as persistent" "${r}" "yes"

DELETED=""
sweep_orphan_s3 >/dev/null 2>&1
check "orphan-S3 sweep spares a tenant it cannot read" "${DELETED# }" ""

: > "${TEARDOWN_LOG}"
gc_tenant ada-lovelace "expired" >/dev/null 2>&1
check "never reaps a tenant it cannot read" "$(cat "${TEARDOWN_LOG}")" ""

# A namespace that is genuinely gone is the orphan the sweeps exist for, so that
# one failure mode must still read as "not persistent".
NS_LOOKUP_ERR='Error from server (NotFound): namespaces "otterworks-ada-lovelace" not found'
tenant_is_persistent ada-lovelace && r=yes || r=no
check "a deleted namespace is not persistent" "${r}" "no"

DELETED=""
sweep_orphan_s3 >/dev/null 2>&1
check "orphan-S3 sweep still clears data whose namespace is gone" \
  "${DELETED# }" "s3 rm s3://otterworks-files-dev/tenants/ada-lovelace/ --recursive"
NS_LOOKUP_ERR=""

# --- the dashboard's copy of the sweep's definition ---------------------------
# The ops dashboard's clean-up preview answers "what would this sweep delete",
# and it answers from constants in lib/env.ts that restate what the sweep does:
# the label it enumerates by, and the namespaces it refuses whatever they are
# labelled. A restatement drifts silently -- the page would keep looking right
# while describing a sweep that no longer exists -- so the two are compared here
# rather than trusted to stay in step.
REAPER_SH="${SCRIPT_DIR}/reaper.sh"
ENV_TS="${SCRIPT_DIR}/../dashboard/lib/env.ts"

# Both sides are scraped, so both scrapes have to be checked for having found
# anything: two empty strings compare equal, and an assertion that passes
# because it read neither file is worse than no assertion -- it reports the two
# as in step for as long as it takes somebody to reformat either one.
found() { if [ -n "$2" ]; then ok "$1"; else nope "$1 (read nothing -- the scrape below is comparing nothing)"; fi; }

sweep_label="$(sed -n 's/.*kubectl get ns -l \([^ ]*\).*/\1/p' "${REAPER_SH}" | head -1)"
env_label="$(sed -n 's/^export const SWEEP_LABEL = "\(.*\)";$/\1/p' "${ENV_TS}")"
found "reads the sweep's selector out of reaper.sh" "${sweep_label}"
found "reads SWEEP_LABEL out of the dashboard's env.ts" "${env_label}"
check "the dashboard preview enumerates by the sweep's label" "${env_label}" "${sweep_label}"

sweep_excluded="$(sed -n 's/.*case "${ns}" in \(.*\)) continue.*/\1/p' "${REAPER_SH}" \
  | tr '|' '\n' | sort | tr '\n' ' ')"
env_excluded="$(sed -n '/SWEEP_EXCLUDED_NAMESPACES/,/^]/p' "${ENV_TS}" \
  | grep -o '"[^"]*"' | tr -d '"' | sort | tr '\n' ' ')"
found "reads the sweep's exclusion list out of reaper.sh" "${sweep_excluded// /}"
found "reads SWEEP_EXCLUDED_NAMESPACES out of the dashboard's env.ts" "${env_excluded// /}"
check "  and skips the same namespaces the sweep refuses" "${env_excluded}" "${sweep_excluded}"

echo ""
echo "  ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
