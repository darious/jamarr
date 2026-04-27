-- Migration V2: Add size_bytes, quick_hash, mtime to track table
-- Run this if the auto-migration in app/db.py does not trigger or for manual updates.

ALTER TABLE track ADD COLUMN IF NOT EXISTS size_bytes BIGINT;
ALTER TABLE track ADD COLUMN IF NOT EXISTS quick_hash BYTEA;
ALTER TABLE track ADD COLUMN IF NOT EXISTS mtime DOUBLE PRECISION;
