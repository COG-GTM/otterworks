# ------------------------------------------------------------------------------
# OtterWorks Observability Module
# IRSA role for the shared Fluent Bit DaemonSet (demo-platform/k8s/observability)
# so it can write container logs to the per-service CloudWatch log groups owned
# by the monitoring module, plus the log groups Fluent Bit routes to that the
# monitoring module does not create (same naming and retention).
# ------------------------------------------------------------------------------

locals {
  common_tags = {
    Module  = "observability"
    Project = var.project
  }
  oidc_host = replace(var.oidc_provider_url, "https://", "")
}

resource "aws_cloudwatch_log_group" "extra" {
  for_each = toset(var.extra_log_groups)

  name              = "/${var.project}/${var.environment}/${each.value}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = merge(local.common_tags, {
    Service = each.value
  })
}

data "aws_iam_policy_document" "fluent_bit_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    # Exactly one service account: the shared DaemonSet. Tenants never get this role.
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:sub"
      values   = ["system:serviceaccount:${var.monitoring_namespace}:${var.fluent_bit_service_account}"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "fluent_bit" {
  statement {
    sid    = "WriteOtterworksLogGroups"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = flatten([
      for arn in concat(values(var.log_group_arns), [for g in aws_cloudwatch_log_group.extra : g.arn]) :
      [arn, "${arn}:*"]
    ])
  }

  statement {
    sid       = "DescribeLogGroups"
    effect    = "Allow"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["*"]
  }
}

resource "aws_iam_role" "fluent_bit" {
  name               = "${var.project}-fluent-bit-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.fluent_bit_assume.json

  tags = merge(local.common_tags, {
    ServiceAccountName = var.fluent_bit_service_account
  })
}

resource "aws_iam_role_policy" "fluent_bit" {
  name   = "${var.project}-fluent-bit-logs"
  role   = aws_iam_role.fluent_bit.id
  policy = data.aws_iam_policy_document.fluent_bit.json
}
