-- Drop unused columns from missing_album table
ALTER TABLE missing_album DROP COLUMN IF EXISTS image_url;
ALTER TABLE missing_album DROP COLUMN IF EXISTS tidal_url;
ALTER TABLE missing_album DROP COLUMN IF EXISTS qobuz_url;
