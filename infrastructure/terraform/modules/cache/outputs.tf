output "redis_endpoint" {
  description = "Primary endpoint for the Redis replication group"
  value       = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "redis_port" {
  description = "Redis port"
  value       = aws_elasticache_replication_group.main.port
}

output "redis_transit_encryption_enabled" {
  description = "Whether clients must connect to Redis over TLS (rediss://)"
  value       = aws_elasticache_replication_group.main.transit_encryption_enabled
}

output "redis_security_group_id" {
  description = "Security group ID for the Redis cluster"
  value       = aws_security_group.redis.id
}
