-- Migration 031: Per-family refresh-token lineage for reuse detection.
--
-- Each login starts a rotation "family"; every rotation keeps the same
-- family_id. Replaying a rotated token is now scoped to its own family: on
-- reuse we revoke only that family (that one device/session line) instead of
-- nuking every session the user has on every device.
--
-- Existing rows each become their own family so current sessions keep working.

ALTER TABLE auth_refresh_session
    ADD COLUMN IF NOT EXISTS family_id UUID;

UPDATE auth_refresh_session
SET family_id = gen_random_uuid()
WHERE family_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_auth_refresh_session_family
    ON auth_refresh_session(family_id, revoked_at)
    WHERE revoked_at IS NULL;
