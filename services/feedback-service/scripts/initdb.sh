#!/bin/sh
# Database init for feedback-service on the tenant's single PostgreSQL database:
# the feedback schema is owned by its own login role, which is the only credential the
# service uses. Idempotent: runs from /docker-entrypoint-initdb.d (POSTGRES_USER /
# POSTGRES_DB set by the postgres image) and from scripts/init-portal-db.sh on every root
# compose start. Password: FEEDBACK_DB_PASSWORD (default "feedback", local only).
set -eu

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
  -v role_password="${FEEDBACK_DB_PASSWORD:-feedback}" <<'SQL'
SELECT 'CREATE ROLE feedback' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'feedback')\gexec
ALTER ROLE feedback WITH LOGIN PASSWORD :'role_password';
CREATE SCHEMA IF NOT EXISTS feedback AUTHORIZATION feedback;
ALTER SCHEMA feedback OWNER TO feedback;
REVOKE ALL ON SCHEMA feedback FROM PUBLIC;
SQL
