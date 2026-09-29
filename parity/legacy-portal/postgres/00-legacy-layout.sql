-- Legacy layout: the state legacy-portal runs in today (see
-- services/legacy-portal/scripts/initdb.sql). One database, one schema per bounded
-- context, everything owned by the monolith's `legacyportal` role.
--
-- Also creates (but grants nothing to) the per-service roles that 10-handover.sql
-- transfers ownership to. Idempotent: re-running it resets the three schemas.
-- Credentials here are local-only fixtures; on EKS each service reads its own from
-- the chart's Secret.

DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['legacyportal', 'announcements_svc', 'user_preferences_svc', 'feedback_svc'] LOOP
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', r, r);
        END IF;
        EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), r);
    END LOOP;
END
$$;

DROP SCHEMA IF EXISTS announcements CASCADE;
DROP SCHEMA IF EXISTS user_preferences CASCADE;
DROP SCHEMA IF EXISTS feedback CASCADE;

CREATE SCHEMA announcements AUTHORIZATION legacyportal;
CREATE SCHEMA user_preferences AUTHORIZATION legacyportal;
CREATE SCHEMA feedback AUTHORIZATION legacyportal;
