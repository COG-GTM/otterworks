output "fluent_bit_role_arn" {
  description = "IAM role ARN for the Fluent Bit service account (FLUENT_BIT_ROLE_ARN)"
  value       = aws_iam_role.fluent_bit.arn
}

output "extra_log_group_names" {
  description = "Log groups created by this module"
  value       = [for g in aws_cloudwatch_log_group.extra : g.name]
}
