-- Remove the default admin account that V1 used to seed with a published password.
-- Cascades to its user_roles, refresh_tokens and user_settings rows, revoking any
-- sessions issued to it. Create the first administrator with BOOTSTRAP_ADMIN_EMAIL /
-- BOOTSTRAP_ADMIN_PASSWORD instead (see AdminBootstrap).
DELETE FROM users WHERE id = 'a0000000-0000-0000-0000-000000000001';
