# Policy-shape checks for the dashboard/runner IRSA role. Runs entirely against
# a mocked AWS provider: `terraform init -backend=false && terraform test`.

mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }

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

  override_data {
    target = data.aws_route53_zone.demo
    values = {
      zone_id = "Z0DEMOZONE"
    }
  }
}

run "route53_record_changes_scoped_to_demo_zone_tenant_deletes" {
  command = apply

  assert {
    condition = alltrue([
      for s in data.aws_iam_policy_document.dashboard.statement :
      !contains(s.resources, "*") || length(setintersection(s.actions, [
        "route53:ChangeResourceRecordSets", "route53:ListResourceRecordSets",
      ])) == 0
    ])
    error_message = "No dashboard statement may grant Route53 record reads or changes on \"*\"."
  }

  assert {
    condition = toset(flatten([
      for s in data.aws_iam_policy_document.dashboard.statement :
      s.resources if contains(s.actions, "route53:ChangeResourceRecordSets")
    ])) == toset(["arn:aws:route53:::hostedzone/Z0DEMOZONE"])
    error_message = "route53:ChangeResourceRecordSets must be granted only on the demo hosted zone."
  }

  assert {
    condition = alltrue([
      for s in data.aws_iam_policy_document.dashboard.statement :
      anytrue([
        for c in s.condition :
        c.test == "ForAllValues:StringEquals" && c.variable == "route53:ChangeResourceRecordSetsActions" && toset(c.values) == toset(["DELETE"])
      ]) if contains(s.actions, "route53:ChangeResourceRecordSets")
    ])
    error_message = "Record changes must be limited to DELETE."
  }

  assert {
    condition = alltrue([
      for s in data.aws_iam_policy_document.dashboard.statement :
      anytrue([
        for c in s.condition :
        c.test == "ForAllValues:StringLike" && c.variable == "route53:ChangeResourceRecordSetsNormalizedRecordNames" && toset(c.values) == toset([
          "t-*.demo.otterworks.app", "api-t-*.demo.otterworks.app",
          "cname-t-*.demo.otterworks.app", "cname-api-t-*.demo.otterworks.app",
          "txt-t-*.demo.otterworks.app", "txt-api-t-*.demo.otterworks.app",
        ])
      ]) if contains(s.actions, "route53:ChangeResourceRecordSets")
    ])
    error_message = "Record changes must be limited to tenant record names under tenant_host_suffix."
  }
}

run "no_route53_record_changes_without_dns" {
  command = apply

  variables {
    enable_dns = false
  }

  assert {
    condition = alltrue([
      for s in data.aws_iam_policy_document.dashboard.statement :
      !contains(s.actions, "route53:ChangeResourceRecordSets")
    ])
    error_message = "With enable_dns off there is no zone, so no record changes may be granted."
  }
}
