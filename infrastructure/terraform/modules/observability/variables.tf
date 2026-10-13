variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "project" {
  description = "Project name used as prefix for resource naming"
  type        = string
}

variable "oidc_provider_arn" {
  description = "ARN of the EKS cluster OIDC provider"
  type        = string
}

variable "oidc_provider_url" {
  description = "URL of the EKS cluster OIDC provider"
  type        = string
}

variable "monitoring_namespace" {
  description = "Namespace of the shared observability stack"
  type        = string
  default     = "monitoring"
}

variable "fluent_bit_service_account" {
  description = "Service account used by the Fluent Bit DaemonSet"
  type        = string
  default     = "fluent-bit"
}

variable "log_group_arns" {
  description = "Map of service name to CloudWatch log group ARN (monitoring module output)"
  type        = map(string)
}

variable "extra_log_groups" {
  description = "Additional /<project>/<environment>/<name> log groups Fluent Bit writes to"
  type        = list(string)
  default     = ["report-service", "unlabelled"]
}

variable "log_retention_days" {
  description = "Number of days to retain CloudWatch logs"
  type        = number
  default     = 30
}

variable "kms_key_arn" {
  description = "ARN of KMS key for CloudWatch log group encryption"
  type        = string
  default     = null
}
