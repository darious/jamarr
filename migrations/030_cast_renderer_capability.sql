-- Migration 030: Cast renderer playback capability cache.
--
-- Records what playback profiles each Cast renderer accepts so that the
-- backend can short-circuit the FLAC -> FLAC 16/48 -> WAV 16/48 -> MP3 320
-- hierarchy on subsequent tracks instead of re-walking it on every play.

CREATE TABLE IF NOT EXISTS cast_renderer_capability (
    renderer_id TEXT PRIMARY KEY,
    best_working_profile TEXT,
    is_lossless BOOLEAN,
    highest_successful_original_sample_rate_hz INTEGER,
    highest_successful_original_bit_depth INTEGER,
    highest_successful_original_channels INTEGER,
    highest_failed_original_sample_rate_hz INTEGER,
    highest_failed_original_bit_depth INTEGER,
    highest_failed_original_channels INTEGER,
    last_failure_reason TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cast_renderer_capability_updated
    ON cast_renderer_capability(updated_at DESC);
