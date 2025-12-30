-- Rename last_updated to updated_at and change type to TIMESTAMPTZ
ALTER TABLE playlist ADD COLUMN updated_at TIMESTAMPTZ;

-- Convert existing epoch double timestamps to TIMESTAMPTZ
UPDATE playlist SET updated_at = to_timestamp(last_updated);

-- Set Default
ALTER TABLE playlist ALTER COLUMN updated_at SET DEFAULT NOW();

-- Make NOT NULL
ALTER TABLE playlist ALTER COLUMN updated_at SET NOT NULL;

-- Drop old column
ALTER TABLE playlist DROP COLUMN last_updated;
