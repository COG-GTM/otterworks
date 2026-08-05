#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Render seed-loader.job.tpl.yaml for one tenant and print it on stdout.
#
# Every tenant is a namespace of its own (otterworks-<id>) with its own
# api-gateway Service, so the loader Job has to be stamped per tenant rather
# than applied from a manifest pinned to one namespace. Rendering is `sed` over
# __PLACEHOLDER__ tokens, the same convention scripts/enable-dns-tls.sh uses for
# demo-platform/k8s/dns-tls.
#
# Usage:
#   render-seed-job.sh <tenant-id> [scale] [departments]
#
# Examples:
#   # seed the ephemeral tenant `coggtm` with a quick, data-rich subset
#   render-seed-job.sh coggtm 0.1 | kubectl apply -f -
#
#   # the full drive (~2,445 files / 15 departments), one department only, ...
#   render-seed-job.sh coggtm 1.0 | kubectl apply -f -
#   render-seed-job.sh coggtm 1.0 Finance | kubectl apply -f -
#
#   # ... or a single-tenant (non-demo-platform) deploy, whose namespace is not
#   # derived from a tenant id
#   TENANT_NAMESPACE=otterworks render-seed-job.sh otterworks | kubectl apply -f -
#
# Overrides (env):
#   TENANT_NAMESPACE  target namespace            (default otterworks-<id>)
#   GATEWAY_URL       in-cluster gateway          (default derived from the namespace)
#   REPO_URL/REPO_REF repo the init container clones the generator from
#
# The Job reads DRIVE_EMAIL / DRIVE_PASSWORD from a `retail-drive-seed` Secret,
# which must already exist IN THE TARGET NAMESPACE:
#   kubectl -n otterworks-<id> create secret generic retail-drive-seed \
#       --from-literal=DRIVE_EMAIL='<email>' --from-literal=DRIVE_PASSWORD='<password>'
# ------------------------------------------------------------------------------
set -euo pipefail

TEMPLATE="$(cd "$(dirname "$0")" && pwd)/seed-loader.job.tpl.yaml"

fail() { echo "[seed] ERROR: $*" >&2; exit 1; }

id="${1:-}"
scale="${2:-1.0}"
departments="${3:-all}"

[ -n "${id}" ] || fail "usage: render-seed-job.sh <tenant-id> [scale] [departments]"
[ -f "${TEMPLATE}" ] || fail "template not found: ${TEMPLATE}"

# The id lands in a namespace name, so hold it to the same RFC 1123 shape the
# platform's sanitizeId() produces rather than letting a stray character render
# a manifest that the API server rejects (or, worse, one that targets something
# other than the intended tenant).
case "${id}" in
  *[!a-z0-9-]*|-*|*-|"") fail "invalid tenant id '${id}' (lowercase alphanumeric and '-', not leading/trailing)" ;;
esac

namespace="${TENANT_NAMESPACE:-otterworks-${id}}"
case "${namespace}" in
  *[!a-z0-9-]*|-*|*-|"") fail "invalid namespace '${namespace}' (RFC 1123 label)" ;;
esac
gateway_url="${GATEWAY_URL:-http://api-gateway.${namespace}.svc.cluster.local:8080}"
repo_url="${REPO_URL:-https://github.com/Cognition-Partner-Workshops/otterworks.git}"
repo_ref="${REPO_REF:-main}"

case "${scale}" in
  ''|*[!0-9.]*|*.*.*|.*|*.|0|0.0) fail "invalid scale '${scale}' (a positive number, e.g. 0.1 or 1.0)" ;;
esac
# Rendered into the manifest by sed, so anything that is special to sed (`#`,
# `&`, `\`) is refused rather than silently mangling the Job spec.
case "${departments}" in
  ''|*[!A-Za-z0-9,_\ -]*) fail "invalid departments '${departments}' (comma-separated names, or 'all')" ;;
esac

sed -e "s#__TENANT_NAMESPACE__#${namespace}#g" \
    -e "s#__GATEWAY_URL__#${gateway_url}#g" \
    -e "s#__SCALE__#${scale}#g" \
    -e "s#__DEPARTMENTS__#${departments}#g" \
    -e "s#__REPO_URL__#${repo_url}#g" \
    -e "s#__REPO_REF__#${repo_ref}#g" \
    "${TEMPLATE}"
