-- Create optimized combined playback history view and materialized view

-- Support index for Last.fm time-based lookups
CREATE INDEX IF NOT EXISTS idx_lastfm_scrobble_played_at
ON lastfm_scrobble(played_at DESC);

-- View with range predicate to keep index usage on timestamps
CREATE OR REPLACE VIEW public.combined_playback_history AS
WITH lastfm_rows AS (
    SELECT
        'lastfm'::text AS source,
        lsm.id AS source_id,
        lsm.track_id,
        ls.played_at,
        u.id AS user_id,
        ls.lastfm_username,
        NULL::text AS client_id,
        NULL::text AS hostname,
        NULL::text AS client_ip,
        lsm.match_score,
        lsm.match_method
    FROM lastfm_scrobble_match lsm
    JOIN lastfm_scrobble ls ON ls.id = lsm.scrobble_id
    JOIN "user" u on ls.lastfm_username = u.lastfm_username
),
local_rows AS (
    SELECT
        'local'::text AS source,
        ph.id AS source_id,
        ph.track_id,
        ph."timestamp" AS played_at,
        ph.user_id,
        NULL::text AS lastfm_username,
        ph.client_id,
        ph.hostname,
        ph.client_ip,
        NULL::double precision AS match_score,
        NULL::text AS match_method
    FROM playback_history ph
),
lastfm_filtered AS (
    SELECT lf.*
    FROM lastfm_rows lf
    WHERE NOT EXISTS (
        SELECT 1
        FROM playback_history lo
        WHERE lo.track_id = lf.track_id
          AND lo."timestamp" BETWEEN lf.played_at - INTERVAL '5 seconds'
                                  AND lf.played_at + INTERVAL '5 seconds'
    )
)
SELECT
    local_rows.source,
    local_rows.source_id,
    local_rows.track_id,
    local_rows.played_at,
    local_rows.user_id,
    local_rows.lastfm_username,
    local_rows.client_id,
    local_rows.hostname,
    local_rows.client_ip,
    local_rows.match_score,
    local_rows.match_method
FROM local_rows
UNION ALL
SELECT
    lastfm_filtered.source,
    lastfm_filtered.source_id,
    lastfm_filtered.track_id,
    lastfm_filtered.played_at,
    lastfm_filtered.user_id,
    lastfm_filtered.lastfm_username,
    lastfm_filtered.client_id,
    lastfm_filtered.hostname,
    lastfm_filtered.client_ip,
    lastfm_filtered.match_score,
    lastfm_filtered.match_method
FROM lastfm_filtered;

-- Materialized view for fast reads; recreate to keep definition in sync
DROP MATERIALIZED VIEW IF EXISTS public.combined_playback_history_mat;
CREATE MATERIALIZED VIEW public.combined_playback_history_mat AS
WITH lastfm_rows AS (
    SELECT
        'lastfm'::text AS source,
        lsm.id AS source_id,
        lsm.track_id,
        ls.played_at,
        NULL::bigint AS user_id,
        ls.lastfm_username,
        NULL::text AS client_id,
        NULL::text AS hostname,
        NULL::text AS client_ip,
        lsm.match_score,
        lsm.match_method
    FROM lastfm_scrobble_match lsm
    JOIN lastfm_scrobble ls ON ls.id = lsm.scrobble_id
),
local_rows AS (
    SELECT
        'local'::text AS source,
        ph.id AS source_id,
        ph.track_id,
        ph."timestamp" AS played_at,
        ph.user_id,
        NULL::text AS lastfm_username,
        ph.client_id,
        ph.hostname,
        ph.client_ip,
        NULL::double precision AS match_score,
        NULL::text AS match_method
    FROM playback_history ph
),
lastfm_filtered AS (
    SELECT lf.*
    FROM lastfm_rows lf
    WHERE NOT EXISTS (
        SELECT 1
        FROM playback_history lo
        WHERE lo.track_id = lf.track_id
          AND lo."timestamp" BETWEEN lf.played_at - INTERVAL '5 seconds'
                                  AND lf.played_at + INTERVAL '5 seconds'
    )
)
SELECT
    local_rows.source,
    local_rows.source_id,
    local_rows.track_id,
    local_rows.played_at,
    local_rows.user_id,
    local_rows.lastfm_username,
    local_rows.client_id,
    local_rows.hostname,
    local_rows.client_ip,
    local_rows.match_score,
    local_rows.match_method
FROM local_rows
UNION ALL
SELECT
    lastfm_filtered.source,
    lastfm_filtered.source_id,
    lastfm_filtered.track_id,
    lastfm_filtered.played_at,
    lastfm_filtered.user_id,
    lastfm_filtered.lastfm_username,
    lastfm_filtered.client_id,
    lastfm_filtered.hostname,
    lastfm_filtered.client_ip,
    lastfm_filtered.match_score,
    lastfm_filtered.match_method
FROM lastfm_filtered;

CREATE UNIQUE INDEX IF NOT EXISTS combined_playback_history_mat_pk
ON public.combined_playback_history_mat (source, source_id);

CREATE INDEX IF NOT EXISTS combined_playback_history_mat_played_at
ON public.combined_playback_history_mat (played_at DESC);

CREATE INDEX IF NOT EXISTS combined_playback_history_mat_track_played
ON public.combined_playback_history_mat (track_id, played_at DESC);
