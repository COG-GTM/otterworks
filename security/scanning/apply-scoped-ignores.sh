#!/usr/bin/env bash
# Removes the findings listed in trivy-scoped-ignores.json from a Trivy JSON report,
# in place. A finding is dropped only when target, package, installed version and
# vulnerability id all match, so the same CVE anywhere else (or a different
# vulnerable version in the same file) is still reported.
#
#   bash security/scanning/apply-scoped-ignores.sh trivy.json
set -euo pipefail

report="${1:?usage: apply-scoped-ignores.sh <trivy-report.json>}"
config="${SCOPED_IGNORES:-$(dirname "${BASH_SOURCE[0]}")/trivy-scoped-ignores.json}"

# shellcheck disable=SC2016  # jq variables, not shell expansions
match='any($ign[]; .target == $t and .pkg == $v.PkgName
                  and .version == $v.InstalledVersion and .id == $v.VulnerabilityID)'

jq -r --slurpfile cfg "$config" "
  \$cfg[0].ignores as \$ign | .Results[]? | .Target as \$t | .Vulnerabilities[]? |
  . as \$v | select($match) |
  \"Suppressed (scoped ignore): \(.VulnerabilityID) \(.Severity) \(\$t) \(.PkgName) \(.InstalledVersion)\"
" "$report"

tmp="$(mktemp)"
jq --slurpfile cfg "$config" "
  \$cfg[0].ignores as \$ign |
  if .Results then
    .Results |= map(.Target as \$t |
      if .Vulnerabilities then
        .Vulnerabilities |= map(. as \$v | select($match | not))
      else . end)
  else . end
" "$report" > "$tmp"
mv "$tmp" "$report"
