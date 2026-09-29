#!/bin/sh
# Roles and schemas of the portal services (announcements, preferences, feedback) on the shared
# PostgreSQL of docker-compose.infra.yml: one login role per service owning its own schema in the
# otterworks database. Runs in the portal-db-init one-shot container of docker-compose.yml once
# postgres is healthy, so it also applies to an existing postgres_data volume. Each service's own
# scripts/initdb.sh (mounted under /portal-initdb/services/) is the definition and is idempotent.
#
# PORTAL_DB_RESET=1 first drops the three schemas and their data, so the services start on empty
# tables (the parity suite requires it); stop the services before resetting.
set -eu

if [ "${PORTAL_DB_RESET:-0}" = 1 ]; then
  psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
    -c 'DROP SCHEMA IF EXISTS announcements, user_preferences, feedback CASCADE'
fi

for script in /portal-initdb/services/*.sh; do
  echo "portal-db-init: ${script##*/}"
  sh "${script}"
done
