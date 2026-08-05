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
NS_LOOKUP_ERR=""        # when set, the namespace lookup fails with this on stderr
DELETED=""              # every destructive call the reaper attempted

kubectl() {
  case "$*" in
    *"labels.demo/persistent"*)
      if [ -n "${NS_LOOKUP_ERR}" ]; then echo "${NS_LOOKUP_ERR}" >&2; return 1; fi
      printf '%s' "${PERSISTENT_LABEL}"; return 0 ;;
    *"get ns -l app.kubernetes.io/managed-by=otterworks-tenant"*)
      printf 'otterworks-ada-lovelace'; return 0 ;;
    *) return 0 ;;
  esac
}

aws() {
  case "$*" in
    # No TENANT#<id> item: the tenant was deployed straight from the script, so
    # ctl_tenant_exists is false and only the persistence guard protects it.
    *"get-item"*)            printf '{}'; return 0 ;;
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

# The guard sits in gc_tenant, which is the single choke point for the expiry
# reap, the orphan-namespace sweep and the orphan-database sweep alike.
PERSISTENT_LABEL="true"
: > "${TEARDOWN_LOG}"
gc_tenant ada-lovelace "expired" >/dev/null 2>&1
check "never tears down a persistent tenant" "$(cat "${TEARDOWN_LOG}")" ""

PERSISTENT_LABEL=""
: > "${TEARDOWN_LOG}"
gc_tenant ada-lovelace "expired" >/dev/null 2>&1
check "still tears down an expired ordinary tenant" "$(cat "${TEARDOWN_LOG}")" "teardown:ada-lovelace"

# A persistent tenant has no TENANT# item, which is what the orphan sweep
# deletes on -- the case that would otherwise wipe the whole roster.
PERSISTENT_LABEL="true"
: > "${TEARDOWN_LOG}"
sweep_orphan_namespaces >/dev/null 2>&1
check "orphan-namespace sweep spares a persistent tenant" "$(cat "${TEARDOWN_LOG}")" ""

PERSISTENT_LABEL=""
: > "${TEARDOWN_LOG}"
sweep_orphan_namespaces >/dev/null 2>&1
check "orphan-namespace sweep still GCs a genuine orphan" "$(cat "${TEARDOWN_LOG}")" "teardown:ada-lovelace"

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

echo ""
echo "  ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
