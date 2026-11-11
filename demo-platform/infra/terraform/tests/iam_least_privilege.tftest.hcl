# Plans the control-plane stack offline and asserts the IAM grants stay least
# privilege. Policy documents are rendered by the real AWS provider (they are
# computed locally); everything that would need an AWS API call is overridden.
#
#   terraform init -backend=false && terraform test

provider "aws" {
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
}

override_data {
  target = data.aws_caller_identity.current
  values = {
    account_id = "111122223333"
  }
}

override_data {
  target = data.aws_eks_cluster.this
  values = {
    arn      = "arn:aws:eks:us-east-1:111122223333:cluster/otterworks-dev"
    identity = [{ oidc = [{ issuer = "https://oidc.eks.us-east-1.amazonaws.com/id/EXAMPLE" }] }]
  }
}

override_data {
  target = data.aws_route53_zone.demo
  values = {
    zone_id = "Z0DEMO"
  }
}

override_data {
  target = data.aws_iam_openid_connect_provider.github
  values = {
    arn = "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"
  }
}

override_resource {
  target = aws_dynamodb_table.control
  values = {
    arn = "arn:aws:dynamodb:us-east-1:111122223333:table/otterworks-demo-control"
  }
}

override_resource {
  target = aws_kms_key.control
  values = {
    arn = "arn:aws:kms:us-east-1:111122223333:key/control"
  }
}

override_resource {
  target = aws_kms_key.dashboard_passcode
  values = {
    arn = "arn:aws:kms:us-east-1:111122223333:key/passcode"
  }
}

override_resource {
  target = aws_secretsmanager_secret.dashboard_passcode
  values = {
    arn = "arn:aws:secretsmanager:us-east-1:111122223333:secret:otterworks/dev/dashboard/passcode"
  }
}

run "dashboard_irsa_trust_is_exact_service_roles" {
  command = plan

  assert {
    condition = alltrue([
      for s in jsondecode(data.aws_iam_policy_document.dashboard_iam_dns.json).Statement :
      alltrue([for r in flatten([s.Resource]) : !strcontains(r, ":role/") || !strcontains(r, "*")])
    ])
    error_message = "No dashboard statement may grant IAM role actions on a wildcard role ARN."
  }

  assert {
    condition = toset(flatten([
      for s in jsondecode(data.aws_iam_policy_document.dashboard_iam_dns.json).Statement :
      [flatten([s.Resource])] if s.Sid == "TenantIrsaTrust"
      ])) == toset([
      for svc in var.tenant_irsa_services : "arn:aws:iam::111122223333:role/otterworks-${svc}-dev"
    ])
    error_message = "TenantIrsaTrust must list exactly the per-service IRSA roles."
  }

  assert {
    condition = !contains(flatten([
      for s in jsondecode(data.aws_iam_policy_document.dashboard_iam_dns.json).Statement :
      [flatten([s.Resource])] if s.Sid == "TenantIrsaTrust"
    ]), "arn:aws:iam::111122223333:role/otterworks-demo-ops-dashboard-dev")
    error_message = "The dashboard role must not be able to rewrite its own trust policy."
  }
}

run "dashboard_route53_changes_are_tenant_deletes_in_demo_zone" {
  command = plan

  assert {
    condition = alltrue([
      for s in jsondecode(data.aws_iam_policy_document.dashboard_iam_dns.json).Statement :
      flatten([s.Resource]) == ["arn:aws:route53:::hostedzone/Z0DEMO"]
      if contains(flatten([s.Action]), "route53:ChangeResourceRecordSets")
    ])
    error_message = "route53:ChangeResourceRecordSets must be bound to the demo hosted zone only."
  }

  assert {
    condition = alltrue([
      for s in jsondecode(data.aws_iam_policy_document.dashboard_iam_dns.json).Statement :
      try(s.Condition["ForAllValues:StringEquals"]["route53:ChangeResourceRecordSetsActions"], null) == "DELETE"
      if contains(flatten([s.Action]), "route53:ChangeResourceRecordSets")
    ])
    error_message = "route53:ChangeResourceRecordSets must be limited to DELETE."
  }

  assert {
    condition = alltrue([
      for s in jsondecode(data.aws_iam_policy_document.dashboard_iam_dns.json).Statement :
      alltrue([
        for p in flatten([s.Condition["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"]]) :
        can(regex("^(cname-|txt-)?(api-)?t-\\*\\.otterworks\\.app$", p))
      ])
      if contains(flatten([s.Action]), "route53:ChangeResourceRecordSets")
    ])
    error_message = "Route53 changes must be limited to tenant record names in the demo zone."
  }

  assert {
    condition = length([
      for s in jsondecode(data.aws_iam_policy_document.dashboard_iam_dns.json).Statement : s
      if contains(flatten([s.Action]), "route53:ChangeResourceRecordSets")
    ]) == 1
    error_message = "Expected exactly one Route53 change statement when DNS is enabled."
  }
}

run "dashboard_route53_changes_absent_without_dns" {
  command = plan

  variables {
    enable_dns = false
  }

  assert {
    condition = length([
      for s in jsondecode(data.aws_iam_policy_document.dashboard_iam_dns.json).Statement : s
      if contains(flatten([s.Action]), "route53:ChangeResourceRecordSets")
    ]) == 0
    error_message = "Without a demo zone the dashboard must hold no Route53 change permission."
  }
}

run "github_actions_role_cannot_read_dashboard_passcode" {
  command = plan

  assert {
    condition = length([
      for s in jsondecode(data.aws_iam_policy_document.github_actions[0].json).Statement : s
      if length([
        for a in flatten([s.Action]) : a
        if startswith(a, "secretsmanager:") || startswith(a, "kms:")
      ]) > 0
    ]) == 0
    error_message = "The branch-trusted CD role must hold no Secrets Manager or KMS access (dashboard passcode)."
  }

  assert {
    condition = alltrue([
      for s in jsondecode(data.aws_iam_policy_document.github_actions[0].json).Statement :
      alltrue([for a in flatten([s.Action]) : startswith(a, "ecr:")])
    ])
    error_message = "The CD role should hold ECR permissions only."
  }
}
