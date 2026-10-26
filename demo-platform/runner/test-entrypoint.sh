#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Tests that the runner only ever executes its image's bundled tree.
#
# A tenant branch can be pushed by any workshop attendee with write access, and
# the runner holds the shared DB admin password, a cluster-wide RBAC role and
# the dashboard's IAM role. So even with a repo URL and token in the env (the
# old participant-branch checkout knobs), a branch whose deploy script is
# hostile must never run: the bundled script must, and the bundled tree must be
# left exactly as it was.
#
# Builds a throwaway "bundled" repo plus a remote carrying a hostile branch;
# aws/kubectl are stubbed. Runs anywhere with bash, git and jq.
# ------------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENTRYPOINT="${ENTRYPOINT:-${SCRIPT_DIR}/entrypoint.sh}"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
nope() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }
has()    { if grep -qF -- "$2" <<<"$3"; then ok "$1"; else nope "$1 (missing '$2')"; fi; }
hasnt()  { if grep -qF -- "$2" <<<"$3"; then nope "$1 (found '$2')"; else ok "$1"; fi; }

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
export HOME="${TMP}/home" GIT_CONFIG_NOSYSTEM=1
mkdir -p "${HOME}" "${TMP}/bin"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

# ---- stubs -------------------------------------------------------------------
printf '#!/bin/sh\necho "{}"\n' > "${TMP}/bin/aws"
printf '#!/bin/sh\nexit 0\n' > "${TMP}/bin/kubectl"
chmod +x "${TMP}/bin/"*
export PATH="${TMP}/bin:${PATH}"

# ---- bundled tree (what the image ships) --------------------------------------
BUNDLED="${TMP}/workspace"
mkdir -p "${BUNDLED}/scripts/lib" "${BUNDLED}/demo-platform/lib"
cp "${ROOT}/scripts/lib/tenant-common.sh" "${BUNDLED}/scripts/lib/"
cp "${ROOT}/demo-platform/lib/control-common.sh" "${BUNDLED}/demo-platform/lib/"
for s in deploy-tenant inject-bug; do
  printf '#!/usr/bin/env bash\necho "BUNDLED-%s $*"\n' "${s}" > "${BUNDLED}/scripts/${s}.sh"
  chmod +x "${BUNDLED}/scripts/${s}.sh"
done
git -C "${BUNDLED}" init -q -b main
git -C "${BUNDLED}" add -A && git -C "${BUNDLED}" commit -qm bundled

# ---- remote with an attendee's hostile branch ---------------------------------
REMOTE="${TMP}/remote.git"
git clone -q --bare "${BUNDLED}" "${REMOTE}"
WORK="${TMP}/attacker"
git clone -q "${REMOTE}" "${WORK}"
git -C "${WORK}" checkout -q -b workshop-mallory
for s in deploy-tenant inject-bug; do
  printf '#!/usr/bin/env bash\necho "BRANCH-SCRIPT-RAN db=${DB_PASSWORD:-}"\nexit 1\n' > "${WORK}/scripts/${s}.sh"
done
git -C "${WORK}" commit -qam hostile && git -C "${WORK}" push -q origin workshop-mallory
git -C "${BUNDLED}" remote add origin "${REMOTE}"
BUNDLED_HEAD="$(git -C "${BUNDLED}" rev-parse HEAD)"

run() {
  env REPO_DIR="${BUNDLED}" KUBERNETES_SERVICE_HOST=stub \
      REPO_HTTPS_URL="file://${REMOTE}" GITHUB_TOKEN=test-token \
      DB_PASSWORD=s3cret TENANT_ID=mallory "$@" \
      bash "${ENTRYPOINT}" 2>&1
}

echo "runner executes only the bundled tree"

out="$(run OP=deploy TENANT_BRANCH=workshop-mallory)"; rc=$?
has   "deploy runs the bundled deploy-tenant.sh" "BUNDLED-deploy-tenant mallory" "${out}"
has   "  and passes the branch only as an image-tag label" "--branch workshop-mallory" "${out}"
hasnt "  and never the branch's deploy-tenant.sh" "BRANCH-SCRIPT-RAN" "${out}"
[ "${rc}" -eq 0 ] && ok "  and succeeds" || nope "  and succeeds (rc=${rc})"
[ "$(git -C "${BUNDLED}" rev-parse HEAD)" = "${BUNDLED_HEAD}" ] \
  && ok "  and leaves the bundled tree on its own commit" \
  || nope "  and leaves the bundled tree on its own commit"
git -C "${BUNDLED}" rev-parse -q --verify refs/remotes/origin/workshop-mallory >/dev/null \
  && nope "  and never fetches the tenant branch" || ok "  and never fetches the tenant branch"

out="$(run OP=inject SCENARIO=s3-upload-fail TENANT_BRANCH=workshop-mallory)"
has   "inject runs the bundled inject-bug.sh" "BUNDLED-inject-bug mallory s3-upload-fail" "${out}"
hasnt "  and never the branch's inject-bug.sh" "BRANCH-SCRIPT-RAN" "${out}"

echo "TENANT_BRANCH must be a tenant branch name"
for bad in "--upload-pack=touch /tmp/x" "feature/x" "workshop-a/../../etc" "workshop-" "main;id" "-main"; do
  out="$(run OP=deploy TENANT_BRANCH="${bad}")"; rc=$?
  if [ "${rc}" -ne 0 ] && ! grep -q "BUNDLED-deploy-tenant" <<<"${out}"; then
    ok "refuses '${bad}'"
  else
    nope "refuses '${bad}' (rc=${rc})"
  fi
done
for good in workshop-mallory demo-mallory workshop/mallory main; do
  out="$(run OP=deploy TENANT_BRANCH="${good}")"
  has "accepts '${good}'" "BUNDLED-deploy-tenant" "${out}"
done

echo
echo "${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
