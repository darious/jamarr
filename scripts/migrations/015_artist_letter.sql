ALTER TABLE artist ADD COLUMN IF NOT EXISTS letter TEXT;

UPDATE artist
SET letter = CASE
    WHEN COALESCE(sort_name, name, '') ~* '^[a-z]' THEN UPPER(SUBSTRING(COALESCE(sort_name, name, '') FROM 1 FOR 1))
    ELSE '#'
END
WHERE letter IS NULL;

CREATE INDEX IF NOT EXISTS idx_artist_letter ON artist(letter);
