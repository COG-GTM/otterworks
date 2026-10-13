# Offline plan against mocked providers: proves the control plane plans
# without AWS credentials.
#   terraform init -backend=false
#   terraform test -var-file=environments/dev.tfvars
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
      arn = "arn:aws:iam::123456789012:oidc-provider/oidc.eks.us-east-1.amazonaws.com/id/TEST"
      url = "oidc.eks.us-east-1.amazonaws.com/id/TEST"
    }
  }
}

run "plan" {
  command = plan

  assert {
    condition     = !var.enable_github_actions_role || length(var.github_actions_trusted_repos) > 0
    error_message = "GitHub Actions role enabled without trusted repos"
  }
}
