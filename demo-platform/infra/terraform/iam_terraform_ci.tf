# Identities for the Terraform workflows (.github/workflows/terraform-*.yml).
#
# NOT CREATED BY DEFAULT: terraform_ci_trusted_repos is empty, so applying this
# root as-is creates nothing and trusts nobody. Populating it is a reviewed
# trust change -- see docs/IAC.md "Enabling plan/apply".
#
#   otterworks-terraform-plan   read-only; assumed by PR plans, drift detection
#                               and the plan half of terraform-apply.yml
#   otterworks-terraform-apply  full access; assumable ONLY from a job bound to
#                               a GitHub Environment named terraform-<env>, which
#                               is where required reviewers are enforced
#
# Kept separate from otterworks-github-actions (CD): that role is ref-scoped to
# workshop-*/demo-* on this fork and must stay narrow.

locals {
  terraform_ci_enabled = length(var.terraform_ci_trusted_repos) > 0

  # Same-repository PRs and main. GitHub never issues an OIDC token to a PR from
  # a fork, so `pull_request` does not extend to forked code.
  terraform_plan_subjects = flatten([
    for repo in var.terraform_ci_trusted_repos :
    ["repo:${repo}:pull_request", "repo:${repo}:ref:refs/heads/main"]
  ])

  terraform_apply_subjects = [
    for repo in var.terraform_ci_trusted_repos : "repo:${repo}:environment:terraform-*"
  ]
}

data "aws_iam_openid_connect_provider" "github_terraform" {
  count = local.terraform_ci_enabled ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "terraform_plan_trust" {
  count = local.terraform_ci_enabled ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github_terraform[0].arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = local.terraform_plan_subjects
    }
  }
}

resource "aws_iam_role" "terraform_plan" {
  count = local.terraform_ci_enabled ? 1 : 0

  name                 = "otterworks-terraform-plan"
  description          = "Terraform plan / drift detection from GitHub Actions (read-only)"
  assume_role_policy   = data.aws_iam_policy_document.terraform_plan_trust[0].json
  max_session_duration = 3600

  tags = {
    Purpose = "Terraform plan and drift detection"
  }
}

resource "aws_iam_role_policy_attachment" "terraform_plan_readonly" {
  count = local.terraform_ci_enabled ? 1 : 0

  role       = aws_iam_role.terraform_plan[0].name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# ReadOnlyAccess reads every bucket and table. A plan needs the state bucket,
# resource metadata, and the data of resources Terraform itself manages (it
# refreshes them), so data-plane reads are denied everywhere else.
#
# The state objects already hold every managed secret, so this role is a state
# reader by design. Its trust is limited to same-repo PRs and main, i.e. people
# with write access to the repository. See docs/IAC.md.
data "aws_iam_policy_document" "terraform_plan_guard" {
  count = local.terraform_ci_enabled ? 1 : 0

  statement {
    sid    = "DenyUnmanagedTableReads"
    effect = "Deny"
    actions = [
      "dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query", "dynamodb:Scan",
    ]
    not_resources = ["arn:aws:dynamodb:*:*:table/${var.control_table_name}"]
  }

  statement {
    sid           = "DenyUnmanagedSecretReads"
    effect        = "Deny"
    actions       = ["secretsmanager:GetSecretValue", "ssm:GetParameter*"]
    not_resources = ["arn:aws:secretsmanager:*:*:secret:otterworks/*"]
  }

  statement {
    sid           = "DenyObjectReadsOutsideState"
    effect        = "Deny"
    actions       = ["s3:GetObject*"]
    not_resources = ["arn:aws:s3:::${var.terraform_state_bucket}/*"]
  }
}

resource "aws_iam_role_policy" "terraform_plan_guard" {
  count = local.terraform_ci_enabled ? 1 : 0

  name   = "deny-data-plane-reads"
  role   = aws_iam_role.terraform_plan[0].id
  policy = data.aws_iam_policy_document.terraform_plan_guard[0].json
}

data "aws_iam_policy_document" "terraform_apply_trust" {
  count = local.terraform_ci_enabled ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github_terraform[0].arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = local.terraform_apply_subjects
    }
  }
}

resource "aws_iam_role" "terraform_apply" {
  count = local.terraform_ci_enabled ? 1 : 0

  name                 = "otterworks-terraform-apply"
  description          = "Terraform apply from a reviewer-gated GitHub Environment"
  assume_role_policy   = data.aws_iam_policy_document.terraform_apply_trust[0].json
  max_session_duration = 3600

  tags = {
    Purpose = "Terraform apply"
  }
}

resource "aws_iam_role_policy_attachment" "terraform_apply_admin" {
  #checkov:skip=CKV_AWS_274:Terraform manages IAM, EKS, VPC and RDS across three roots; the guard is the environment-scoped trust plus required reviewers, not the permission set.
  count = local.terraform_ci_enabled ? 1 : 0

  role       = aws_iam_role.terraform_apply[0].name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
