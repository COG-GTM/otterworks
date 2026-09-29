#!/usr/bin/env bash
# Run the DAST harness so that its exit code survives.
#
# The make targets are the convenient handles, but GNU make reports 2 for any
# failed recipe whatever the command returned, and this harness says different
# things with 1 (findings), 2 (nothing was tested) and 3 (no verdict reached).
# Anything that *branches* on the outcome — CI, a remediation loop — has to call
# the scripts rather than make, so it calls this.
#
#   ./security/dast/run.sh scan     [--target URL] [...]
#   ./security/dast/run.sh verify   FINDING [--target URL]
#   ./security/dast/run.sh coverage [--report PATH]
#   ./security/dast/run.sh routes
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
harness="$here/harness"
target="${DAST_TARGET:-http://localhost:8080}"

command="${1:-scan}"
shift || true

case "$command" in
scan)
  exec uv run "$harness/dast_scan.py" --target "$target" "$@"
  ;;
verify)
  # 64, not the 1 that `${1:?}` would exit with: this script exists so a caller
  # can branch on the outcome, and a mistyped command must not read as "the
  # finding reproduced".
  if [ $# -eq 0 ]; then
    echo "usage: run.sh verify <FINDING-ID> [--target URL]" >&2
    exit 64
  fi
  finding="$1"
  shift
  # A verification ignores the baseline on purpose: an accepted finding is still
  # a finding while you are proving you closed it.
  exec uv run "$harness/dast_scan.py" \
    --target "$target" --only "$finding" --no-baseline --fail-on info "$@"
  ;;
coverage)
  exec uv run "$harness/dast_coverage.py" "$@"
  ;;
routes)
  exec uv run "$harness/route_inventory.py" "$@"
  ;;
*)
  echo "usage: run.sh {scan|verify|coverage|routes} [args]" >&2
  exit 64
  ;;
esac
