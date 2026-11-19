-- ListenBrainz scrobbling (replaces Last.fm, whose API keys need Pro from
-- 2026-12-01). Per-user token plus a submission state table so local plays
-- reach ListenBrainz even when it is briefly unreachable.
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS listenbrainz_username TEXT;
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS listenbrainz_token TEXT;
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS listenbrainz_enabled BOOLEAN DEFAULT TRUE;
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS listenbrainz_connected_at TIMESTAMPTZ;
-- Local plays at or after this time are sent to ListenBrainz.
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS listenbrainz_since TIMESTAMPTZ;
-- Set while submission is paused; plays from then until resume are skipped.
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS listenbrainz_paused_at TIMESTAMPTZ;
-- Set when ListenBrainz rejects the token; submission pauses until reconnect.
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS listenbrainz_auth_error TEXT;

CREATE TABLE IF NOT EXISTS listenbrainz_submission (
    playback_history_id BIGINT PRIMARY KEY
        REFERENCES playback_history(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('submitted', 'retry', 'rejected', 'skipped')),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    next_attempt_at TIMESTAMPTZ,
    submitted_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_listenbrainz_submission_retry
    ON listenbrainz_submission(next_attempt_at) WHERE status = 'retry';
