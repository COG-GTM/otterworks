# ------------------------------------------------------------------------------
# OtterWorks Monitoring Module
# CloudWatch log groups for each service
# ------------------------------------------------------------------------------

locals {
  common_tags = {
    Module  = "monitoring"
    Project = var.project
  }

  services = [
    "api-gateway",
    "auth-service",
    "file-service",
    "document-service",
    "collab-service",
    "notification-service",
    "search-service",
    "analytics-service",
    "admin-service",
    "audit-service",
    "web-app",
    "admin-dashboard",
  ]
}

resource "aws_cloudwatch_log_group" "services" {
  for_each = toset(local.services)
  #checkov:skip=CKV_AWS_338:Retention is var.log_retention_days per environment (prod 365); a year of logs in dev is pure cost.
  #checkov:skip=CKV_AWS_158:kms_key_arn is an optional input; the AWS-managed CloudWatch Logs encryption applies when it is unset.

  name              = "/otterworks/${var.environment}/${each.value}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = merge(local.common_tags, {
    Service = each.value
  })
}
