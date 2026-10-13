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

# Tenant namespaces use a separate ClusterSecretStore that assumes this role,
# so a tenant ExternalSecret can only ever reach the shared-RDS credential,
# never the golden JWT/session signing keys.
data "aws_iam_policy_document" "eso_tenant_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.eso.arn]
    }
  }
}

data "aws_iam_policy_document" "eso_tenant_read" {
  statement {
    sid    = "ReadSharedDbPassword"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = [
      for svc in local.db_services :
      "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:${local.prefix}/${svc}/DB_PASSWORD-??????"
    ]
  }
}

resource "aws_iam_role" "eso_tenant" {
  name               = "${var.project}-external-secrets-tenant-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.eso_tenant_assume_role.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy" "eso_tenant_read" {
  name   = "${var.project}-external-secrets-tenant-read"
  role   = aws_iam_role.eso_tenant.id
  policy = data.aws_iam_policy_document.eso_tenant_read.json
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

resource "aws_iam_role_policy" "eso_assume_tenant" {
  name = "${var.project}-external-secrets-assume-tenant"
  role = aws_iam_role.eso.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sts:AssumeRole"
      Resource = aws_iam_role.eso_tenant.arn
    }]
  })
}
