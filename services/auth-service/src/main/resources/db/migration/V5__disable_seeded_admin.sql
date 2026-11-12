-- Earlier revisions of V1 seeded admin@otterworks.dev with a password published in
-- this repository. Disable that account wherever it still carries the published hash
-- (an account whose password was already rotated is left alone): its ADMIN role is
-- removed so it no longer counts as an administrator, and its refresh tokens are
-- revoked. The replacement value is not a BCrypt hash, so no password matches.
-- The published hash is matched by its SHA-256 digest so it is not re-committed here.
WITH disabled AS (
    UPDATE users
       SET password_hash = '!disabled:published-seed-credential',
           updated_at = NOW()
     WHERE id = 'a0000000-0000-0000-0000-000000000001'
       AND email = 'admin@otterworks.dev'
       AND encode(sha256(convert_to(password_hash, 'UTF8')), 'hex')
           = '06456ebb89a24e2fb0a01f4e5f02254664a0859c377fc00b650e8f20f55372d5'
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
