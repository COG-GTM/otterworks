# Partial backend config: terraform init -backend-config=environments/backend-staging.hcl
bucket  = "otterworks-terraform-state"
key     = "platform/staging/terraform.tfstate"
region  = "us-east-1"
encrypt = true
