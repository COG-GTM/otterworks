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
  #checkov:skip=CKV_AWS_382:Open egress is the AWS default; ElastiCache initiates no outbound traffic and ingress is VPC-only.
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
    description = "All outbound (AWS APIs, package mirrors)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Service = "shared-cache"
  })
}

resource "aws_elasticache_replication_group" "main" {
  #checkov:skip=CKV_AWS_30:Clients connect with plain redis://; transit encryption is a variable (redis_transit_encryption_enabled) to flip together with rediss:// support.
  #checkov:skip=CKV_AWS_31:An AUTH token requires transit encryption (see CKV_AWS_30); access is restricted to the VPC CIDR by security group.
  #checkov:skip=CKV_AWS_191:At-rest encryption uses the AWS-managed key; a CMK would force replacement of the replication group.
  #checkov:skip=CKV2_AWS_50:Automatic failover follows redis_num_cache_clusters > 1 (prod runs 2 nodes).
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
  automatic_failover_enabled = var.redis_num_cache_clusters > 1
  apply_immediately          = var.redis_apply_immediately

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.redis.id]

  tags = merge(local.common_tags, {
    Service = "shared-cache"
  })
}
