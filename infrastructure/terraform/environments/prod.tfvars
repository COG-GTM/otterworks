# Prod. db_password / meilisearch_master_key come from TF_VAR_* in CI.
aws_region  = "us-east-1"
environment = "prod"
namespace   = "otterworks"

platform_state_key = "platform/prod/terraform.tfstate"

log_retention_days = 365

db_instance_class        = "db.r6g.large"
db_allocated_storage     = 100
db_max_allocated_storage = 500

# Two nodes turn on automatic failover (see modules/cache).
redis_node_type          = "cache.r6g.large"
redis_num_cache_clusters = 2
