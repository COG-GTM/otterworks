output "redis_endpoint" {
  description = "Primary endpoint for the Redis replication group"
  value       = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "redis_port" {
  description = "Redis port"
  value       = aws_elasticache_replication_group.main.port
}

output "redis_security_group_id" {
  description = "Security group ID for the Redis cluster"
  value       = aws_security_group.redis.id
}

output "redis_clients_security_group_id" {
  description = "Security group to attach (via SecurityGroupPolicy) to pods that may connect to Redis"
  value       = aws_security_group.redis_clients.id
}

output "redis_auth_secret_arn" {
  description = "Secrets Manager ARN holding the Redis AUTH token"
  value       = aws_secretsmanager_secret.redis_auth.arn
}
