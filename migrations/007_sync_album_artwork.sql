-- Migration 007: Sync album.artwork_id from track table
-- This fixes albums where artwork_id was not updated during rescans
-- due to missing artwork_id in the ON CONFLICT UPDATE clause

-- Update album.artwork_id based on the first track with artwork for each release
UPDATE album
SET artwork_id = subquery.artwork_id
FROM (
    SELECT DISTINCT ON (release_mbid)
        release_mbid,
        artwork_id
    FROM track
    WHERE release_mbid IS NOT NULL
      AND artwork_id IS NOT NULL
    ORDER BY release_mbid, id
) AS subquery
WHERE album.mbid = subquery.release_mbid
  AND (album.artwork_id IS NULL OR album.artwork_id != subquery.artwork_id);

-- Log the number of albums updated
-- Note: This will show in the migration output
SELECT COUNT(*) as albums_updated
FROM album a
WHERE EXISTS (
    SELECT 1 FROM track t
    WHERE t.release_mbid = a.mbid
      AND t.artwork_id IS NOT NULL
      AND (a.artwork_id IS NULL OR a.artwork_id != t.artwork_id)
);
