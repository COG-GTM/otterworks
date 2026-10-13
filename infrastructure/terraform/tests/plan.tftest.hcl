# Offline plan against mocked providers and a stubbed platform state: proves
# each environment's tfvars plan without AWS credentials. Run per environment:
#   terraform init -backend=false
#   terraform test -var-file=environments/<env>.tfvars
mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_data "aws_region" {
    defaults = { name = "us-east-1" }
  }
}

mock_provider "kubernetes" {}
mock_provider "helm" {}

override_data {
  target = data.terraform_remote_state.platform
  values = {
    outputs = {
      cluster_name                  = "otterworks-test"
      cluster_endpoint              = "https://example.eks.amazonaws.com"
      cluster_certificate_authority = "dGVzdA=="
      vpc_id                        = "vpc-0123456789abcdef0"
      vpc_cidr_block                = "10.0.0.0/16"
      private_subnet_ids            = ["subnet-0aaaaaaaaaaaaaaaa", "subnet-0bbbbbbbbbbbbbbbb"]
      oidc_provider_arn             = "arn:aws:iam::123456789012:oidc-provider/oidc.eks.us-east-1.amazonaws.com/id/TEST"
      oidc_provider_url             = "oidc.eks.us-east-1.amazonaws.com/id/TEST"
    }
  }
}

variables {
  db_password            = "offline-test-only"
  meilisearch_master_key = "offline-test-only-key"
}

run "plan" {
  command = plan

  assert {
    condition     = local.vpc_id == "vpc-0123456789abcdef0" && local.cluster_name == "otterworks-test"
    error_message = "Platform remote-state outputs are not wired into this layer"
  }
}
