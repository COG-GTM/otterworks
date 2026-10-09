# The identity GitHub Actions uses to ship tenant environments.
#
# Continuous delivery needs to do two things: push service images to ECR, and
# tell the Demo Ops dashboard to redeploy the tenant that owns the branch. Only
# the first needs AWS: the second authenticates to the dashboard with the job's
# own GitHub OIDC token (dashboard lib/cdauth.ts), which yields a session bound
# to that branch's tenant. This role deliberately gets no more than ECR -- no
# EKS, no RDS, no control-table writes, and no dashboard passcode, because the
# passcode is a facilitator credential over every tenant and any branch this
# role trusts runs a workflow its pusher wrote.
#
# Federated (OIDC) rather than an IAM user: a workflow exchanges a short-lived
# GitHub token for equally short-lived AWS credentials, so there is no static
# key to leak, store in a repo secret, or rotate.

data "aws_iam_openid_connect_provider" "github" {
  count = var.enable_github_actions_role ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "github_actions_trust" {
  count = var.enable_github_actions_role ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github[0].arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Ref-scoped, not `repo:<org>/<repo>:*`. The wildcard form would let any
    # branch -- including one pushed by a workshop attendee with write access --
    # assume this role and publish images the golden app then serves. Only the
    # branches CD actually deploys are trusted, per repository, so a fork gets
    # credentials for its own ephemeral environments and not for main.
    # `pull_request`, `environment` and tag subjects are excluded by the same
    # token: a fork PR never gets credentials, and neither does a pushed tag
    # (release builds run from main via workflow_dispatch -- see
    # .github/workflows/docker-build.yml).
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = flatten([
        for repo, refs in var.github_actions_trusted_repos :
        [for ref in refs : "repo:${repo}:ref:refs/heads/${ref}"]
      ])
    }
  }
}

resource "aws_iam_role" "github_actions" {
  count = var.enable_github_actions_role ? 1 : 0

  name               = "otterworks-github-actions"
  description        = "GitHub Actions CD: push service images and drive dashboard redeploys"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust[0].json

  # A workflow run is minutes; anything longer is only useful to a stolen token.
  max_session_duration = 3600

  tags = {
    Purpose = "Continuous delivery for demo tenants"
  }
}

data "aws_iam_policy_document" "github_actions" {
  count = var.enable_github_actions_role ? 1 : 0

  # ECR authorization is account-wide by API design (GetAuthorizationToken takes
  # no resource), so the repository-level grants below are what actually scope
  # this role's push access.
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  # Only the service repositories CD builds, not everything under the prefix
  # (which includes the control plane's own images). ECR has no per-tag IAM
  # condition, so tags are bounded elsewhere: tag immutability plus no
  # ecr:BatchDeleteImage means this role cannot move an existing tag (`main`,
  # another tenant's `tenant-<id>`), and the dashboard refuses a CD deploy of
  # any image tag not built from the session's own branch.
  statement {
    sid    = "EcrPushPull"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [
      for repo in var.github_actions_ecr_repositories :
      "arn:aws:ecr:${var.aws_region}:${data.aws_caller_identity.current.account_id}:repository/${var.ecr_repo_prefix}/${repo}"
    ]
  }
}

resource "aws_iam_role_policy" "github_actions" {
  count = var.enable_github_actions_role ? 1 : 0

  name   = "cd-access"
  role   = aws_iam_role.github_actions[0].id
  policy = data.aws_iam_policy_document.github_actions[0].json
}
