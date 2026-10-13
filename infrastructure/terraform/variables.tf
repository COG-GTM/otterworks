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

# Where the platform layer's state lives. Per environment (see
# environments/backend-<env>.hcl in platform/terraform); the defaults are dev's
# original location, so an init/plan without an environment file is unchanged.
variable "platform_state_bucket" {
  description = "S3 bucket holding the platform layer's Terraform state"
  type        = string
  default     = "otterworks-terraform-state"
}

variable "platform_state_key" {
  description = "State key of the platform layer for this environment"
  type        = string
  default     = "platform/terraform.tfstate"
}

# Sizing. Defaults equal the values dev has always run with.
variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

variable "db_allocated_storage" {
  description = "Initial RDS storage in GB"
  type        = number
  default     = 20
}

variable "db_max_allocated_storage" {
  description = "Upper bound for RDS storage autoscaling in GB"
  type        = number
  default     = 50
}

variable "redis_node_type" {
  description = "ElastiCache node type"
  type        = string
  default     = "cache.t3.micro"
}

variable "redis_num_cache_clusters" {
  description = "Redis nodes in the replication group (>1 enables automatic failover)"
  type        = number
  default     = 1
}
