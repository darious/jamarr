import os
from typing import Optional

TARGET_LOUDNESS_LUFS = float(os.getenv("JAMARR_TARGET_LOUDNESS_LUFS", "-16"))
TRUE_PEAK_CEILING_DBTP = float(os.getenv("JAMARR_TRUE_PEAK_CEILING_DBTP", "-1"))
MAX_LOUDNESS_BOOST_DB = float(os.getenv("JAMARR_MAX_LOUDNESS_BOOST_DB", "6"))


def env_flag_enabled(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "off", "no"}


def calculate_normalization_gain_db(
    loudness_lufs: float,
    true_peak_db: Optional[float],
    *,
    target_lufs: float = TARGET_LOUDNESS_LUFS,
    true_peak_ceiling_db: float = TRUE_PEAK_CEILING_DBTP,
    max_boost_db: float = MAX_LOUDNESS_BOOST_DB,
) -> float:
    requested_gain = target_lufs - loudness_lufs
    if requested_gain > max_boost_db:
        requested_gain = max_boost_db
    if true_peak_db is not None:
        requested_gain = min(requested_gain, true_peak_ceiling_db - true_peak_db)
    return requested_gain


def calculate_track_gain_db(
    loudness_lufs: float,
    true_peak_db: Optional[float],
) -> float:
    return calculate_normalization_gain_db(loudness_lufs, true_peak_db)


def calculate_album_gain_db(
    album_gain_db: float,
    album_true_peak_db: Optional[float] = None,
    *,
    true_peak_ceiling_db: float = TRUE_PEAK_CEILING_DBTP,
    max_boost_db: float = MAX_LOUDNESS_BOOST_DB,
) -> float:
    gain_db = min(album_gain_db, max_boost_db)
    if album_true_peak_db is not None:
        gain_db = min(gain_db, true_peak_ceiling_db - album_true_peak_db)
    return gain_db


def album_key(track: dict) -> tuple[object, object]:
    return (
        track.get("mb_release_id") or track.get("album_mbid") or track.get("album"),
        track.get("album_artist") or track.get("artist"),
    )


def is_album_sequence_item(queue: list[dict], index: int) -> bool:
    return len(album_sequence_track_ids(queue, index)) > 1


def album_sequence_track_ids(queue: list[dict], index: int) -> list[int]:
    if index < 0 or index >= len(queue):
        return []
    track = queue[index]
    if not isinstance(track, dict):
        return []
    key = album_key(track)
    if not key[0]:
        return []

    start = index
    while start > 0:
        previous = queue[start - 1]
        current = queue[start]
        if not isinstance(previous, dict) or not isinstance(current, dict):
            break
        if album_key(previous) != key or not _looks_contiguous_album_order(previous, current):
            break
        start -= 1

    end = index
    while end + 1 < len(queue):
        current = queue[end]
        next_track = queue[end + 1]
        if not isinstance(current, dict) or not isinstance(next_track, dict):
            break
        if album_key(next_track) != key or not _looks_contiguous_album_order(current, next_track):
            break
        end += 1

    track_ids = []
    for item in queue[start : end + 1]:
        track_id = _int_or_none(item.get("id"))
        if track_id is not None:
            track_ids.append(track_id)
    return track_ids


def _looks_contiguous_album_order(track: dict, neighbor: dict) -> bool:
    track_no = _int_or_none(track.get("track_no"))
    neighbor_track_no = _int_or_none(neighbor.get("track_no"))
    disc_no = _int_or_none(track.get("disc_no"))
    neighbor_disc_no = _int_or_none(neighbor.get("disc_no"))

    if track_no is None or neighbor_track_no is None:
        return True
    if disc_no is not None and neighbor_disc_no is not None and disc_no != neighbor_disc_no:
        return True
    return abs(track_no - neighbor_track_no) == 1


def _int_or_none(value: object) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
