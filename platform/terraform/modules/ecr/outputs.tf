output "repository_urls" {
  description = "Map of service name to ECR repository URL"
  value = var.create_repositories ? { for k, v in aws_ecr_repository.services : k => v.repository_url } : {
    for name in var.service_names :
    name => "${data.aws_caller_identity.current.account_id}.dkr.ecr.${data.aws_region.current.name}.amazonaws.com/${var.ecr_prefix}${name}"
  }
}

output "registry_id" {
  description = "ECR registry ID (AWS account ID)"
  value       = data.aws_caller_identity.current.account_id
}
