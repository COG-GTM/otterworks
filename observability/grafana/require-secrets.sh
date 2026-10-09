#!/bin/sh
# Grafana entrypoint guard for docker-compose.infra.yml: refuse to start with a
# missing or well-known admin password / alert-webhook secret, then exec Grafana.
set -eu

fail() {
  echo "grafana: $1 (see README.md#observability)" >&2
  exit 64
}

require_secret() {
  name=$1
  value=$2
  [ -n "$value" ] || fail "$name is required; no default is committed"
  case "$value" in
    admin | otterworks | password | changeme | demo-alert-secret)
      fail "$name must not be a well-known default value"
      ;;
  esac
  [ "${#value}" -ge 12 ] || fail "$name must be at least 12 characters"
}

require_secret GRAFANA_ADMIN_PASSWORD "${GF_SECURITY_ADMIN_PASSWORD:-}"
require_secret ALERT_WEBHOOK_SECRET "${ALERT_WEBHOOK_SECRET:-}"

# Grafana only applies GF_SECURITY_ADMIN_PASSWORD when it creates its database, so
# an existing grafana_data volume would keep the old (e.g. committed) password.
# Re-apply it on every start and refuse to start if that fails.
data_dir=${GF_PATHS_DATA:-/var/lib/grafana}
if [ -f "$data_dir/grafana.db" ]; then
  grafana cli --homepath "${GF_PATHS_HOME:-/usr/share/grafana}" \
    --config "${GF_PATHS_CONFIG:-/etc/grafana/grafana.ini}" \
    admin reset-admin-password "$GF_SECURITY_ADMIN_PASSWORD" >/dev/null 2>&1 ||
    fail "could not apply GRAFANA_ADMIN_PASSWORD to the existing Grafana database"
fi

exec "$@"
