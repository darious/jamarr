-- Last.fm's API is no longer used (Pro-only from 2026-12-01). A scheduled
-- Last.fm sync becomes the ListenBrainz sync, which also keeps the stored
-- Last.fm scrobbles matched; any duplicate left over is dropped.
UPDATE scheduled_task SET job_key = 'listenbrainz_sync', updated_at = NOW()
WHERE job_key = 'lastfm_sync'
  AND NOT EXISTS (SELECT 1 FROM scheduled_task WHERE job_key = 'listenbrainz_sync');
DELETE FROM scheduled_task WHERE job_key = 'lastfm_sync';
