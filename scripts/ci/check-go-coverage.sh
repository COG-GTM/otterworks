#!/usr/bin/env bash
# Fail if total Go statement coverage in a coverprofile is below a minimum.
# Usage: scripts/ci/check-go-coverage.sh <coverage.out> <min-percent>
set -euo pipefail
profile="${1:?coverprofile path required}"
min="${2:?minimum percent required}"
total="$(go tool cover -func="$profile" | awk '/^total:/ {gsub("%", "", $NF); print $NF}')"
echo "Go total coverage: ${total}% (minimum ${min}%)"
awk -v t="$total" -v m="$min" 'BEGIN { exit !(t + 0 >= m + 0) }' || {
  echo "::error::Go coverage ${total}% is below the ${min}% minimum"
  exit 1
}
