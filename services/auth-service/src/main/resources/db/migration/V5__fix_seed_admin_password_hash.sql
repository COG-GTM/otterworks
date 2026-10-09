-- V1 seeded admin@otterworks.dev with a bcrypt hash that does not match the
-- documented password (Admin123!), so the account could never log in. Only
-- rows still holding that broken seed hash are touched.
UPDATE users
SET password_hash = '$2a$10$w1mMiapumcDI4GBy3gWeN.6V.zxZ282iR9pk5TfQ8OVjGH1dTJpey', -- nosemgrep: generic.secrets.security.detected-bcrypt-hash.detected-bcrypt-hash
    updated_at = NOW()
WHERE id = 'a0000000-0000-0000-0000-000000000001'
  AND password_hash = '$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy'; -- nosemgrep: generic.secrets.security.detected-bcrypt-hash.detected-bcrypt-hash
