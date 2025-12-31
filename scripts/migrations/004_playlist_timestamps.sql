-- Add updated_at if missing (safe if it already exists)
ALTER TABLE playlist ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

-- Add last_updated if missing so the UPDATE below never errors on missing column
ALTER TABLE playlist ADD COLUMN IF NOT EXISTS last_updated DOUBLE PRECISION;

-- Backfill updated_at from last_updated when present; otherwise use NOW()
UPDATE playlist SET updated_at = COALESCE(updated_at, to_timestamp(last_updated), NOW());

-- Set defaults/constraints
ALTER TABLE playlist ALTER COLUMN updated_at SET DEFAULT NOW();
ALTER TABLE playlist ALTER COLUMN updated_at SET NOT NULL;

-- Remove legacy column
ALTER TABLE playlist DROP COLUMN IF EXISTS last_updated;
