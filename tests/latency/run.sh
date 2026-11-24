#!/usr/bin/env bash
# Runs the latency scripts and checks the results against budgets.json.
#   tests/latency/run.sh [auth|audit|gateway ...]   (default: all three)
# Env: RATE (req/s per endpoint, default 10), DURATION (default 30s), WARMUP (default 10s),
#      AUTH_URL, AUDIT_URL, GATEWAY_URL, SEED_EVENTS, OUT_DIR.
set -euo pipefail
cd "$(dirname "$0")/../.."
export OUT_DIR="${OUT_DIR:-tests/latency/results}"
mkdir -p "$OUT_DIR"
services=("$@")
[ ${#services[@]} -eq 0 ] && services=(auth audit gateway)
results=()
for svc in "${services[@]}"; do
  k6 run --quiet "tests/latency/${svc}.js"
  case "$svc" in
    auth) results+=("$OUT_DIR/auth-service.json") ;;
    audit) results+=("$OUT_DIR/audit-service.json") ;;
    gateway) results+=("$OUT_DIR/api-gateway.json") ;;
  esac
done
python3 tests/latency/check_budget.py ${CHECK_ARGS:-} "${results[@]}"
