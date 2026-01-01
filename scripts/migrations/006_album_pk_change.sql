-- Migration V6: Change Album PK to Release ID (release_mbid)
-- Purpose: Allow multiple releases (versions) per Release Group.

BEGIN;

-- 1. Backup existing metadata (Description, Chart Position) which is tied to Release Group
-- Use a temporary table for this backup
CREATE TEMP TABLE album_backup AS
SELECT mbid, description, peak_chart_position
FROM album;

-- 2. Add release_group_mbid column to album
ALTER TABLE album ADD COLUMN IF NOT EXISTS release_group_mbid TEXT;
CREATE INDEX IF NOT EXISTS idx_album_release_group ON album(release_group_mbid);

-- 3. Clear existing album data (definitions change from RG-based to Release-based)
-- We need to clear artist_album too as it references album.mbid (which are currently RG IDs)
TRUNCATE TABLE artist_album CASCADE;
TRUNCATE TABLE album CASCADE;

-- 4. Repopulate album table from track data
-- We group by release_mbid (new PK) and release_group_mbid
INSERT INTO album (mbid, release_group_mbid, title, release_date, release_type, release_type_raw, artwork_id, updated_at)
SELECT DISTINCT ON (t.release_mbid)
    t.release_mbid,      -- New PK
    t.release_group_mbid,
    t.album,            -- Use album title from track
    t.release_date,
    t.release_type,
    t.release_type_raw,
    t.artwork_id,
    NOW()
FROM track t
WHERE t.release_mbid IS NOT NULL 
  AND t.release_group_mbid IS NOT NULL;

-- 5. Restore Metadata (Description, Chart Position)
-- We join back to the backup table using the Release Group ID
UPDATE album a
SET 
    description = ab.description,
    peak_chart_position = ab.peak_chart_position
FROM album_backup ab
WHERE a.release_group_mbid = ab.mbid;

-- 6. Repopulate artist_album
-- Link artists to the NEW album IDs (Release IDs)
-- We determine 'primary' vs 'contributor' based on existing logic or data
-- For simplicity, we can rebuild this from track_artist + track data
INSERT INTO artist_album (artist_mbid, album_mbid, type)
SELECT DISTINCT 
    ta.artist_mbid,
    t.release_mbid, -- New Album ID
    CASE 
        WHEN t.album_artist_mbid LIKE '%' || ta.artist_mbid || '%' THEN 'primary'
        ELSE 'contributor'
    END
FROM track t
JOIN track_artist ta ON t.id = ta.track_id
WHERE t.release_mbid IS NOT NULL;

-- 7. Restore External Links
-- Links in external_link table for 'album' type currently point to Release Group IDs.
-- We should probably KEEP them pointing to Release Groups if they are generic (Wiki/MB/Spotify for Album).
-- BUT 'album' table now has Release IDs as PK.
-- Issue: external_links usually link to the specific release on streaming services, but we often only have RG links.
-- Logic: 
-- For now, we update external_link to point to the FIRST release ID in that group found in our library? 
-- Or duplicated for all?
-- Or should we have a separate 'release_group' table? (Out of scope)
--
-- Decision: Copy links from Release Group ID to ALL Release IDs in that group.
-- This ensures 'get_albums' (which joins on album.key = external_link.entity_id) still finds them.

-- insert links for new release IDs based on old release group ID links
INSERT INTO external_link (entity_type, entity_id, type, url)
SELECT 
    'album',
    a.mbid, -- New Release ID
    el.type,
    el.url
FROM external_link el
JOIN album a ON a.release_group_mbid = el.entity_id
WHERE el.entity_type = 'album'
  AND el.entity_id != a.mbid -- Avoid conflict if by chance ID is same (unlikely)
ON CONFLICT DO NOTHING;

-- Cleanup old links that pointed to RG IDs that are no longer in album table?
-- Actually, the old RG IDs are no longer in 'album' table, so they are orphaned "album" links.
-- We can delete them.
DELETE FROM external_link 
WHERE entity_type = 'album' 
  AND entity_id NOT IN (SELECT mbid FROM album);

-- Cleanup
DROP TABLE album_backup;

COMMIT;
