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
# 63 is the label limit the API server applies; without this a long id renders a
# manifest that is only rejected at apply time, by which point the runner has
# already deleted the previous loader.
[ "${#namespace}" -le 63 ] || fail "invalid namespace '${namespace}' (${#namespace} characters, max 63)"
gateway_url="${GATEWAY_URL:-http://api-gateway.${namespace}.svc.cluster.local:8080}"
# `:-`, not `-`: the runner passes REPO_URL/REPO_REF through unconditionally and
# they are empty when its own SEED_REPO_* are unset, so empty has to mean default.
repo_url="${REPO_URL:-https://github.com/Cognition-Partner-Workshops/otterworks.git}"
repo_ref="${REPO_REF:-main}"

# A plain decimal, so no exponent notation (which the caller's language may
# produce for a small number) and no zero, which would seed an empty drive.
case "${scale}" in
  ''|*[!0-9.]*|*.*.*|.*|*.) fail "invalid scale '${scale}' (a positive number, e.g. 0.1 or 1.0)" ;;
esac
case "${scale//./}" in
  *[!0]*) ;;
  *) fail "invalid scale '${scale}' (must be greater than zero)" ;;
esac
# Three departments in taxonomy.py are named with an ampersand ("Supply Chain &
# Logistics"), and generate_drive.py matches department names exactly, so `&`
# has to be spellable here. It is also sed's "the whole match" though, hence the
# escape below; `#` and `\` have no such use and stay refused.
# The second case is for the separators-only values (",", ", ") that survive the
# first: generate_drive.py drops empty entries, so those select no department at
# all and the loader would succeed having uploaded nothing.
case "${departments}" in
  ''|*[!A-Za-z0-9,_\&\ -]*) fail "invalid departments '${departments}' (comma-separated names, or 'all')" ;;
esac
case "${departments}" in
  *[A-Za-z0-9]*) ;;
  *) fail "invalid departments '${departments}' (no department names in it)" ;;
esac
# A leading `-` is argparse's option prefix, so "-Finance" reaches the loader as
# `--departments -Finance` and kills the pod with "expected one argument"
# instead of failing here, where the message says which value was wrong.
case "${departments}" in
  -*) fail "invalid departments '${departments}' (a department name cannot start with '-')" ;;
esac
departments_sed="${departments//&/\\&}"
# The URL overrides are operator input, but they are still sed replacement text
# stamped into a manifest -- and GATEWAY_URL is where the loader sends requests
# carrying the drive credentials. Hold them to an http(s) URL of URL characters
# so neither a typo nor a stray `#`/`&`/`\` can mangle the Job or retarget it.
for pair in "GATEWAY_URL:${gateway_url}" "REPO_URL:${repo_url}"; do
  name="${pair%%:*}"
  value="${pair#*:}"
  case "${value}" in
    http://*|https://*) ;;
    *) fail "invalid ${name} '${value}' (must be an http:// or https:// URL)" ;;
  esac
  case "${value}" in
    *[!A-Za-z0-9:/?=@%._~-]*) fail "invalid ${name} '${value}' (unexpected character)" ;;
  esac
done
# A branch or a tag, not a commit: the init container clones with `--branch`,
# which does not take a SHA, so accepting one here would only move the failure
# into the loader pod as an opaque git error.
case "${repo_ref}" in
  ''|*[!A-Za-z0-9./_-]*) fail "invalid REPO_REF '${repo_ref}' (a branch or tag name)" ;;
esac

sed -e "s#__TENANT_NAMESPACE__#${namespace}#g" \
    -e "s#__GATEWAY_URL__#${gateway_url}#g" \
    -e "s#__SCALE__#${scale}#g" \
    -e "s#__DEPARTMENTS__#${departments_sed}#g" \
    -e "s#__REPO_URL__#${repo_url}#g" \
    -e "s#__REPO_REF__#${repo_ref}#g" \
    "${TEMPLATE}"
