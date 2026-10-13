# Plan/apply role trust (iam_terraform_ci.tf): off by default, narrowly scoped when on.
mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_eks_cluster" {
    defaults = {
      identity = [{ oidc = [{ issuer = "https://oidc.eks.us-east-1.amazonaws.com/id/TEST" }] }]
    }
  }
  mock_data "aws_iam_openid_connect_provider" {
    defaults = {
      arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
      url = "token.actions.githubusercontent.com"
    }
  }
}

run "terraform_ci_roles_off_by_default" {
  command = plan

  assert {
    condition     = length(aws_iam_role.terraform_plan) == 0 && length(aws_iam_role.terraform_apply) == 0
    error_message = "Terraform CI roles must not be created unless terraform_ci_trusted_repos is set"
  }
}

run "terraform_ci_roles_scoped_when_enabled" {
  command = plan

  variables {
    terraform_ci_trusted_repos = ["COG-GTM/otterworks"]
  }

  assert {
    condition     = local.terraform_plan_subjects == ["repo:COG-GTM/otterworks:pull_request", "repo:COG-GTM/otterworks:ref:refs/heads/main"]
    error_message = "Plan role trust must be same-repo PRs and main only"
  }

  assert {
    condition     = local.terraform_apply_subjects == ["repo:COG-GTM/otterworks:environment:terraform-*"]
    error_message = "Apply role trust must be limited to terraform-* GitHub Environments"
  }
}
