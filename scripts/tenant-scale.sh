#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# OtterWorks - Per-Tenant Scale-to-Zero (cost control)
#
# Between sessions, scale a tenant's compute to zero while KEEPING the
# namespace, config/secrets and its RDS database intact — compute cost drops to
# ~0, spin-up is a single command.
#
# The per-tenant Redis and MeiliSearch run without persistence, so scaling down
# discards sessions, the search index (rebuilt on use) and any injected chaos
# flag. Re-inject the scenario after scaling a lab tenant back up.
#
# Usage:
#   ./scripts/tenant-scale.sh <ATTENDEE_ID> down   # scale all deployments to 0
#   ./scripts/tenant-scale.sh <ATTENDEE_ID> up     # scale all deployments to 1
# ------------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/tenant-common.sh
source "${SCRIPT_DIR}/lib/tenant-common.sh"

ATTENDEE_ID="${1:-}"
DIRECTION="${2:-}"
[ -n "${ATTENDEE_ID}" ] && [ -n "${DIRECTION}" ] || { err "Usage: $0 <ATTENDEE_ID> <up|down>"; exit 1; }
require_bins kubectl
NS="$(tenant_namespace "${ATTENDEE_ID}")"
kubectl get ns "${NS}" >/dev/null 2>&1 || { err "Namespace ${NS} not found."; exit 1; }

case "${DIRECTION}" in
  down) replicas=0 ;;
  up)   replicas=1 ;;
  *)    err "Direction must be 'up' or 'down'"; exit 1 ;;
esac

# Scaling an always-on tenant down does not stick: the idle scan finds it at
# zero, reads the label as a promise that the URL answers, and puts it back.
# Say so here rather than letting the operator discover it from the tenant
# coming back up on its own.
if [ "${replicas}" = "0" ] \
   && [ "$(kubectl get ns "${NS}" -o jsonpath='{.metadata.labels.demo/always-on}' 2>/dev/null)" = "true" ]; then
  warn "${NS} is labelled demo/always-on=true: the idle scan will scale it back up"
  warn "  within one pass. To park it, redeploy without --always-on (or remove the"
  warn "  label: kubectl label ns ${NS} demo/always-on-) and scale down after."
fi

log "Scaling all deployments in ${NS} to ${replicas}..."
kubectl -n "${NS}" scale deployment --all --replicas="${replicas}"
kubectl -n "${NS}" get deploy
