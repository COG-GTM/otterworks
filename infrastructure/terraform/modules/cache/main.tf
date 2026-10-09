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

# Attached only to the golden-namespace pods that use Redis (via a
# SecurityGroupPolicy, see scripts/deploy-dev.sh). Nodes and tenant pods carry
# the cluster security group instead, so they cannot reach 6379.
resource "aws_security_group" "redis_clients" {
  name        = "${var.project}-redis-clients-${var.environment}"
  description = "Pods allowed to connect to OtterWorks ElastiCache Redis"
  vpc_id      = var.vpc_id

  egress {
    description = "Redis"
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.selected.cidr_block]
  }

  tags = merge(local.common_tags, {
    Service = "shared-cache"
  })
}

data "aws_vpc" "selected" {
  id = var.vpc_id
}

resource "aws_security_group" "redis" {
  name        = "${var.project}-redis-${var.environment}"
  description = "Security group for OtterWorks ElastiCache Redis"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Redis from pods holding the redis-clients security group"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.redis_clients.id]
  }

  dynamic "ingress" {
    for_each = length(var.allowed_cidr_blocks) > 0 ? [1] : []
    content {
      description = "Redis from explicitly allowed CIDR blocks"
      from_port   = 6379
      to_port     = 6379
      protocol    = "tcp"
      cidr_blocks = var.allowed_cidr_blocks
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Service = "shared-cache"
  })
}

# ElastiCache AUTH requires in-transit encryption, so the two are enabled
# together. ElastiCache rejects "/", "\"", "@" and spaces in the token; an
# alphanumeric token also needs no escaping in redis:// URLs.
resource "random_password" "redis_auth" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "redis_auth" {
  name        = "${var.project}/${var.environment}/redis/auth-token"
  description = "AUTH token for the OtterWorks ElastiCache Redis replication group"

  tags = merge(local.common_tags, {
    Service = "shared-cache"
  })
}

resource "aws_secretsmanager_secret_version" "redis_auth" {
  secret_id     = aws_secretsmanager_secret.redis_auth.id
  secret_string = random_password.redis_auth.result
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
  transit_encryption_enabled = true
  transit_encryption_mode    = var.redis_transit_encryption_mode
  auth_token                 = random_password.redis_auth.result
  automatic_failover_enabled = var.redis_num_cache_clusters > 1
  apply_immediately          = var.redis_apply_immediately

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.redis.id]

  tags = merge(local.common_tags, {
    Service = "shared-cache"
  })
}
