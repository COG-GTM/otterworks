#!/bin/sh
# Database init for preferences-service on the tenant's single PostgreSQL database:
# the user_preferences schema is owned by its own login role, which is the only credential the
# service uses. Idempotent: runs from /docker-entrypoint-initdb.d (POSTGRES_USER /
# POSTGRES_DB set by the postgres image) and from scripts/init-portal-db.sh on every root
# compose start. Password: PREFERENCES_DB_PASSWORD (default "preferences", local only).
set -eu

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
  -v role_password="${PREFERENCES_DB_PASSWORD:-preferences}" <<'SQL'
SELECT 'CREATE ROLE preferences' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'preferences')\gexec
ALTER ROLE preferences WITH LOGIN PASSWORD :'role_password';
CREATE SCHEMA IF NOT EXISTS user_preferences AUTHORIZATION preferences;
ALTER SCHEMA user_preferences OWNER TO preferences;
REVOKE ALL ON SCHEMA user_preferences FROM PUBLIC;
SQL
