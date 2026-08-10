ALTER TABLE track_audio_analysis
    ADD COLUMN IF NOT EXISTS first_audio_start_seconds DOUBLE PRECISION;

ALTER TABLE track_audio_analysis
    ADD COLUMN IF NOT EXISTS last_audio_end_seconds DOUBLE PRECISION;

ALTER TABLE track_audio_analysis
    ADD COLUMN IF NOT EXISTS leading_silence_seconds DOUBLE PRECISION;

ALTER TABLE track_audio_analysis
    ADD COLUMN IF NOT EXISTS trailing_silence_seconds DOUBLE PRECISION;

UPDATE track_audio_analysis a
SET
    first_audio_start_seconds = COALESCE(a.first_audio_start_seconds, a.silence_start_seconds, 0),
    last_audio_end_seconds = COALESCE(a.last_audio_end_seconds, a.silence_end_seconds, t.duration_seconds),
    leading_silence_seconds = COALESCE(a.leading_silence_seconds, a.silence_start_seconds, 0),
    trailing_silence_seconds = COALESCE(
        a.trailing_silence_seconds,
        CASE
            WHEN a.silence_end_seconds IS NOT NULL AND t.duration_seconds IS NOT NULL
                THEN GREATEST(0, t.duration_seconds - a.silence_end_seconds)
            ELSE 0
        END
    )
FROM track t
WHERE t.id = a.track_id;
