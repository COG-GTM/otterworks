#!/usr/bin/env bash
# enable-tenant-irsa-wildcard.sh — make per-tenant IRSA scale to high tens.
#
# The shared per-service IAM roles (otterworks-<svc>-<env>) trust each namespace
# service account via an EXACT-match (StringEquals) statement. deploy-tenant.sh
# adds one per tenant, so at high-tens the trust document hits IAM's ~4KB cap and
# deploys start failing. This script adds ONE StringLike wildcard statement per
# role — system:serviceaccount:otterworks-*:<svc> — that covers every current and
# future tenant namespace. deploy-tenant.sh already detects this wildcard and
# then skips per-tenant trust edits entirely (no IAM churn, no bloat).
#
# The golden app's own namespace is `otterworks` (no hyphen), which the
# `otterworks-*` glob does NOT match, so its existing exact statement is left in
# place. Idempotent: re-running makes no change once the wildcard is present.
#
# Usage: ENV=dev ./enable-tenant-irsa-wildcard.sh
# Requires: aws, jq, and IAM perms iam:GetRole + iam:UpdateAssumeRolePolicy on
# the per-service roles below (the dashboard IRSA role has these for exactly the
# roles in tenant_irsa_services, demo-platform/infra/terraform/variables.tf).
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENV:-dev}"
CLUSTER="${EKS_CLUSTER:-otterworks-dev}"

# Service roles that back the app (must match the irsa module role names and
# tenant_irsa_services in demo-platform/infra/terraform/variables.tf).
# web-app/admin-dashboard are frontends with no IRSA role, so they're omitted.
SERVICES=(
  api-gateway auth-service file-service document-service search-service
  collab-service notification-service audit-service analytics-service
  admin-service
)

command -v jq >/dev/null || { echo "jq required" >&2; exit 1; }

oidc_url="$(aws eks describe-cluster --name "${CLUSTER}" --region "${AWS_REGION}" \
  --query 'cluster.identity.oidc.issuer' --output text 2>/dev/null || echo "")"
oidc_url="${oidc_url#https://}"
[ -n "${oidc_url}" ] || { echo "could not resolve OIDC issuer for ${CLUSTER}" >&2; exit 1; }

pattern_prefix="system:serviceaccount:otterworks-*"

for svc in "${SERVICES[@]}"; do
  role="otterworks-${svc}-${ENVIRONMENT}"
  sub="${pattern_prefix}:${svc}"
  doc="$(aws iam get-role --role-name "${role}" \
    --query 'Role.AssumeRolePolicyDocument' --output json 2>/dev/null || echo "")"
  [ -n "${doc}" ] || { echo "  skip: role ${role} not found"; continue; }

  # Already has a StringLike wildcard for this sub?
  have="$(echo "${doc}" | jq -r --arg url "${oidc_url}" --arg sub "${sub}" '
    [ .Statement[]?.Condition.StringLike[$url+":sub"]
      | select(. != null)
      | if type=="array" then .[] else . end ]
    | index($sub) | if . == null then "no" else "yes" end')"
  if [ "${have}" = "yes" ]; then
    echo "  ok: ${role} already trusts ${sub}"
    continue
  fi

  new="$(echo "${doc}" | jq --arg sub "${sub}" --arg url "${oidc_url}" '
    .Statement += [{
      Effect: "Allow",
      Action: "sts:AssumeRoleWithWebIdentity",
      Principal: (.Statement[0].Principal),
      Condition: {
        StringLike:   { ($url+":sub"): $sub },
        StringEquals: { ($url+":aud"): "sts.amazonaws.com" }
      }
    }]')"
  aws iam update-assume-role-policy --role-name "${role}" \
    --policy-document "${new}" >/dev/null
  echo "  updated: ${role} now trusts ${sub}"
done

echo "done."
