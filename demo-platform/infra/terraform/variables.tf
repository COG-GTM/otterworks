variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "cluster_name" {
  type    = string
  default = "otterworks-dev"
}

variable "platform_namespace" {
  type    = string
  default = "otterworks-platform"
}

variable "dashboard_service_account" {
  type    = string
  default = "demo-ops-dashboard"
}

variable "control_table_name" {
  type    = string
  default = "otterworks-demo-control"
}

# DNS/TLS is gated until the domain is registered. Flip to true and set
# dns_zone_name once otterworks.app exists in Route53.
variable "enable_dns" {
  type    = bool
  default = false
}

variable "dns_zone_name" {
  type    = string
  default = "otterworks.app"
}

# Shared data-plane resources the reaper must be able to GC per-tenant slices of.
# Prefix match keeps the policy stable as tables/buckets are added.
variable "shared_dynamodb_table_prefix" {
  type    = string
  default = "otterworks-"
}

variable "shared_s3_bucket_prefix" {
  type    = string
  default = "otterworks-"
}

# S3 bucket holding the application Terraform state; the runner reads it via
# `terraform output` (load_infra_outputs) to resolve RDS/S3/DynamoDB coordinates.
variable "terraform_state_bucket" {
  type    = string
  default = "otterworks-terraform-state"
}

# ECR repository namespace for the app service images; deploy-tenant.sh resolves
# the newest tag per service via ecr:DescribeImages.
variable "ecr_repo_prefix" {
  type    = string
  default = "otterworks"
}

variable "monthly_budget_usd" {
  description = "Monthly cost budget for the otterworks platform, in USD. See demo-platform/docs/cost-and-scale.md for how this figure is derived."
  type        = number
  default     = 700
}

variable "budget_alert_emails" {
  description = "Addresses notified when spend crosses the budget thresholds. No budget is created when empty."
  type        = list(string)
  default     = []
}
