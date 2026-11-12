-- Revoke the default admin password that V1 previously seeded with a committed bcrypt hash.
-- Matched by fingerprint so an admin whose password was already rotated is left untouched.
-- '!' is not a valid bcrypt hash, so no password can authenticate until AdminBootstrap
-- (ADMIN_BOOTSTRAP_PASSWORD) sets a new one.
UPDATE users
SET password_hash = '!', updated_at = NOW()
WHERE id = 'a0000000-0000-0000-0000-000000000001'
  AND md5(password_hash) = 'a015f44e73c0c6c1714cb3a335fc6988';

DELETE FROM refresh_tokens
WHERE user_id = 'a0000000-0000-0000-0000-000000000001'
  AND EXISTS (
    SELECT 1 FROM users
    WHERE id = 'a0000000-0000-0000-0000-000000000001' AND password_hash = '!'
  );
