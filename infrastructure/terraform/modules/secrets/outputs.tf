output "eso_role_arn" {
  description = "IAM role ARN for the External Secrets Operator controller ServiceAccount"
  value       = aws_iam_role.eso.arn
}

output "key_prefix" {
  description = "Prefix of every key this module writes (<project>/<environment>)"
  value       = local.prefix
}

output "secret_names" {
  description = "Secrets Manager secret names written (values are not exported)"
  value       = sort([for s in aws_secretsmanager_secret.app : s.name])
}

output "parameter_names" {
  description = "SSM parameter names written"
  value       = sort([for p in aws_ssm_parameter.config : p.name])
}
