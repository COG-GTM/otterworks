variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

variable "namespace" {
  description = "Kubernetes namespace for OtterWorks services"
  type        = string
  default     = "otterworks"
}

variable "db_password" {
  description = "Master password for the RDS PostgreSQL instance"
  type        = string
  sensitive   = true
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

variable "meilisearch_master_key" {
  description = "MeiliSearch master key (required for production)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "ses_from_address" {
  description = "From address notification-service sends as (its SES_FROM_EMAIL). The notification-service IRSA role may only send SES email from this address."
  type        = string
  default     = "notifications@otterworks.io"

  validation {
    condition     = can(regex("^[^@*\\s]+@[^@*\\s]+\\.[^@*\\s]+$", var.ses_from_address))
    error_message = "ses_from_address must be a single email address (no wildcards)."
  }
}

variable "ses_identity_domain" {
  description = "Verified SES domain identity covering ses_from_address. Defaults to the domain part of ses_from_address."
  type        = string
  default     = ""

  validation {
    condition     = var.ses_identity_domain == "" || can(regex("^[a-z0-9.-]+\\.[a-z]{2,}$", var.ses_identity_domain))
    error_message = "ses_identity_domain must be a plain domain name (no wildcards)."
  }
}
