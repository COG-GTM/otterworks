variable "environment" {
  description = "Environment name (dev, staging, prod); second segment of every key"
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

variable "project" {
  description = "Project name; first segment of every key"
  type        = string
  default     = "otterworks"
}

variable "oidc_provider_arn" {
  description = "ARN of the EKS OIDC identity provider (for the ESO controller's IRSA role)"
  type        = string
}

variable "oidc_provider_url" {
  description = "URL of the EKS OIDC identity provider"
  type        = string
}

variable "eso_namespace" {
  description = "Namespace the External Secrets Operator controller runs in"
  type        = string
  default     = "external-secrets"
}

variable "eso_service_account" {
  description = "ServiceAccount name of the External Secrets Operator controller"
  type        = string
  default     = "external-secrets"
}

variable "db_password" {
  description = "RDS master password, vaulted for every SQL-backed service"
  type        = string
  sensitive   = true
}

variable "meilisearch_master_key" {
  description = "MeiliSearch key for search-service; a random one is generated when empty"
  type        = string
  default     = ""
  sensitive   = true
}

variable "recovery_window_in_days" {
  description = "Secrets Manager recovery window; 0 deletes immediately (dev convenience)"
  type        = number
  default     = 7
}

# Non-sensitive per-service config written to SSM Parameter Store as String
# parameters at /<project>/<environment>/<service>/<KEY>. KEY is the env var
# name the service reads.
variable "service_config" {
  description = "Map of service name to map of env var name to value (non-sensitive)"
  type        = map(map(string))
  default     = {}
}
