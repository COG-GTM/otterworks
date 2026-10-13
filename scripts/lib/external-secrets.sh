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

# Value for Terraform's enable_external_secrets. Sticky: once the state holds
# the ESO role, keep it on even without USE_EXTERNAL_SECRETS, so an ordinary
# apply never destroys vaulted keys that running pods sync from. Turning it
# off is a deliberate `terraform apply -var enable_external_secrets=false`.
#   eso_tf_enabled <terraform dir>
eso_tf_enabled() {
  if eso_enabled; then echo true; return; fi
  if [ -n "$(terraform -chdir="$1" output -raw external_secrets_role_arn 2>/dev/null || true)" ]; then
    echo "USE_EXTERNAL_SECRETS unset but ESO keys already exist in state; keeping enable_external_secrets=true" >&2
    echo true
  else
    echo false
  fi
}

# Tenants use their own store, whose assumed role can read only DB_PASSWORD
# keys; the golden stores are not reachable from tenant namespaces.
ESO_TENANT_STORE="otterworks-tenant-secretsmanager"

# Read-only check that the shared platform add-on is installed
# (demo-platform/scripts/install-external-secrets.sh) before any chart starts
# depending on it; otherwise pods would sit in CreateContainerConfigError.
#   eso_preflight [golden|tenant]
eso_preflight() {
  local mode=${1:-golden} stores=(otterworks-secretsmanager otterworks-parameterstore)
  [ "${mode}" = "tenant" ] && stores=("${ESO_TENANT_STORE}")
  if ! kubectl get crd externalsecrets.external-secrets.io >/dev/null 2>&1; then
    echo "External Secrets Operator CRDs not found; run demo-platform/scripts/install-external-secrets.sh" >&2
    return 1
  fi
  local store ready
  for store in "${stores[@]}"; do
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
    # Evaluated by ESO, not by the shell/Helm. urlquery encodes a space as '+',
    # which SQLAlchemy would keep literally; a literal '+' is already %2B, so
    # mapping the remaining '+' to %20 gives the same form as urlencode().
    # shellcheck disable=SC2016
    db_url="postgresql+asyncpg://$(jq -rn --arg s "${db_user}" '$s|@uri'):{{ .DB_PASSWORD | urlquery | replace \"+\" \"%20\" }}@${db_host}:${db_port}/${db_name}"
  fi
  jq -n --arg prefix "${EXTERNAL_SECRETS_KEY_PREFIX}" --arg mode "${mode}" --arg dburl "${db_url}" \
    --arg tstore "${ESO_TENANT_STORE}" '
    {externalSecrets: ({enabled: true, keyPrefix: $prefix}
      + (if $dburl != "" then {templates: {DOC_SVC_DATABASE_URL: $dburl}} else {} end)
      # Tenants share only the RDS credential; their JWT/session keys,
      # MeiliSearch and (disabled) eventing are per tenant, so null those out.
      + (if $mode == "tenant" then
           {secrets: {JWT_SECRET: null, SECRET_KEY_BASE: null,
                      ALERT_WEBHOOK_SECRET: null, MEILISEARCH_API_KEY: null},
            parameters: null,
            secretStoreRef: {kind: "ClusterSecretStore", name: $tstore}}
         else {} end))}'
}
