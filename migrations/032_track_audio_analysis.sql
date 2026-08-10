CREATE TABLE IF NOT EXISTS track_audio_analysis (
    track_id BIGINT PRIMARY KEY REFERENCES track(id) ON DELETE CASCADE,
    track_quick_hash BYTEA,
    analysis_version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    analyzed_at TIMESTAMPTZ,
    phase1_analyzed_at TIMESTAMPTZ,
    phase2_analyzed_at TIMESTAMPTZ,
    phase3_analyzed_at TIMESTAMPTZ,
    phase4_analyzed_at TIMESTAMPTZ,

    loudness_lufs DOUBLE PRECISION,
    loudness_range_lu DOUBLE PRECISION,
    sample_peak_db DOUBLE PRECISION,
    true_peak_db DOUBLE PRECISION,
    silence_start_seconds DOUBLE PRECISION,
    silence_end_seconds DOUBLE PRECISION,
    first_audio_start_seconds DOUBLE PRECISION,
    last_audio_end_seconds DOUBLE PRECISION,
    leading_silence_seconds DOUBLE PRECISION,
    trailing_silence_seconds DOUBLE PRECISION,
    silence_threshold_db DOUBLE PRECISION,
    silence_min_duration_seconds DOUBLE PRECISION,

    replaygain_track_gain_db DOUBLE PRECISION,
    replaygain_track_peak DOUBLE PRECISION,
    replaygain_album_gain_db DOUBLE PRECISION,
    replaygain_album_peak DOUBLE PRECISION,

    bpm DOUBLE PRECISION,
    bpm_confidence DOUBLE PRECISION,

    gapless_hint TEXT,
    transition_hint TEXT,
    energy_score_local DOUBLE PRECISION,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_track_audio_analysis_status
    ON track_audio_analysis(status);

CREATE INDEX IF NOT EXISTS idx_track_audio_analysis_hash
    ON track_audio_analysis(track_quick_hash);

CREATE INDEX IF NOT EXISTS idx_track_audio_analysis_phase1
    ON track_audio_analysis(phase1_analyzed_at);
