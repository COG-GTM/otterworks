# ------------------------------------------------------------------------------
# IRSA role for the External Secrets Operator controller (a shared, cluster-wide
# platform component). Read-only, and only under the per-service prefixes this
# module writes (otterworks/<env>/<service>/*): it cannot read other secrets in
# the account (e.g. otterworks/dev/rds/master) or write anything.
# ------------------------------------------------------------------------------

data "aws_iam_policy_document" "eso_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_provider_url, "https://", "")}:sub"
      values   = ["system:serviceaccount:${var.eso_namespace}:${var.eso_service_account}"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_provider_url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "eso_read" {
  statement {
    sid    = "ReadAppSecrets"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    # Secrets Manager appends a random 6-character suffix to every ARN.
    resources = [
      for svc in local.services :
      "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:${local.prefix}/${svc}/*"
    ]
  }

  statement {
    sid    = "ReadAppConfig"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
    ]
    resources = [
      for svc in local.services :
      "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter/${local.prefix}/${svc}/*"
    ]
  }
}

resource "aws_iam_role" "eso" {
  name               = "${var.project}-external-secrets-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.eso_assume_role.json

  tags = merge(local.common_tags, {
    ServiceAccountName = var.eso_service_account
  })
}

resource "aws_iam_role_policy" "eso_read" {
  name   = "${var.project}-external-secrets-read"
  role   = aws_iam_role.eso.id
  policy = data.aws_iam_policy_document.eso_read.json
}
