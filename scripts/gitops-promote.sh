#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Promote image tags one step along dev -> staging -> prod in the GitOps tree
# (deploy/gitops/envs/<env>/services/<service>.yaml). Edits files only: it never
# talks to a cluster. Argo CD applies the change once the promotion PR merges.
#
# Usage:
#   scripts/gitops-promote.sh <from-env> <to-env> [service ...]   # default: all
#   scripts/gitops-promote.sh dev staging
#   scripts/gitops-promote.sh staging prod api-gateway web-app
#
# Prints one "service: old -> new" line per change; exits 0 with no output when
# the target is already up to date. Requires mikefarah yq v4.
# ------------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVS_DIR="${ROOT}/deploy/gitops/envs"

die() { echo "gitops-promote: $*" >&2; exit 1; }

[ $# -ge 2 ] || die "usage: $0 <from-env> <to-env> [service ...]"
from="$1"; to="$2"; shift 2

case "${from}->${to}" in
  dev-\>staging|staging-\>prod) ;;
  *) die "only dev->staging and staging->prod are allowed (got ${from}->${to})" ;;
esac
command -v yq >/dev/null 2>&1 || die "yq (mikefarah v4) is required"

if [ $# -eq 0 ]; then
  services=()
  for f in "${ENVS_DIR}/${from}/services/"*.yaml; do services+=("$(basename "${f}" .yaml)"); done
else
  services=("$@")
fi

for svc in "${services[@]}"; do
  src="${ENVS_DIR}/${from}/services/${svc}.yaml"
  dst="${ENVS_DIR}/${to}/services/${svc}.yaml"
  [ -f "${src}" ] || die "no ${from} values for ${svc} (${src})"
  [ -f "${dst}" ] || die "no ${to} values for ${svc} (${dst})"
  new="$(yq -r '.image.tag' "${src}")"
  old="$(yq -r '.image.tag' "${dst}")"
  [[ "${new}" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || die "${src}: invalid image.tag '${new}'"
  [ "${new}" != latest ] || die "${src}: refusing to promote mutable tag 'latest'"
  if [ "${new}" != "${old}" ]; then
    NEW_TAG="${new}" yq -i '.image.tag = strenv(NEW_TAG)' "${dst}"
    echo "${svc}: ${old} -> ${new}"
  fi
done
