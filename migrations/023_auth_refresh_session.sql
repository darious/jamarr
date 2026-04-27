-- Migration 023: Add auth_refresh_session table for JWT refresh tokens
-- This table stores hashed refresh tokens for the new JWT-based authentication system.
-- Multiple active sessions per user are supported for multi-device usage.

CREATE TABLE IF NOT EXISTS auth_refresh_session (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    token_hash TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_agent TEXT,
    ip TEXT,
    FOREIGN KEY(user_id) REFERENCES "user"(id) ON DELETE CASCADE
);

-- Index for fast token lookup
CREATE INDEX IF NOT EXISTS idx_auth_refresh_session_token_hash 
    ON auth_refresh_session(token_hash);

-- Index for user session queries (e.g., logout all sessions)
CREATE INDEX IF NOT EXISTS idx_auth_refresh_session_user_id 
    ON auth_refresh_session(user_id);

-- Index for cleanup of expired sessions
CREATE INDEX IF NOT EXISTS idx_auth_refresh_session_expires_at 
    ON auth_refresh_session(expires_at);

-- Index for active sessions query (not revoked)
CREATE INDEX IF NOT EXISTS idx_auth_refresh_session_active 
    ON auth_refresh_session(user_id, revoked_at) 
    WHERE revoked_at IS NULL;
