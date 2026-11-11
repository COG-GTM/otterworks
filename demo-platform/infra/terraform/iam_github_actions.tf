# The identity GitHub Actions uses to ship tenant environments.
#
# Continuous delivery needs to do two things: push service images to ECR, and
# tell the Demo Ops dashboard to redeploy the tenant that owns the branch. Only
# the first needs AWS: the second is authenticated by the workflow's GitHub OIDC
# token, not by any AWS credential. The role gets no EKS, no RDS, no
# control-table writes and no dashboard passcode, because the dashboard's runner
# Job already holds that authority under its own IRSA role, behind validation
# and an audit trail.
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
  description        = "GitHub Actions CD: push service images to ECR"
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
    resources = ["arn:aws:ecr:${var.aws_region}:${data.aws_caller_identity.current.account_id}:repository/${var.ecr_repo_prefix}/*"]
  }

  # Deliberately no access to the dashboard passcode. That passcode signs a
  # facilitator session that can drive every tenant, and this role is trusted
  # for any workshop-*/demo-* branch in a fork. CD authenticates to the
  # dashboard with the workflow's GitHub OIDC token instead (POST /api/cd/sync),
  # which the dashboard verifies itself and scopes to the one tenant that the
  # token's own repository and branch map to.
}

resource "aws_iam_role_policy" "github_actions" {
  count = var.enable_github_actions_role ? 1 : 0

  name   = "cd-access"
  role   = aws_iam_role.github_actions[0].id
  policy = data.aws_iam_policy_document.github_actions[0].json
}
