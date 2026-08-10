from app.scanner.audio_analysis import (
    _parse_ebur128_summary,
    _parse_replaygain,
    _parse_sample_peak,
    _parse_silence,
)


def test_parse_ebur128_summary():
    stderr = """
[Parsed_ebur128_0 @ 0xabc] Summary:

  Integrated loudness:
    I:         -13.6 LUFS
    Threshold: -23.7 LUFS

  Loudness range:
    LRA:         6.8 LU
    Threshold: -33.7 LUFS
    LRA low:   -18.0 LUFS
    LRA high:  -11.2 LUFS

  True peak:
    Peak:       -0.3 dBFS
[silencedetect @ 0xdef] silence_end: 551.291247 | silence_duration: 5.045578
"""
    assert _parse_ebur128_summary(stderr) == (-13.6, 6.8, -0.3)


def test_parse_sample_peak_from_astats_overall():
    stderr = """
[Parsed_astats_1 @ 0xabc] Channel: 1
[Parsed_astats_1 @ 0xabc] Peak level dB: -0.500000
[Parsed_astats_1 @ 0xabc] Overall
[Parsed_astats_1 @ 0xabc] Min level: -0.946715
[Parsed_astats_1 @ 0xabc] Max level: 0.963046
[Parsed_astats_1 @ 0xabc] Peak level dB: -0.327063
[Parsed_astats_1 @ 0xabc] RMS level dB: -15.790941
[out#0/null @ 0xdef] video:0KiB audio:94969KiB
"""
    assert _parse_sample_peak(stderr) == -0.327063


def test_parse_silence_leading_and_trailing():
    stderr = """
[silencedetect @ 0xabc] silence_start: 0
[silencedetect @ 0xabc] silence_end: 1.25 | silence_duration: 1.25
[silencedetect @ 0xabc] silence_start: 546.245669
[silencedetect @ 0xabc] silence_end: 551.291247 | silence_duration: 5.045578
"""
    assert _parse_silence(stderr, 551.291247) == (1.25, 546.245669)


def test_parse_silence_ignores_internal_silence():
    stderr = """
[silencedetect @ 0xabc] silence_start: 0
[silencedetect @ 0xabc] silence_end: 0.50 | silence_duration: 0.50
[silencedetect @ 0xabc] silence_start: 120.0
[silencedetect @ 0xabc] silence_end: 180.0 | silence_duration: 60.0
"""
    assert _parse_silence(stderr, 240.0) == (0.5, None)


def test_parse_silence_counts_ffmpeg_eof_closing_interval():
    stderr = """
[silencedetect @ 0xabc] silence_start: 106.997551
[silencedetect @ 0xabc] silence_end: 456.426667 | silence_duration: 349.429116
"""
    assert _parse_silence(stderr, 456.4266666666667) == (None, 106.997551)


def test_parse_replaygain():
    stderr = """
[Parsed_replaygain_0 @ 0xabc] track_gain = +0.68 dB
[Parsed_replaygain_0 @ 0xabc] track_peak = 0.964264
"""
    result = _parse_replaygain(stderr)
    assert result.replaygain_track_gain_db == 0.68
    assert result.replaygain_track_peak == 0.964264
