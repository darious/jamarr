-- Migration v6: Release Type and Date Standardization

-- 1. CLEANUP: Drop genre from track
ALTER TABLE track DROP COLUMN IF EXISTS genre;

-- 2. TRACK: Add new columns
ALTER TABLE track ADD COLUMN IF NOT EXISTS release_type TEXT;
ALTER TABLE track ADD COLUMN IF NOT EXISTS release_type_raw TEXT;
ALTER TABLE track ADD COLUMN IF NOT EXISTS release_date_raw TEXT;
ALTER TABLE track ADD COLUMN IF NOT EXISTS release_date_tag TEXT;

-- 3. TRACK: Convert date to DATE type AND rename to release_date
-- We create the new column 'release_date' directly.
ALTER TABLE track ADD COLUMN IF NOT EXISTS release_date DATE;

-- Populate release_date from the old 'date' column
UPDATE track 
SET release_date = CASE 
    WHEN date ~ '^\d{4}$' THEN (date || '-01-01')::DATE
    WHEN date ~ '^\d{4}-\d{2}$' THEN (date || '-01')::DATE
    WHEN date ~ '^\d{4}-\d{2}-\d{2}$' THEN date::DATE
    ELSE NULL -- potentially loose data if weird format, but scanner will re-fill
END;

-- Drop the old date column
ALTER TABLE track DROP COLUMN IF EXISTS date;

-- 4. ALBUM: Add new columns
ALTER TABLE album ADD COLUMN IF NOT EXISTS release_type TEXT;
ALTER TABLE album ADD COLUMN IF NOT EXISTS release_type_raw TEXT;

-- 5. ALBUM: Convert release_date to DATE type
-- Same logic as track, but keeping the name 'release_date'
ALTER TABLE album ADD COLUMN IF NOT EXISTS release_date_temp DATE;

UPDATE album 
SET release_date_temp = CASE 
    WHEN release_date ~ '^\d{4}$' THEN (release_date || '-01-01')::DATE
    WHEN release_date ~ '^\d{4}-\d{2}$' THEN (release_date || '-01')::DATE
    WHEN release_date ~ '^\d{4}-\d{2}-\d{2}$' THEN release_date::DATE
    ELSE NULL
END;

ALTER TABLE album DROP COLUMN release_date;
ALTER TABLE album RENAME COLUMN release_date_temp TO release_date;

-- 6. Clean up unused cols from album (User requested removal)
ALTER TABLE album DROP COLUMN IF EXISTS primary_type;
ALTER TABLE album DROP COLUMN IF EXISTS secondary_types;
