-- Fix Qobuz Links to use play.qobuz.com format

-- Update links that end in digits (extract ID)
WITH updates AS (
    SELECT 
        entity_type, entity_id, type,
        'https://play.qobuz.com/artist/' || (regexp_match(url, '([0-9]+)$'))[1] as new_url
    FROM external_link
    WHERE type = 'qobuz'
    AND url ~ '[0-9]+$'
)
UPDATE external_link el
SET url = u.new_url
FROM updates u
WHERE el.entity_type = u.entity_type 
  AND el.entity_id = u.entity_id 
  AND el.type = u.type
  AND el.url != u.new_url;

-- Delete any Qobuz links that do NOT match the play.qobuz.com/artist/ID format
-- (This includes the ones we couldn't fix above because they didn't end in digits or were otherwise malformed)
DELETE FROM external_link
WHERE type = 'qobuz'
AND url NOT LIKE 'https://play.qobuz.com/artist/%';
