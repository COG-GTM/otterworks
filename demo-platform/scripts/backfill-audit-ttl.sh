#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# One-off backfill: give every pre-existing AUDIT# item a `ttl` so DynamoDB TTL
# prunes it. Writers set `ttl` on new items (lib/control.ts appendAudit,
# lib/control-common.sh ctl_audit); items written before that never expire.
#
# ttl = ts/1000 + AUDIT_RETENTION_DAYS*86400 (same formula as the writers), so
# items already past retention are expired by DynamoDB shortly after this runs.
# Items with no usable `ts` get now + retention. Idempotent: the update is
# conditional on `ttl` being absent, so re-runs and racing writers are safe.
#
# Usage:
#   demo-platform/scripts/backfill-audit-ttl.sh            # apply
#   DRY_RUN=1 demo-platform/scripts/backfill-audit-ttl.sh  # count only
# ------------------------------------------------------------------------------
set -euo pipefail

CONTROL_TABLE="${CONTROL_TABLE:-otterworks-demo-control}"
AWS_REGION="${AWS_REGION:-us-east-1}"

retention_days() {
  local days="${AUDIT_RETENTION_DAYS:-90}"
  [[ "$days" =~ ^[1-9][0-9]{0,4}$ ]] || days=90
  echo "$days"
}

# audit_ttl <ts_ms|""> <now_s> <days> -> epoch seconds
audit_ttl() {
  local ts="$1" now="$2" days="$3"
  if [[ "$ts" =~ ^[0-9]+$ ]]; then
    echo $(( ts / 1000 + days * 86400 ))
  else
    echo $(( now + days * 86400 ))
  fi
}

# One line per AUDIT# item lacking ttl: "<PK>\t<SK>\t<ts or empty>".
# The CLI paginates the scan itself and merges pages.
list_untimed() {
  aws dynamodb scan --table-name "${CONTROL_TABLE}" --region "${AWS_REGION}" \
    --filter-expression "begins_with(PK, :p) AND attribute_not_exists(#t)" \
    --projection-expression "PK, SK, ts" \
    --expression-attribute-names '{"#t":"ttl"}' \
    --expression-attribute-values '{":p":{"S":"AUDIT#"}}' \
    --output json | jq -r '.Items[]? | [.PK.S, .SK.S, (.ts.N // "")] | @tsv'
}

set_ttl() {
  local pk="$1" sk="$2" ttl="$3"
  aws dynamodb update-item --table-name "${CONTROL_TABLE}" --region "${AWS_REGION}" \
    --key "$(jq -n --arg pk "$pk" --arg sk "$sk" '{PK:{S:$pk},SK:{S:$sk}}')" \
    --update-expression "SET #t = :t" \
    --condition-expression "attribute_not_exists(#t)" \
    --expression-attribute-names '{"#t":"ttl"}' \
    --expression-attribute-values "$(jq -n --arg t "$ttl" '{":t":{N:$t}}')" \
    >/dev/null 2>&1
}

main() {
  local days now pk sk ts n=0 updated=0 failed=0
  days="$(retention_days)"
  now="$(date -u +%s)"
  while IFS=$'\t' read -r pk sk ts; do
    [ -n "$pk" ] || continue
    n=$((n + 1))
    [ -n "${DRY_RUN:-}" ] && continue
    if set_ttl "$pk" "$sk" "$(audit_ttl "$ts" "$now" "$days")"; then
      updated=$((updated + 1))
    else
      failed=$((failed + 1))
    fi
  done < <(list_untimed)
  echo "audit items without ttl: ${n}; updated: ${updated}; failed: ${failed}${DRY_RUN:+ (dry run)}"
  [ "$failed" -eq 0 ]
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
