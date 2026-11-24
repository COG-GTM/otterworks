#!/usr/bin/env bash
# Run the platform latency scripts and check every endpoint's p95 against
# budgets.json. Exits non-zero if any endpoint is over budget or erroring.
#
#   tests/latency/run.sh                      # all services, all endpoints
#   tests/latency/run.sh auth audit           # selected services
#   ENDPOINTS=auth_profile,gateway_health tests/latency/run.sh   # selected endpoints
#   RATE=10 DURATION_S=30 tests/latency/run.sh                     # load shape (defaults)
set -uo pipefail
cd "$(dirname "$0")"
export RESULTS_DIR="${RESULTS_DIR:-results}"
mkdir -p "$RESULTS_DIR"

services=("$@")
[ ${#services[@]} -eq 0 ] && services=(auth audit gateway)

declare -A endpoints_of=(
  [auth]="auth_register auth_login auth_profile"
  [audit]="audit_record_event audit_query_events"
  [gateway]="gateway_health gateway_profile gateway_audit_record"
)

status=0
for svc in "${services[@]}"; do
  if [ -n "${ENDPOINTS:-}" ]; then
    hit=0
    for e in ${endpoints_of[$svc]}; do [[ ",$ENDPOINTS," == *",$e,"* ]] && hit=1; done
    [ $hit -eq 0 ] && continue
  fi
  echo ">>> $svc"
  k6 run --quiet "$svc.js"
  rc=$?
  if [ $rc -eq 99 ]; then
    echo "!!! $svc: p95 budget or error-rate threshold failed"
    status=1
  elif [ $rc -ne 0 ]; then
    echo "!!! $svc: k6 exited $rc"
    status=$rc
  fi
done

python3 - "$RESULTS_DIR" "${services[@]}" <<'PY'
import json, os, sys
out, svcs = sys.argv[1], sys.argv[2:]
names = {"auth": "auth-service", "audit": "audit-service", "gateway": "api-gateway"}
rows = []
for s in svcs:
    f = os.path.join(out, names[s] + ".json")
    if os.path.exists(f):
        rows += json.load(open(f))["endpoints"]
rows.sort(key=lambda r: -r["p95_ms"])
print("\n| Endpoint | Request | p50 ms | p95 ms | p99 ms | p95 budget ms | Status |")
print("|---|---|---|---|---|---|---|")
for r in rows:
    print(f"| {r['endpoint']} | {r['method_path']} | {r['p50_ms']} | {r['p95_ms']} | {r['p99_ms']} | {r['budget_p95_ms']} | {'OVER' if r['over_budget'] else 'ok'} |")
PY
[ $status -eq 0 ] && echo "PASS: all checked endpoints within p95 budget" || echo "FAIL: see above"
exit $status
