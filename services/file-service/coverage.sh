#!/usr/bin/env bash
#
# Coverage gate for file-service.
#
# Runs the unit-test suite under cargo-llvm-cov and fails when coverage drops
# below the floors below. The floors are the measured coverage of this branch,
# rounded down (98.24% lines / 95.64% regions at the time of writing): ratchet
# them up as coverage improves, never down.
#
#   ./coverage.sh                 # gate, summary only
#   ./coverage.sh --html          # gate + HTML report in target/llvm-cov/html
#   ./coverage.sh --lcov --output-path lcov.info
#
# Requires: cargo-llvm-cov (cargo install cargo-llvm-cov) and the
# llvm-tools-preview rustup component.
set -euo pipefail

cd "$(dirname "$0")"

# The ratchet. MIN_LINES/MIN_REGIONS may raise these for a stricter local run,
# but never lower them: lowering the gate has to be a reviewed edit to this file.
FLOOR_LINES=98
FLOOR_REGIONS=95

at_least() { # at_least <name> <floor> <requested>
  # A percentage is at most three digits; anything longer is rejected here
  # rather than reaching `[ -gt ]`, which errors on values outside intmax_t.
  case "$3" in
    '') echo "$2" ;;
    *[!0-9]* | ????*)
      echo "coverage.sh: ignoring $1=$3 (whole numbers only), gating at $2" >&2
      echo "$2"
      ;;
    *)
      set -- "$1" "$2" "$((10#$3))" # normalise 098 -> 98
      if [ "$3" -gt "$2" ]; then
        echo "$3"
      else
        [ "$3" -eq "$2" ] ||
          echo "coverage.sh: ignoring $1=$3 (below the $2 floor), gating at $2" >&2
        echo "$2"
      fi
      ;;
  esac
}

MIN_LINES=$(at_least MIN_LINES "$FLOOR_LINES" "${MIN_LINES:-}")
MIN_REGIONS=$(at_least MIN_REGIONS "$FLOOR_REGIONS" "${MIN_REGIONS:-}")

# cargo-llvm-cov rejects --summary-only alongside a report format, so it is only
# added when the caller asked for no other output -- and not added twice when the
# caller passed it explicitly. Every expansion of "$@" is
# guarded, because bash < 4.4 (e.g. macOS 3.2) treats an empty "$@" as an unbound
# variable under `set -u`.
format=""
if [ "$#" -gt 0 ]; then
  for arg in "$@"; do
    case "$arg" in
      --summary-only | --html | --open | --lcov | --json | --cobertura | --codecov | --text | \
        --output-path | --output-path=*)
        format="yes"
        ;;
    esac
  done
fi
if [ -z "$format" ]; then
  set -- --summary-only ${1+"$@"}
fi

exec cargo llvm-cov \
  --fail-under-lines "$MIN_LINES" \
  --fail-under-regions "$MIN_REGIONS" \
  "$@"
