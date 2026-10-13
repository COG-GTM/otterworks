variable "project" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "ecr_prefix" {
  description = "Prefix for ECR repository names"
  type        = string
  default     = "otterworks/"
}

variable "service_names" {
  description = "List of service names to create ECR repositories for"
  type        = list(string)
}

variable "create_repositories" {
  description = "Create the repositories. Off for an environment that shares another environment's registry in the same account (names are not environment-scoped)."
  type        = bool
  default     = true
}
