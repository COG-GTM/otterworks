#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Argument-handling tests for deploy-dev.sh.
#
# A mistyped flag (e.g. --skip-terrafrom) must stop the script before it touches
# any cloud tooling; otherwise it falls through to a full Terraform provision.
#
# aws / terraform / kubectl / docker / helm are stubbed; this runs anywhere.
# ------------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY="${SCRIPT_DIR}/deploy-dev.sh"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
nope() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else nope "$1 (expected '$3', got '$2')"; fi; }
contains() { case "$2" in *"$3"*) ok "$1" ;; *) nope "$1 (missing '$3' in: $2)" ;; esac; }

STUBS="$(mktemp -d)"
CALLS="${STUBS}/calls.log"
trap 'rm -rf "${STUBS}"' EXIT
for c in aws terraform kubectl docker helm; do
  printf '#!/bin/sh\necho "%s $*" >> "%s"\nexit 1\n' "$c" "${CALLS}" > "${STUBS}/$c"
  chmod +x "${STUBS}/$c"
done

# run <AWS_ACCOUNT_ID or ""> args... -> sets OUT, RC, TOOLS
run() {
  local acct="$1"; shift
  : > "${CALLS}"
  if [ -n "${acct}" ]; then
    OUT="$(PATH="${STUBS}:${PATH}" AWS_ACCOUNT_ID="${acct}" bash "${DEPLOY}" "$@" 2>&1)"; RC=$?
  else
    OUT="$(env -u AWS_ACCOUNT_ID PATH="${STUBS}:${PATH}" bash "${DEPLOY}" "$@" 2>&1)"; RC=$?
  fi
  TOOLS="$(cat "${CALLS}")"
}

echo "unknown argument is rejected before any tool runs"
run 000000000000 --skip-terrafrom
check "exit code" "${RC}" "2"
contains "names the bad argument" "${OUT}" "unknown argument: --skip-terrafrom"
contains "prints usage" "${OUT}" "usage:"
check "no cloud tooling invoked" "${TOOLS}" ""

echo "unknown argument is rejected without AWS_ACCOUNT_ID"
run "" --bogus
check "exit code" "${RC}" "2"
contains "names the bad argument" "${OUT}" "unknown argument: --bogus"
check "no cloud tooling invoked" "${TOOLS}" ""

echo "--help works without AWS_ACCOUNT_ID"
run "" --help
check "exit code" "${RC}" "0"
contains "prints usage block" "${OUT}" "--skip-terraform"
check "no cloud tooling invoked" "${TOOLS}" ""

echo "valid flags are still honored"
run 000000000000 --skip-terraform --skip-build
contains "skips Terraform" "${OUT}" "Skipping Terraform provisioning."
case "${TOOLS}" in
  "aws eks update-kubeconfig"*) ok "first tool call is kubeconfig, not terraform" ;;
  *) nope "first tool call is kubeconfig, not terraform (got: ${TOOLS})" ;;
esac

echo
echo "${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
