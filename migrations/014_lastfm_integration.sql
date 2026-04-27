-- Add Last.fm integration columns to user table
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS lastfm_username TEXT;
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS lastfm_session_key TEXT;
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS lastfm_enabled BOOLEAN DEFAULT TRUE;
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS lastfm_connected_at TIMESTAMPTZ;

-- Create index for Last.fm enabled users (partial index for performance)
CREATE INDEX IF NOT EXISTS idx_user_lastfm_enabled ON "user"(lastfm_enabled) WHERE lastfm_enabled = TRUE;
