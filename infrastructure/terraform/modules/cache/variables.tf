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

variable "vpc_id" {
  description = "VPC ID for the Redis security group"
  type        = string
}

variable "subnet_ids" {
  description = "List of subnet IDs for the ElastiCache subnet group"
  type        = list(string)
}

variable "allowed_cidr_blocks" {
  description = "Extra CIDR blocks allowed to connect to Redis. Leave empty: pods get access through the redis-clients security group. Never pass the VPC CIDR, which includes every tenant pod."
  type        = list(string)
  default     = []
}

variable "redis_node_type" {
  description = "ElastiCache node type"
  type        = string
  default     = "cache.t3.micro"
}

variable "redis_transit_encryption_mode" {
  description = "In-transit encryption mode. \"required\" rejects plaintext clients; set \"preferred\" only while migrating an existing plaintext cluster, then return to \"required\"."
  type        = string
  default     = "required"

  validation {
    condition     = contains(["required", "preferred"], var.redis_transit_encryption_mode)
    error_message = "redis_transit_encryption_mode must be \"required\" or \"preferred\"."
  }
}

variable "redis_apply_immediately" {
  description = "Apply ElastiCache modifications immediately instead of during the next maintenance window (dev convenience)."
  type        = bool
  default     = true
}

variable "redis_num_cache_clusters" {
  description = "Number of cache clusters (nodes) in the replication group"
  type        = number
  default     = 1

  validation {
    condition     = var.redis_num_cache_clusters >= 1 && var.redis_num_cache_clusters <= 6
    error_message = "Number of cache clusters must be between 1 and 6."
  }
}
