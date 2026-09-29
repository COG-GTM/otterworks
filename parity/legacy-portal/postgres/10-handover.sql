-- Cutover step: hand each bounded-context schema (and every table in it, which
-- carries its identity/serial sequences along) from the monolith's role to the
-- owning service's role. After this:
--   * announcements_svc / user_preferences_svc / feedback_svc own exactly one schema
--     each and cannot see the others' (Flyway in each service baselines the existing
--     tables and applies V1 as a no-op);
--   * legacyportal keeps DML on all three for the rollback window, so the monolith
--     can be switched back on against the same data without a reverse migration.
-- Once the rollback window closes, REVOKE the legacyportal grants and move each
-- schema to its own database (the charts already take a per-service DATABASE_URL).

DO $$
DECLARE
    m record;
    t record;
BEGIN
    FOR m IN
        SELECT * FROM (VALUES
            ('announcements', 'announcements_svc'),
            ('user_preferences', 'user_preferences_svc'),
            ('feedback', 'feedback_svc')
        ) AS v(schema_name, role_name)
    LOOP
        EXECUTE format('ALTER SCHEMA %I OWNER TO %I', m.schema_name, m.role_name);
        FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = m.schema_name LOOP
            EXECUTE format('ALTER TABLE %I.%I OWNER TO %I', m.schema_name, t.tablename, m.role_name);
        END LOOP;

        EXECUTE format('GRANT USAGE ON SCHEMA %I TO legacyportal', m.schema_name);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO legacyportal', m.schema_name);
        EXECUTE format('GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA %I TO legacyportal', m.schema_name);
        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO legacyportal', m.role_name, m.schema_name);
        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO legacyportal', m.role_name, m.schema_name);
    END LOOP;
END
$$;
