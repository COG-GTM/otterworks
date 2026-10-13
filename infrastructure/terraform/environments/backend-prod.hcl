# Partial backend config: terraform init -backend-config=environments/backend-prod.hcl
bucket  = "otterworks-terraform-state"
key     = "otterworks/prod/terraform.tfstate"
region  = "us-east-1"
encrypt = true
