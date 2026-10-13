#!/usr/bin/env bash
# CRITICAL/HIGH gate over `trivy image --format json` reports.
#
#   trivy-gate.sh --head <report.json> [--head ...] [--base <report.json> ...]
#
# With no --base the gate is absolute: any finding fails it. With --base it
# fails only on findings present in the head image and absent from the base
# image (the same policy security-scan.yml applies to the source tree), so a PR
# is never blocked by CVEs that were already shipping on main. Findings Trivy
# suppressed through .trivyignore never reach the report and so never gate.
#
# A finding's identity is (target, package, vulnerability). OS-package targets
# are keyed by distro family instead of Trivy's target string, which embeds the
# scanned path and the exact OS point release.
set -euo pipefail

heads=() bases=()
while [ $# -gt 0 ]; do
  case "$1" in
    --head) heads+=("$2"); shift 2 ;;
    --base) bases+=("$2"); shift 2 ;;
    *) echo "trivy-gate: unknown argument $1" >&2; exit 2 ;;
  esac
done
[ "${#heads[@]}" -gt 0 ] || { echo "trivy-gate: at least one --head report is required" >&2; exit 2; }

findings() {
  jq -r '
    .Results[]? | (if .Class == "os-pkgs" then "os:" + .Type else .Target end) as $t |
    .Vulnerabilities[]? | select(.Severity == "CRITICAL" or .Severity == "HIGH") |
    [$t, .PkgName, .VulnerabilityID, .Severity, .InstalledVersion, (.FixedVersion // "no fix")] | @tsv
  ' "$@" | sort -u
}

tmp="$(mktemp -d)"; trap 'rm -rf "${tmp}"' EXIT
findings "${heads[@]}" > "${tmp}/head.tsv"
cut -f1-3 "${tmp}/head.tsv" | sort -u > "${tmp}/head.keys"
if [ "${#bases[@]}" -gt 0 ]; then
  findings "${bases[@]}" | cut -f1-3 | sort -u > "${tmp}/base.keys"
  mode="new vs base"
else
  : > "${tmp}/base.keys"
  mode="absolute"
fi
comm -23 "${tmp}/head.keys" "${tmp}/base.keys" > "${tmp}/new.keys"

total="$(wc -l < "${tmp}/head.keys")"
new="$(wc -l < "${tmp}/new.keys")"
echo "trivy-gate (${mode}): ${total} CRITICAL/HIGH finding(s) in head, ${new} gating"

if [ "${new}" -gt 0 ]; then
  awk -F'\t' 'NR==FNR { k[$1 FS $2 FS $3]; next } ($1 FS $2 FS $3) in k {
    printf "  %-9s %-20s %s %s %s -> %s\n", $4, $3, $1, $2, $5, $6 }' \
    "${tmp}/new.keys" "${tmp}/head.tsv"
  exit 1
fi
