# Offline plan against mocked providers: proves each environment's tfvars plan
# without AWS credentials. Run per environment:
#   terraform init -backend=false
#   terraform test -var-file=environments/<env>.tfvars
mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = { names = ["us-east-1a", "us-east-1b", "us-east-1c"] }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
}

mock_provider "tls" {}

run "plan" {
  command = plan

  assert {
    condition     = module.eks.cluster_name == var.cluster_name
    error_message = "EKS cluster name does not follow var.cluster_name"
  }

  assert {
    condition     = var.create_ecr_repositories ? length(module.ecr.repository_urls) > 0 : length(module.ecr.repository_urls) == 0
    error_message = "ECR repositories are not gated by create_ecr_repositories"
  }
}
