#!/usr/bin/env bash
# Static assertion that every OtterWorks image repository in ECR is declared
# with scan-on-push. Reads Terraform only -- no AWS credentials, no plan/apply.
#
#   assert-ecr-scan-on-push.sh [terraform-dir] [release-workflow]
#
# Runs checkov's CKV_AWS_163 ("ECR image scanning on push is enabled") over the
# Terraform root, so module for_each expansions are evaluated, then checks that
# (a) nothing failed or failed to parse, and (b) every image the release
# workflow publishes has a repository that passed. (b) matters because checkov
# passes vacuously when a repository resource is deleted or renamed.
set -euo pipefail

tf_dir="${1:-platform/terraform}"
workflow="${2:-.github/workflows/docker-build.yml}"

report="$(mktemp)"; trap 'rm -f "${report}"' EXIT
# checkov exits non-zero on a failed check; the report is authoritative.
checkov -d "${tf_dir}" --framework terraform --check CKV_AWS_163 \
  --output json > "${report}" || true

# checkov prints [] (or a summary with no results key) when nothing matched.
jq -e 'type == "object" and has("summary")' "${report}" > /dev/null || {
  echo "::error::checkov found no aws_ecr_repository resources under ${tf_dir}"
  exit 1
}

failed="$(jq '.summary.failed' "${report}")"
parse_errors="$(jq '.summary.parsing_errors' "${report}")"
if [ "${failed}" != 0 ] || [ "${parse_errors}" != 0 ]; then
  jq -r '.results.failed_checks[]? | "::error file=\(.repo_file_path)::\(.resource) does not enable scan_on_push (\(.check_id))"' "${report}"
  [ "${parse_errors}" = 0 ] || echo "::error::checkov could not parse ${parse_errors} Terraform file(s)"
  exit 1
fi

mapfile -t passed < <(jq -r '.results.passed_checks[]?.resource' "${report}" |
  sed -n 's/.*aws_ecr_repository\.[A-Za-z0-9_-]*\["\([^"]*\)"\].*/\1/p' | sort -u)
mapfile -t images < <(sed -n 's/.*{ *name: *\([A-Za-z0-9_-]*\), *context:.*/\1/p' "${workflow}" | sort -u)
[ "${#images[@]}" -gt 0 ] || { echo "::error::no images found in ${workflow} matrix"; exit 1; }

missing="$(comm -23 <(printf '%s\n' "${images[@]}") <(printf '%s\n' "${passed[@]}"))"
if [ -n "${missing}" ]; then
  while read -r image; do
    echo "::error::no ECR repository with scan_on_push found for published image '${image}'"
  done <<< "${missing}"
  exit 1
fi

echo "ECR scan-on-push: ${#passed[@]} repositories pass CKV_AWS_163, covering all ${#images[@]} published images."
