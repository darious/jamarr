
-- Migration to add image_source to artist table
ALTER TABLE artist ADD COLUMN IF NOT EXISTS image_source TEXT;
