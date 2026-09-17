-- Auth Service: per-account login failure tracking for temporary lockout
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_failed_login_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS lockout_until TIMESTAMP WITH TIME ZONE;
