output "control_table_name" {
  value = aws_dynamodb_table.control.name
}

output "control_table_arn" {
  value = aws_dynamodb_table.control.arn
}

output "dashboard_role_arn" {
  value = aws_iam_role.dashboard.arn
}

output "dns_zone_id" {
  value = var.enable_dns ? data.aws_route53_zone.demo[0].zone_id : null
}

output "dns_zone_name_servers" {
  value = var.enable_dns ? data.aws_route53_zone.demo[0].name_servers : null
}

output "dns_role_arn" {
  value = var.enable_dns ? aws_iam_role.dns[0].arn : null
}
