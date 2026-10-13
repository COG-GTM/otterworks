#!/usr/bin/env bash
# Offline static checks for every Terraform root: fmt, init (no backend),
# validate, tflint, checkov and the mocked per-environment plan tests.
# No AWS credentials are needed or used. Same checks as
# .github/workflows/terraform-static.yml.
#
#   scripts/terraform-check.sh                  # all roots
#   scripts/terraform-check.sh platform/terraform
#   SKIP_CHECKOV=1 SKIP_TESTS=1 scripts/terraform-check.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOTS=("platform/terraform" "infrastructure/terraform" "demo-platform/infra/terraform")
[[ $# -gt 0 ]] && ROOTS=("$@")

need() { command -v "$1" >/dev/null || { echo "missing tool: $1" >&2; exit 2; }; }
need terraform
[[ -n "${SKIP_TFLINT:-}" ]] || need tflint
[[ -n "${SKIP_CHECKOV:-}" ]] || need checkov

[[ -n "${SKIP_TFLINT:-}" ]] || tflint --init --config="$REPO_ROOT/.tflint.hcl" >/dev/null

fail=0
step() { echo "--- $*"; }
for root in "${ROOTS[@]}"; do
  dir="$REPO_ROOT/$root"
  echo "=== $root"
  step "terraform fmt -check"
  terraform -chdir="$dir" fmt -check -recursive -diff || fail=1
  step "terraform init -backend=false"
  terraform -chdir="$dir" init -backend=false -input=false -no-color >/dev/null
  step "terraform validate"
  terraform -chdir="$dir" validate -no-color || fail=1
  if [[ -z "${SKIP_TFLINT:-}" ]]; then
    step "tflint"
    tflint --chdir="$dir" --config="$REPO_ROOT/.tflint.hcl" --format=compact || fail=1
  fi
  if [[ -z "${SKIP_CHECKOV:-}" ]]; then
    step "checkov"
    checkov -d "$dir" --framework terraform --quiet --compact \
      --config-file "$REPO_ROOT/.checkov.yaml" || fail=1
  fi
  if [[ -z "${SKIP_TESTS:-}" ]]; then
    for tfvars in "$dir"/environments/*.tfvars; do
      env="$(basename "$tfvars" .tfvars)"
      step "terraform test (mocked plan) env=$env"
      terraform -chdir="$dir" test -no-color -var-file="environments/$env.tfvars" || fail=1
    done
  fi
done

if [[ $fail -ne 0 ]]; then
  echo "Terraform checks FAILED" >&2
  exit 1
fi
echo "All Terraform checks passed"
