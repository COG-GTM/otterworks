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
  description = "CIDR blocks allowed to connect to Redis"
  type        = list(string)
}

variable "redis_node_type" {
  description = "ElastiCache node type"
  type        = string
  default     = "cache.t3.micro"
}

variable "redis_transit_encryption_enabled" {
  description = "Enable in-transit (TLS) encryption. Session tokens and collaboration state travel over this connection, so it defaults to on; clients must connect with rediss:// (TLS) when it is enabled."
  type        = bool
  default     = true
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

variable "redis_auth_token" {
  description = "AUTH token for Redis. Only usable with transit encryption enabled; empty leaves AUTH off. Supply it from the secret store, never in tfvars."
  type        = string
  default     = ""
  sensitive   = true
}
