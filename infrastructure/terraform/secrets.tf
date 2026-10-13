# ------------------------------------------------------------------------------
# App secrets + config for External Secrets Operator (docs/SECRETS.md).
#
# Off by default: with enable_external_secrets = false this file creates
# nothing, so existing applies are unchanged. Turning it on writes
#   Secrets Manager  otterworks/<env>/<service>/<KEY>
#   SSM (String)    /otterworks/<env>/<service>/<KEY>
# and the read-only IRSA role the ESO controller runs as.
# ------------------------------------------------------------------------------

variable "enable_external_secrets" {
  description = "Write app secrets/config to Secrets Manager + SSM and create the ESO IRSA role"
  type        = bool
  default     = false
}

module "secrets" {
  count  = var.enable_external_secrets ? 1 : 0
  source = "./modules/secrets"

  environment            = var.environment
  project                = "otterworks"
  oidc_provider_arn      = local.oidc_provider_arn
  oidc_provider_url      = local.oidc_provider_url
  db_password            = var.db_password
  meilisearch_master_key = var.meilisearch_master_key

  # Non-sensitive config, keyed by the env var each service reads (mirrors the
  # config.* wiring in scripts/deploy-dev.sh). Values that depend on the deploy
  # (DB host/pooler port, in-cluster Redis/MeiliSearch) stay in the deploy
  # scripts' ConfigMap, not here.
  # COGNITO_* are vaulted for future readers; no service reads them today, so
  # no chart maps them yet.
  service_config = {
    "auth-service" = {
      COGNITO_USER_POOL_ID    = module.auth.user_pool_id
      COGNITO_WEB_CLIENT_ID   = module.auth.user_pool_client_id
      COGNITO_ADMIN_CLIENT_ID = module.auth.admin_client_id
    }
    "file-service" = {
      AWS_REGION              = var.aws_region
      S3_BUCKET               = module.storage.file_bucket_name
      DYNAMODB_TABLE          = module.database.file_metadata_table_name
      DYNAMODB_FOLDERS_TABLE  = module.database.folders_table_name
      DYNAMODB_VERSIONS_TABLE = module.database.file_versions_table_name
      DYNAMODB_SHARES_TABLE   = module.database.file_shares_table_name
      SNS_TOPIC_ARN           = module.messaging.events_topic_arn
    }
    "document-service" = {
      DOC_SVC_AWS_REGION    = var.aws_region
      DOC_SVC_SNS_TOPIC_ARN = module.messaging.events_topic_arn
    }
    "notification-service" = {
      AWS_REGION                   = var.aws_region
      DYNAMODB_TABLE_NOTIFICATIONS = module.database.notifications_table_name
      SNS_TOPIC_ARN                = module.messaging.events_topic_arn
      SQS_QUEUE_URL                = module.messaging.notification_queue_url
    }
    "analytics-service" = {
      AWS_REGION          = var.aws_region
      S3_DATA_LAKE_BUCKET = module.storage.data_lake_bucket_name
    }
    "audit-service" = {
      Aws__Region          = var.aws_region
      Aws__DynamoDbTable   = module.database.audit_events_table_name
      Aws__S3ArchiveBucket = module.storage.audit_archive_bucket_name
    }
  }
}

output "external_secrets_role_arn" {
  description = "IRSA role ARN for the External Secrets Operator controller (empty when disabled)"
  value       = try(module.secrets[0].eso_role_arn, "")
}

output "external_secrets_key_prefix" {
  description = "Prefix of every vaulted key, e.g. otterworks/dev (empty when disabled)"
  value       = try(module.secrets[0].key_prefix, "")
}
