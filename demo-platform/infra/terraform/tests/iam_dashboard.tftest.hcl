# Plan-only checks on the control-plane IRSA role policy. The AWS provider is
# mocked, so this needs no credentials and touches no account:
#   terraform init -backend=false && terraform test

mock_provider "aws" {
  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
    }
  }

  override_data {
    target = data.aws_eks_cluster.this
    values = {
      arn = "arn:aws:eks:us-east-1:123456789012:cluster/otterworks-dev"
      identity = [{
        oidc = [{ issuer = "https://oidc.eks.us-east-1.amazonaws.com/id/EXAMPLE" }]
      }]
    }
  }
}

run "tenant_irsa_trust_names_only_the_per_service_roles" {
  command = plan

  assert {
    condition = one([
      for s in data.aws_iam_policy_document.dashboard.statement : s.resources
      if s.sid == "TenantIrsaTrust"
      ]) == toset([
      for svc in [
        "api-gateway", "auth-service", "file-service", "document-service", "search-service",
        "collab-service", "notification-service", "audit-service", "analytics-service",
        "admin-service",
      ] : "arn:aws:iam::123456789012:role/otterworks-${svc}-dev"
    ])
    error_message = "TenantIrsaTrust must list exactly the otterworks-<svc>-<env> IRSA role ARNs."
  }

  assert {
    condition = alltrue(flatten([
      for s in data.aws_iam_policy_document.dashboard.statement : [
        for r in s.resources : !strcontains(r, "*") && !strcontains(r, "?")
      ] if contains(s.actions, "iam:UpdateAssumeRolePolicy") || contains(s.actions, "iam:GetRole")
    ]))
    error_message = "iam:GetRole / iam:UpdateAssumeRolePolicy must never be granted on a wildcard role ARN."
  }

  assert {
    condition = length(setintersection(
      toset(flatten([
        for s in data.aws_iam_policy_document.dashboard.statement : tolist(s.resources)
        if contains(s.actions, "iam:UpdateAssumeRolePolicy")
      ])),
      toset([
        for name in [
          "otterworks-eks-cluster-dev", "otterworks-eks-nodes-dev", "otterworks-karpenter-dev",
          "otterworks-ebs-csi-driver-dev", "otterworks-github-actions", "otterworks-demo-dns-dev",
          "otterworks-demo-ops-dashboard-dev",
        ] : "arn:aws:iam::123456789012:role/${name}"
      ])
    )) == 0
    error_message = "The control plane must not be able to rewrite the trust of platform roles or its own role."
  }

  assert {
    condition = anytrue(flatten([
      for s in data.aws_iam_policy_document.dashboard.statement : [
        for c in s.condition : c.test == "StringEquals" && c.variable == "aws:ResourceTag/Module" && toset(c.values) == toset(["irsa"])
      ] if s.sid == "TenantIrsaTrust"
    ]))
    error_message = "TenantIrsaTrust must require the irsa module's Module=irsa role tag."
  }
}

run "tenant_irsa_services_rejects_wildcards" {
  command = plan

  variables {
    tenant_irsa_services = ["file-service", "*"]
  }

  expect_failures = [var.tenant_irsa_services]
}

run "tenant_irsa_services_rejects_platform_roles" {
  command = plan

  variables {
    tenant_irsa_services = ["file-service", "karpenter"]
  }

  expect_failures = [var.tenant_irsa_services]
}
