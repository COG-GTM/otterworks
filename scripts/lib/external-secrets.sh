# shellcheck shell=bash
# ------------------------------------------------------------------------------
# Opt-in External Secrets Operator wiring for scripts/deploy-dev.sh and
# scripts/deploy-tenant.sh (docs/SECRETS.md).
#
#   USE_EXTERNAL_SECRETS=true     sync app secrets from AWS via ESO instead of
#                                 writing them into a Helm values file
#   EXTERNAL_SECRETS_KEY_PREFIX   default otterworks/dev
#
# Off by default; with it off nothing here changes what the scripts deploy.
# ------------------------------------------------------------------------------

USE_EXTERNAL_SECRETS="${USE_EXTERNAL_SECRETS:-false}"
EXTERNAL_SECRETS_KEY_PREFIX="${EXTERNAL_SECRETS_KEY_PREFIX:-otterworks/dev}"

eso_enabled() { [ "${USE_EXTERNAL_SECRETS}" = "true" ]; }

# Read-only check that the shared platform add-on is installed
# (demo-platform/scripts/install-external-secrets.sh) before any chart starts
# depending on it; otherwise pods would sit in CreateContainerConfigError.
eso_preflight() {
  if ! kubectl get crd externalsecrets.external-secrets.io >/dev/null 2>&1; then
    echo "External Secrets Operator CRDs not found; run demo-platform/scripts/install-external-secrets.sh" >&2
    return 1
  fi
  local store ready
  for store in otterworks-secretsmanager otterworks-parameterstore; do
    ready="$(kubectl get clustersecretstore "${store}" \
      -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true)"
    if [ "${ready}" != "True" ]; then
      echo "ClusterSecretStore ${store} is not Ready (got '${ready:-missing}')" >&2
      return 1
    fi
  done
}

# Drop the secret pairs ESO now delivers from the global SECRET_KV array, so
# they are no longer rendered into <release>-secrets.
#   golden: everything (JWT, DB passwords, SECRET_KEY_BASE, DB URL) is vaulted
#   tenant: only the shared-RDS credentials; per-tenant JWT/session keys stay
eso_filter_secret_kv() {
  local mode=$1 i key kept=()
  for ((i = 0; i < ${#SECRET_KV[@]}; i += 2)); do
    key="${SECRET_KV[i]}"
    if [ "${mode}" = "golden" ]; then continue; fi
    case "${key}" in
      SPRING_DATASOURCE_PASSWORD|SPRING_FLYWAY_PASSWORD|DOC_SVC_DATABASE_URL|DATABASE_PASSWORD|DB_PASSWORD) continue ;;
    esac
    kept+=("${key}" "${SECRET_KV[i + 1]}")
  done
  SECRET_KV=("${kept[@]+"${kept[@]}"}")
}

# Print a Helm values document (JSON) enabling externalSecrets for a service.
# Contains no secret values: the DB URL is an ESO template that ESO fills in
# from the synced DB_PASSWORD inside the cluster.
#   eso_values <service> <golden|tenant> <db_user> <db_host> <db_port> <db_name>
eso_values() {
  local service=$1 mode=$2 db_user=$3 db_host=$4 db_port=$5 db_name=$6
  local db_url=""
  if [ "${service}" = "document-service" ]; then
    # '{{ .DB_PASSWORD | urlquery }}' is evaluated by ESO, not by the shell/Helm.
    # shellcheck disable=SC2016
    db_url="postgresql+asyncpg://$(jq -rn --arg s "${db_user}" '$s|@uri'):{{ .DB_PASSWORD | urlquery }}@${db_host}:${db_port}/${db_name}"
  fi
  jq -n --arg prefix "${EXTERNAL_SECRETS_KEY_PREFIX}" --arg mode "${mode}" --arg dburl "${db_url}" '
    {externalSecrets: ({enabled: true, keyPrefix: $prefix}
      + (if $dburl != "" then {templates: {DOC_SVC_DATABASE_URL: $dburl}} else {} end)
      # Tenants share only the RDS credential; their JWT/session keys,
      # MeiliSearch and (disabled) eventing are per tenant, so null those out.
      + (if $mode == "tenant" then
           {secrets: {JWT_SECRET: null, SECRET_KEY_BASE: null,
                      ALERT_WEBHOOK_SECRET: null, MEILISEARCH_API_KEY: null},
            parameters: null}
         else {} end))}'
}
