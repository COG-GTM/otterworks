-- Earlier revisions of V1 seeded admin@otterworks.dev with a password published in
-- this repository. Disable that account wherever it still carries the published hash
-- (an account whose password was already rotated is left alone): its ADMIN role is
-- removed so it no longer counts as an administrator, and its refresh tokens are
-- revoked. The replacement value is not a BCrypt hash, so no password matches.
WITH disabled AS (
    UPDATE users
       SET password_hash = '!disabled:published-seed-credential',
           updated_at = NOW()
     WHERE id = 'a0000000-0000-0000-0000-000000000001'
       AND email = 'admin@otterworks.dev'
       AND password_hash = '$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy' -- nosemgrep: generic.secrets.security.detected-bcrypt-hash.detected-bcrypt-hash
    RETURNING id
),
demoted AS (
    DELETE FROM user_roles
     WHERE role = 'ADMIN'
       AND user_id IN (SELECT id FROM disabled)
)
UPDATE refresh_tokens
   SET revoked = true
 WHERE user_id IN (SELECT id FROM disabled);
