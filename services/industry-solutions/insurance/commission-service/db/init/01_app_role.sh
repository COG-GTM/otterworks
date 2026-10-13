#!/bin/sh
# Creates the non-superuser application role so FORCE ROW LEVEL SECURITY applies to it
# (superusers and BYPASSRLS roles skip RLS). The password comes from the environment.
set -eu
: "${COMMISSION_SVC_DB_PASSWORD:?COMMISSION_SVC_DB_PASSWORD must be set}"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_password="$COMMISSION_SVC_DB_PASSWORD" <<'SQL'
CREATE ROLE commission_svc LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'app_password';
GRANT CREATE, CONNECT ON DATABASE :"DBNAME" TO commission_svc;
SQL
