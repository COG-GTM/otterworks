# ------------------------------------------------------------------------------
# OtterWorks IRSA Module
# IAM Roles for Service Accounts (IRSA) on EKS
# Enables fine-grained AWS permissions per Kubernetes service account
# ------------------------------------------------------------------------------

locals {
  common_tags = {
    Module  = "irsa"
    Project = var.project
  }
}

data "aws_iam_policy_document" "assume_role" {
  for_each = var.service_accounts

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    # Trust ONLY the golden namespace's service account. These roles carry
    # bucket- and table-wide grants, so they must never be assumable from a
    # tenant namespace (otterworks-<ATTENDEE_ID>), whose code is attendee-
    # controlled. Tenants get their own tenant-scoped roles, created at
    # provisioning by scripts/deploy-tenant.sh under the /otterworks-tenant/ path,
    # capped by the tenant permissions boundary (see ../../main.tf).
    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_provider_url, "https://", "")}:sub"
      values   = ["system:serviceaccount:${var.namespace}:${each.key}"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_provider_url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "service_account" {
  for_each = var.service_accounts

  name               = "${var.project}-${each.key}-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.assume_role[each.key].json

  tags = merge(local.common_tags, {
    Service            = each.key
    ServiceAccountName = each.key
  })
}

resource "aws_iam_role_policy" "service_account" {
  for_each = var.service_accounts

  name   = "${var.project}-${each.key}-policy"
  role   = aws_iam_role.service_account[each.key].id
  policy = each.value
}
