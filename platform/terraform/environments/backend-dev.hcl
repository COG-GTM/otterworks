# Partial backend config: terraform init -backend-config=environments/backend-dev.hcl
# dev keeps the key from the backend block in main.tf, so existing state is reused as-is.
bucket  = "otterworks-terraform-state"
key     = "platform/terraform.tfstate"
region  = "us-east-1"
encrypt = true
