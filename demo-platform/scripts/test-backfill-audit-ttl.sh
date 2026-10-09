#!/usr/bin/env bash
# Unit tests for backfill-audit-ttl.sh. `aws` is stubbed; this runs anywhere.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
nope() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else nope "$1 (expected '$3', got '$2')"; fi; }

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/backfill-audit-ttl.sh"
set +e

SCAN_JSON=""
UPDATES=""
aws() {
  case "$2" in
    scan) printf '%s' "$SCAN_JSON" ;;
    update-item)
      local key="" vals="" args=("$@") i
      for ((i = 0; i < ${#args[@]}; i++)); do
        case "${args[i]}" in
          --key) key="${args[i+1]}" ;;
          --expression-attribute-values) vals="${args[i+1]}" ;;
        esac
      done
      UPDATES+="$(jq -r '.SK.S' <<<"$key")=$(jq -r '.[":t"].N' <<<"$vals");"
      [[ "$key" != *boom* ]]
      ;;
  esac
}

echo "audit_ttl"
check "ttl from ms ts"          "$(audit_ttl 1700000000123 0 90)" "$((1700000000 + 90 * 86400))"
check "missing ts uses now"     "$(audit_ttl "" 1800000000 90)"    "$((1800000000 + 90 * 86400))"
check "garbage ts uses now"     "$(audit_ttl "1.5e3" 1800000000 1)" "$((1800000000 + 86400))"

echo "retention_days"
check "default"            "$(AUDIT_RETENTION_DAYS='' retention_days)"  "90"
check "integer honoured"   "$(AUDIT_RETENTION_DAYS=30 retention_days)"  "30"
check "fraction falls back" "$(AUDIT_RETENTION_DAYS=0.5 retention_days)" "90"
check "zero falls back"    "$(AUDIT_RETENTION_DAYS=0 retention_days)"   "90"

echo "main"
SCAN_JSON='{"Items":[
  {"PK":{"S":"AUDIT#_auth"},"SK":{"S":"1700000000000#login_fail"},"ts":{"N":"1700000000000"}},
  {"PK":{"S":"AUDIT#t1"},"SK":{"S":"1700000001000#checkout"}}
]}'
UPDATES=""
out="$(AUDIT_RETENTION_DAYS=1 main; echo "rc=$?")"
# main runs in a subshell above; re-run in this shell to observe UPDATES.
AUDIT_RETENTION_DAYS=1 main >/dev/null
check "updates every untimed item from its ts" \
  "$(cut -d';' -f1 <<<"$UPDATES")" "1700000000000#login_fail=$((1700000000 + 86400))"
check "reports counts" "$(head -1 <<<"$out")" "audit items without ttl: 2; updated: 2; failed: 0"
check "exit 0 when all updated" "$(tail -1 <<<"$out")" "rc=0"

UPDATES=""
out="$(DRY_RUN=1 main)"
DRY_RUN=1 main >/dev/null
check "dry run writes nothing" "$UPDATES" ""
check "dry run counts" "$out" "audit items without ttl: 2; updated: 0; failed: 0 (dry run)"

SCAN_JSON='{"Items":[{"PK":{"S":"AUDIT#x"},"SK":{"S":"1#boom"},"ts":{"N":"1000"}}]}'
out="$(main; echo "rc=$?")"
check "failed update reported" "$(head -1 <<<"$out")" "audit items without ttl: 1; updated: 0; failed: 1"
check "non-zero exit on failure" "$(tail -1 <<<"$out")" "rc=1"

SCAN_JSON='{"Items":[]}'
check "empty table" "$(main)" "audit items without ttl: 0; updated: 0; failed: 0"

echo
echo "${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]
