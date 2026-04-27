-- Migration V11: Add FTS index to Album table
-- Purpose: Enable efficient Full Text Search on album titles.

BEGIN;

-- Create GIN index for fast text search on album title
-- We use English dictionary configuration
CREATE INDEX IF NOT EXISTS idx_album_title_fts 
ON album 
USING GIN (to_tsvector('english', title));

COMMIT;
