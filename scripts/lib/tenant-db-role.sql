-- Give a tenant database its own login role, so tenant services never hold the
-- shared RDS master credential.
--
-- Run as the master user, connected to the golden `otterworks` database:
--   TENANT_DB_PASSWORD=... psql "$CONN" -v db=otterworks_a01 -v role=otterworks_a01_app -f tenant-db-role.sql
-- Idempotent: safe on every redeploy, and it migrates a database that a previous
-- deploy created and populated as the master user.
\set ON_ERROR_STOP on
\set app_password ''
\getenv app_password TENANT_DB_PASSWORD
SELECT :'app_password' = '' AS missing_password \gset
\if :missing_password
DO $$ BEGIN RAISE EXCEPTION 'TENANT_DB_PASSWORD is empty'; END $$;
\endif

SELECT format('CREATE ROLE %I LOGIN', :'role')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'role') \gexec
ALTER ROLE :"role" WITH LOGIN NOCREATEDB NOCREATEROLE PASSWORD :'app_password';

-- On RDS the master is not a superuser, and ALTER ... OWNER TO requires being
-- able to SET ROLE to the new owner. PG16+ needs that spelled out.
SELECT current_setting('server_version_num')::int >= 160000 AS pg16 \gset
\if :pg16
SELECT format('GRANT %I TO CURRENT_USER WITH SET TRUE', :'role')
WHERE NOT pg_has_role(current_user, :'role', 'SET') \gexec
\else
SELECT format('GRANT %I TO CURRENT_USER', :'role')
WHERE NOT pg_has_role(current_user, :'role', 'MEMBER') \gexec
\endif

ALTER DATABASE :"db" OWNER TO :"role";
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"db" TO :"role";

-- PUBLIC has CONNECT on every database by default, which would let one
-- tenant's role log into the golden database and every other tenant's. Owners
-- (the master, or each tenant's own role) keep their access.
SELECT format('REVOKE CONNECT, TEMPORARY ON DATABASE %I FROM PUBLIC', datname)
FROM pg_database
WHERE datname = 'otterworks' OR datname LIKE 'otterworks\_%' \gexec

\connect :"db"
SELECT set_config('otterworks.tenant_role', :'role', false) \gset

-- Hand everything the master created in this database (schemas, tables,
-- sequences, views, routines, types) to the tenant role, so the services'
-- migrations can keep altering it. Objects owned by extensions stay put.
DO $$
DECLARE
  target text := current_setting('otterworks.tenant_role');
  me oid := (SELECT oid FROM pg_roles WHERE rolname = current_user);
  r record;
BEGIN
  FOR r IN
    SELECT n.nspname FROM pg_namespace n
    WHERE n.nspowner = me
      AND n.nspname NOT LIKE 'pg\_%' AND n.nspname <> 'information_schema'
      AND NOT EXISTS (SELECT FROM pg_depend d WHERE d.classid = 'pg_namespace'::regclass
                      AND d.objid = n.oid AND d.deptype = 'e')
  LOOP
    EXECUTE format('ALTER SCHEMA %I OWNER TO %I', r.nspname, target);
  END LOOP;

  FOR r IN
    SELECT c.oid, c.relkind, n.nspname, c.relname FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relowner = me
      AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
      AND n.nspname NOT LIKE 'pg\_%' AND n.nspname <> 'information_schema'
      AND NOT EXISTS (SELECT FROM pg_depend d WHERE d.classid = 'pg_class'::regclass
                      AND d.objid = c.oid AND d.deptype IN ('e', 'a', 'i'))
  LOOP
    EXECUTE format('ALTER %s %I.%I OWNER TO %I',
      CASE r.relkind WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW'
                     WHEN 'f' THEN 'FOREIGN TABLE' WHEN 'S' THEN 'SEQUENCE' ELSE 'TABLE' END,
      r.nspname, r.relname, target);
  END LOOP;

  FOR r IN
    SELECT p.oid FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE p.proowner = me AND p.prokind IN ('f', 'p')
      AND n.nspname NOT LIKE 'pg\_%' AND n.nspname <> 'information_schema'
      AND NOT EXISTS (SELECT FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass
                      AND d.objid = p.oid AND d.deptype = 'e')
  LOOP
    EXECUTE format('ALTER ROUTINE %s OWNER TO %I', r.oid::regprocedure, target);
  END LOOP;

  FOR r IN
    SELECT t.oid FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typowner = me AND t.typtype IN ('e', 'd', 'r', 'c')
      AND (t.typtype <> 'c' OR (SELECT relkind FROM pg_class WHERE oid = t.typrelid) = 'c')
      AND n.nspname NOT LIKE 'pg\_%' AND n.nspname <> 'information_schema'
      AND NOT EXISTS (SELECT FROM pg_depend d WHERE d.classid = 'pg_type'::regclass
                      AND d.objid = t.oid AND d.deptype = 'e')
  LOOP
    EXECUTE format('ALTER TYPE %s OWNER TO %I', r.oid::regtype, target);
  END LOOP;
END
$$;
