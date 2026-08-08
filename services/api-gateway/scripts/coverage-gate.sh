#!/usr/bin/env sh
# Coverage ratchet for the api-gateway.
#
# Go has no --fail-under flag, so the gate reads the `total:` line of
# `go tool cover -func`. MIN is a ratchet: raise it when coverage rises,
# never lower it.
#
#   sh scripts/coverage-gate.sh [coverage-profile] [min-percent]
#
# The profile must be produced with -coverpkg=./..., otherwise packages
# without their own test file are omitted from the report instead of being
# counted as 0%.
set -eu

PROFILE="${1:-coverage.out}"
MIN="${2:-${COVERAGE_MIN:-95.0}}"

if [ ! -f "$PROFILE" ]; then
	echo "coverage profile not found: $PROFILE" >&2
	echo "run: go test -coverpkg=./... -coverprofile=$PROFILE ./..." >&2
	exit 1
fi

go tool cover -func="$PROFILE" | awk -v min="$MIN" '
	/^total:/ {
		c = $NF; sub(/%/, "", c)
		found = 1
		if (c + 0 < min) {
			printf "FAIL coverage %.1f%% < %.1f%%\n", c, min
			exit 1
		}
		printf "OK coverage %.1f%% >= %.1f%%\n", c, min
	}
	END { if (!found) { print "FAIL no total line in coverage profile"; exit 1 } }
'
