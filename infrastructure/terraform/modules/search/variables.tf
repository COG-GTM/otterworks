variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

variable "project" {
  description = "Project name used as prefix for resource naming"
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.project))
    error_message = "Project name must be lowercase alphanumeric with hyphens, 2-21 characters."
  }
}

variable "meilisearch_cpu" {
  description = "CPU units for MeiliSearch Fargate task (1024 = 1 vCPU)"
  type        = number
  default     = 512
}

variable "meilisearch_memory" {
  description = "Memory in MiB for MeiliSearch Fargate task"
  type        = number
  default     = 1024
}

variable "meilisearch_master_key" {
  description = "MeiliSearch master key (required for production). Leave empty for dev."
  type        = string
  default     = ""
  sensitive   = true
}

variable "vpc_id" {
  description = "VPC ID for the MeiliSearch security group"
  type        = string
}

variable "subnet_ids" {
  description = "Subnet IDs for MeiliSearch ECS placement"
  type        = list(string)
}

variable "vpc_cidr" {
  description = "VPC CIDR block for security group ingress rules"
  type        = string
}

variable "kms_key_deletion_window" {
  description = "Waiting period in days before a scheduled KMS key deletion takes effect"
  type        = number
  default     = 30
}
