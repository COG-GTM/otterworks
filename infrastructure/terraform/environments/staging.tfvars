# Staging. db_password / meilisearch_master_key come from TF_VAR_* in CI.
aws_region  = "us-east-1"
environment = "staging"
namespace   = "otterworks"

platform_state_key = "platform/staging/terraform.tfstate"

log_retention_days = 30

db_instance_class        = "db.t3.small"
db_allocated_storage     = 20
db_max_allocated_storage = 100

redis_node_type          = "cache.t3.small"
redis_num_cache_clusters = 1
