# ------------------------------------------------------------------------------
# OtterWorks Cache Module
# ElastiCache Redis for session management and caching
# Used by collab-service (real-time state) and auth-service (session tokens)
# ------------------------------------------------------------------------------

locals {
  common_tags = {
    Module  = "cache"
    Project = var.project
  }
}

resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.project}-redis-${var.environment}"
  subnet_ids = var.subnet_ids

  tags = merge(local.common_tags, {
    Service = "shared-cache"
  })
}

resource "aws_security_group" "redis" {
  name        = "${var.project}-redis-${var.environment}"
  description = "Security group for OtterWorks ElastiCache Redis"
  vpc_id      = var.vpc_id

  ingress {
    description = "Redis from EKS workers"
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks
  }

  egress {
    description = "Replication and health traffic within the VPC"
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks
  }

  tags = merge(local.common_tags, {
    Service = "shared-cache"
  })
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id = "${var.project}-redis-${var.environment}"
  description          = "OtterWorks Redis cluster for session and cache"

  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.redis_node_type
  num_cache_clusters   = var.redis_num_cache_clusters
  port                 = 6379
  parameter_group_name = "default.redis7"

  at_rest_encryption_enabled = true
  transit_encryption_enabled = var.redis_transit_encryption_enabled
  auth_token                 = var.redis_auth_token != "" ? var.redis_auth_token : null
  automatic_failover_enabled = var.redis_num_cache_clusters > 1
  apply_immediately          = var.redis_apply_immediately

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.redis.id]

  tags = merge(local.common_tags, {
    Service = "shared-cache"
  })
}
