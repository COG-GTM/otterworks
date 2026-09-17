-- Per-user storage quota (default 10 GiB)
ALTER TABLE users ADD COLUMN quota_bytes BIGINT NOT NULL DEFAULT 10737418240;
