-- One schema per bounded context still served by the monolith. These are the decomposition
-- seams: each schema moves to its own service when that context is extracted.
-- announcements is owned by announcements-service (services/announcements-service/scripts/initdb.sh).
-- user_preferences is owned by preferences-service (services/preferences-service/scripts/initdb.sh).
CREATE SCHEMA IF NOT EXISTS feedback;
