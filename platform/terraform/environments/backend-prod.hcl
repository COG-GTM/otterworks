# Partial backend config: terraform init -backend-config=environments/backend-prod.hcl
bucket  = "otterworks-terraform-state"
key     = "platform/prod/terraform.tfstate"
region  = "us-east-1"
encrypt = true
