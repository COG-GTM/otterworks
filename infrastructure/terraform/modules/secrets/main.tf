# ------------------------------------------------------------------------------
# OtterWorks application secrets + config, vaulted for External Secrets Operator
#
#   Secrets Manager  <project>/<env>/<service>/<KEY>    sensitive values
#   SSM (String)    /<project>/<env>/<service>/<KEY>    non-sensitive config
#
# KEY is the name the service's ExternalSecret maps from; the chart maps it to
# the env var(s) the service reads (see externalSecrets.* in each chart and
# docs/SECRETS.md). Values come from Terraform resources or random_password,
# never from tfvars or git.
# ------------------------------------------------------------------------------

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  prefix = "${var.project}/${var.environment}"

  common_tags = {
    Module  = "secrets"
    Project = var.project
  }

  # Which generated/input value each service receives. The JWT secret is one
  # value written to every service that signs or validates tokens, so a
  # rotation (taint random_password.jwt_secret) changes them all at once.
  service_secrets = {
    "api-gateway" = {
      JWT_SECRET = random_password.jwt_secret.result
    }
    "auth-service" = {
      JWT_SECRET  = random_password.jwt_secret.result
      DB_PASSWORD = var.db_password
    }
    "file-service" = {
      ALERT_WEBHOOK_SECRET = random_password.alert_webhook_secret.result
    }
    "document-service" = {
      JWT_SECRET  = random_password.jwt_secret.result
      DB_PASSWORD = var.db_password
    }
    "collab-service" = {
      JWT_SECRET = random_password.jwt_secret.result
    }
    "notification-service" = {
      ALERT_WEBHOOK_SECRET = random_password.alert_webhook_secret.result
    }
    "search-service" = {
      MEILISEARCH_API_KEY = var.meilisearch_master_key != "" ? var.meilisearch_master_key : random_password.meilisearch_key.result
    }
    "analytics-service" = {
      DB_PASSWORD = var.db_password
    }
    "admin-service" = {
      JWT_SECRET           = random_password.jwt_secret.result
      DB_PASSWORD          = var.db_password
      SECRET_KEY_BASE      = random_password.secret_key_base.result
      ALERT_WEBHOOK_SECRET = random_password.alert_webhook_secret.result
    }
    "report-service" = {
      DB_PASSWORD = var.db_password
    }
  }

  # Flatten to "<service>/<KEY>" => value. Keys are not secret; values are.
  secret_entries = merge([
    for svc, kv in local.service_secrets : {
      for k, v in kv : "${svc}/${k}" => { service = svc, key = k, value = v }
    }
  ]...)

  # Every service with a key under <prefix>/<service>/; the ESO role can read
  # only these prefixes.
  services = sort(distinct(concat(keys(local.service_secrets), keys(var.service_config))))

  config_entries = merge([
    for svc, kv in var.service_config : {
      for k, v in kv : "${svc}/${k}" => { service = svc, key = k, value = v }
    }
  ]...)
}

# --- Generated secrets ---------------------------------------------------------

resource "random_password" "jwt_secret" {
  length  = 64
  special = false
}

resource "random_password" "secret_key_base" {
  length  = 128
  special = false
}

resource "random_password" "alert_webhook_secret" {
  length  = 48
  special = false
}

resource "random_password" "meilisearch_key" {
  length  = 48
  special = false
}

# --- Secrets Manager -----------------------------------------------------------

resource "aws_secretsmanager_secret" "app" {
  # Keys of the map are not sensitive even though the values are.
  for_each = nonsensitive(toset(keys(local.secret_entries)))

  name                    = "${local.prefix}/${each.key}"
  description             = "OtterWorks ${split("/", each.key)[0]} ${split("/", each.key)[1]} (delivered by External Secrets Operator)"
  recovery_window_in_days = var.recovery_window_in_days

  tags = merge(local.common_tags, {
    Service = split("/", each.key)[0]
  })
}

resource "aws_secretsmanager_secret_version" "app" {
  for_each = nonsensitive(toset(keys(local.secret_entries)))

  secret_id     = aws_secretsmanager_secret.app[each.key].id
  secret_string = local.secret_entries[each.key].value
}

# --- SSM Parameter Store (non-sensitive config) --------------------------------

resource "aws_ssm_parameter" "config" {
  for_each = local.config_entries

  name  = "/${local.prefix}/${each.key}"
  type  = "String"
  value = each.value.value
  tier  = "Standard"

  tags = merge(local.common_tags, {
    Service = each.value.service
  })
}
