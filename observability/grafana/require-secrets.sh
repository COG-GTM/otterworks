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

exec "$@"
