-- Migration: Cleanup and Normalize Qobuz Links
-- 1. Delete "rubbish" links (no numeric ID found in URL)
DELETE FROM external_link
WHERE type = 'qobuz'
  AND url NOT SIMILAR TO '%[0-9]+%';

-- 2. Normalize "fixable" links (convert .../interpreter/.../ID to https://play.qobuz.com/artist/ID)
-- Use regex replacement to extract the ID and rebuild the URL
UPDATE external_link
SET url = 'https://play.qobuz.com/artist/' || substring(url FROM '([0-9]+)(?:/|$)')
WHERE type = 'qobuz'
  AND url LIKE '%qobuz.com%'
  AND url NOT LIKE 'https://play.qobuz.com/artist/%'
  AND substring(url FROM '([0-9]+)(?:/|$)') IS NOT NULL;
