# Dev: the values this layer has always been applied with (variable defaults).
# db_password is never committed: export TF_VAR_db_password.
aws_region  = "us-east-1"
environment = "dev"
namespace   = "otterworks"

platform_state_key = "platform/terraform.tfstate"

log_retention_days = 30

db_instance_class        = "db.t3.micro"
db_allocated_storage     = 20
db_max_allocated_storage = 50

redis_node_type          = "cache.t3.micro"
redis_num_cache_clusters = 1
