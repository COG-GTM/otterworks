#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Unit tests for image-tag validation on the runner's deploy path.
#
# IMAGE_TAG comes from the dashboard API and ends up in `helm --set-string
# image.tag=...`. Helm reads `,` `=` `[` `]` `\` as its own syntax, so a tag
# like `x,image.repository=evil/img` would set extra chart values on every
# service in the tenant. These tests pin the grammar and check that both scripts
# refuse a bad tag before helm runs.
#
# kubectl / helm are stubbed; this runs anywhere.
# ------------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
nope() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }

# shellcheck source=../../scripts/lib/tenant-common.sh
source "${REPO_ROOT}/scripts/lib/tenant-common.sh"

echo "valid_image_tag"
for tag in main tenant-derek workshop-derek-abc1234 v1.2.3 _x A_b.c-d "$(printf 'a%.0s' $(seq 128))"; do
  if valid_image_tag "${tag}"; then ok "accepts '${tag:0:40}'"; else nope "accepts '${tag:0:40}'"; fi
done
for tag in "" "x,image.repository=evil/img" "a=b" "a[0]" "a]" 'a\b' "-x" ".x" "a b" "a/b" "a:b" \
           $'a\nb' "$(printf 'a%.0s' $(seq 129))"; do
  if valid_image_tag "${tag}"; then nope "rejects '${tag:0:40}'"; else ok "rejects '${tag:0:40}'"; fi
done

# ---- stubs -------------------------------------------------------------------
STUB_DIR="$(mktemp -d)"
trap 'rm -rf "${STUB_DIR}"' EXIT
HELM_LOG="${STUB_DIR}/helm.log"
cat > "${STUB_DIR}/helm" <<STUB
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "${HELM_LOG}"
STUB
printf '#!/usr/bin/env bash\nexit 0\n' > "${STUB_DIR}/kubectl"
chmod +x "${STUB_DIR}/helm" "${STUB_DIR}/kubectl"
export PATH="${STUB_DIR}:${PATH}"

echo "deploy-tenant.sh"
: > "${HELM_LOG}"
if out="$("${REPO_ROOT}/scripts/deploy-tenant.sh" derek --image-tag 'x,image.repository=evil/img' 2>&1)"; then
  nope "rejects an injected --image-tag"
else
  case "${out}" in *"--image-tag must match"*) ok "rejects an injected --image-tag" ;;
                   *) nope "rejects an injected --image-tag (got: ${out})" ;; esac
fi
if [ -s "${HELM_LOG}" ]; then nope "helm not run for a bad tag"; else ok "helm not run for a bad tag"; fi
if grep -nE -- '--set image\.(tag|repository)' "${REPO_ROOT}/scripts/deploy-tenant.sh" "${REPO_ROOT}/scripts/inject-bug.sh"; then
  nope "image values are passed with --set-string"
else
  ok "image values are passed with --set-string"
fi

echo "inject-bug.sh code-variant"
: > "${HELM_LOG}"
if "${REPO_ROOT}/scripts/inject-bug.sh" derek code-variant --image-tag 'x,serviceAccount.roleArn=arn' >/dev/null 2>&1; then
  nope "rejects an injected --image-tag"
else
  ok "rejects an injected --image-tag"
fi
if [ -s "${HELM_LOG}" ]; then nope "helm not run for a bad tag"; else ok "helm not run for a bad tag"; fi

: > "${HELM_LOG}"
if "${REPO_ROOT}/scripts/inject-bug.sh" derek code-variant --image-tag variant-abc1234 >/dev/null 2>&1 &&
   grep -q -- '--set-string image.tag=variant-abc1234$' "${HELM_LOG}"; then
  ok "valid tag reaches helm via --set-string"
else
  nope "valid tag reaches helm via --set-string (helm: $(cat "${HELM_LOG}"))"
fi

echo
echo "${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
