#!/bin/sh
# Database init for feedback-service on the tenant's single PostgreSQL database:
# the feedback schema is owned by its own login role, which is the only credential the
# service uses. Runs from /docker-entrypoint-initdb.d (POSTGRES_USER / POSTGRES_DB are set by
# the postgres image). Password: FEEDBACK_DB_PASSWORD (default "feedback", local only).
set -eu

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
  -v role_password="${FEEDBACK_DB_PASSWORD:-feedback}" <<'SQL'
CREATE ROLE feedback LOGIN PASSWORD :'role_password';
CREATE SCHEMA IF NOT EXISTS feedback AUTHORIZATION feedback;
ALTER SCHEMA feedback OWNER TO feedback;
REVOKE ALL ON SCHEMA feedback FROM PUBLIC;
SQL
