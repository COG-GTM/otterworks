#!/usr/bin/env bash
#
# Coverage gate for file-service.
#
# Runs the unit-test suite under cargo-llvm-cov and fails when coverage drops
# below the floors below. The floors are the values actually measured on the
# commit that introduced this script (98.41% lines / 95.64% regions, rounded
# down): ratchet them up as coverage improves, never down.
#
#   ./coverage.sh                 # gate, summary only
#   ./coverage.sh --html          # gate + HTML report in target/llvm-cov/html
#   ./coverage.sh --lcov --output-path lcov.info
#
# Requires: cargo-llvm-cov (cargo install cargo-llvm-cov) and the
# llvm-tools-preview rustup component.
set -euo pipefail

cd "$(dirname "$0")"

MIN_LINES="${MIN_LINES:-98}"
MIN_REGIONS="${MIN_REGIONS:-95}"

# cargo-llvm-cov rejects --summary-only alongside a report format, so it is only
# added when the caller asked for no other output.
format=""
for arg in "$@"; do
  case "$arg" in
    --html | --open | --lcov | --json | --cobertura | --codecov | --text)
      format="yes"
      ;;
  esac
done
if [ -z "$format" ]; then
  set -- --summary-only "$@"
fi

exec cargo llvm-cov \
  --fail-under-lines "$MIN_LINES" \
  --fail-under-regions "$MIN_REGIONS" \
  "$@"
