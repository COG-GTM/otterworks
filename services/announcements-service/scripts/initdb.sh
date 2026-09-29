#!/bin/sh
# Database init for announcements-service on the tenant's single PostgreSQL database:
# the announcements schema is owned by its own login role, which is the only credential the
# service uses. Runs from /docker-entrypoint-initdb.d (POSTGRES_USER / POSTGRES_DB are set by
# the postgres image). Password: ANNOUNCEMENTS_DB_PASSWORD (default "announcements", local only).
set -eu

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
  -v role_password="${ANNOUNCEMENTS_DB_PASSWORD:-announcements}" <<'SQL'
CREATE ROLE announcements LOGIN PASSWORD :'role_password';
CREATE SCHEMA IF NOT EXISTS announcements AUTHORIZATION announcements;
ALTER SCHEMA announcements OWNER TO announcements;
REVOKE ALL ON SCHEMA announcements FROM PUBLIC;
SQL
