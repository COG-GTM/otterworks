#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Image-tag validation on the runner -> deploy-tenant.sh -> helm path.
#
# The tag ends up in `helm --set image.tag=...`, and Helm splits --set on `,`,
# so `v1,image.repository=evil/x` would also replace the image repository. Every
# entry point must reject such a tag before it reaches AWS, kubectl or Helm.
#
# aws / kubectl / helm / terraform are stubbed and record their calls; this
# runs anywhere.
# ------------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
nope() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else nope "$1 (expected '$3', got '$2')"; fi; }

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
mkdir -p "${WORK}/bin"
cat > "${WORK}/bin/stub" <<'STUB'
#!/usr/bin/env bash
printf '%s' "$(basename "$0")" >> "${STUB_LOG}"
printf ' %q' "$@" >> "${STUB_LOG}"
echo >> "${STUB_LOG}"
case "$(basename "$0") ${1:-} ${2:-}" in
  "aws sts "*) echo 123456789012 ;;
  "aws ecr describe-images") echo main ;;
esac
exit 0
STUB
chmod +x "${WORK}/bin/stub"
for b in aws kubectl helm terraform psql; do ln -s stub "${WORK}/bin/${b}"; done
export STUB_LOG="${WORK}/calls.log"
export PATH="${WORK}/bin:${PATH}"

# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/lib/tenant-common.sh"

echo "valid_image_tag"
for tag in v1 main tenant-derek demo-x-abc1234 1.2.3 _x "$(printf 'a%.0s' {1..128})"; do
  if valid_image_tag "${tag}"; then ok "accepts '${tag:0:40}'"; else nope "accepts '${tag:0:40}'"; fi
done
for tag in "" "v1,image.repository=evil/x" "a=b" "a[0]" "a{b}" "a b" ".x" "-x" \
           "v1 --set x=y" "a/b" "a:b" "$(printf 'a%.0s' {1..129})" $'v1\nx'; do
  if valid_image_tag "${tag}"; then nope "rejects '${tag:0:40}'"; else ok "rejects '${tag:0:40}'"; fi
done

BAD="v1,image.repository=registry.example/evil"

run_deploy() {
  : > "${STUB_LOG}"
  DB_PASSWORD=x AWS_ACCOUNT_ID=123456789012 TENANT_PROFILE=core \
    "${REPO_ROOT}/scripts/deploy-tenant.sh" derek --skip-db "$@" >"${WORK}/out.log" 2>&1
}

echo "deploy-tenant.sh"
run_deploy --image-tag "${BAD}"
check "--image-tag with a comma exits non-zero" "$?" "1"
check "... before any aws/kubectl/helm call" "$(wc -l < "${STUB_LOG}" | tr -d ' ')" "0"

run_deploy --image-tag v1
check "--image-tag v1 deploys" "$?" "0"
check "... passes the tag with --set-string" \
  "$(grep -c -- '--set-string image.tag=v1 ' "${STUB_LOG}")" "$(grep -c '^helm upgrade' "${STUB_LOG}")"
check "... and never with plain --set" "$(grep -c -- '--set image.tag=' "${STUB_LOG}")" "0"

BUG_IMAGE_TAG_web_app="${BAD}" run_deploy
check "BUG_IMAGE_TAG_web_app with a comma: no helm upgrade for web-app" \
  "$(grep -c '^helm upgrade --install web-app ' "${STUB_LOG}")" "0"
check "... other services still deploy" "$(grep -c '^helm upgrade --install api-gateway ' "${STUB_LOG}")" "1"
check "... and nothing receives the injected repository" "$(grep -c 'registry.example' "${STUB_LOG}")" "0"

echo "inject-bug.sh"
: > "${STUB_LOG}"
"${REPO_ROOT}/scripts/inject-bug.sh" derek code-variant --image-tag "${BAD}" >"${WORK}/out.log" 2>&1
check "code-variant with a comma exits non-zero" "$?" "1"
check "... without calling helm" "$(grep -c '^helm' "${STUB_LOG}")" "0"

echo "runner entrypoint"
: > "${STUB_LOG}"
OP=deploy TENANT_ID=derek DB_PASSWORD=x REPO_DIR="${REPO_ROOT}" IMAGE_TAG="${BAD}" \
  KUBERNETES_SERVICE_HOST=stub "${REPO_ROOT}/demo-platform/runner/entrypoint.sh" >"${WORK}/out.log" 2>&1
check "OP=deploy with a comma in IMAGE_TAG exits non-zero" "$?" "1"
check "... before any status write or deploy" "$(wc -l < "${STUB_LOG}" | tr -d ' ')" "0"

echo "${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
