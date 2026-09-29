-- Owned by user-preferences-service. Shape matches the table legacy-portal created in the
-- shared `user_preferences` schema (Hibernate 5, ddl-auto=update), so this is a no-op when
-- the service adopts an existing legacy database and a full create on a fresh one.
CREATE TABLE IF NOT EXISTS user_preference (
    user_id              VARCHAR(100) PRIMARY KEY,
    theme                VARCHAR(20)  NOT NULL,
    locale               VARCHAR(20)  NOT NULL,
    email_notifications  BOOLEAN      NOT NULL
);
