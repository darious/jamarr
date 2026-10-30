from typing import Any, Dict, List, Optional
from pydantic import BaseModel

class Track(BaseModel):
    id: int
    title: str
    artist: str
    album: str
    duration_seconds: float
    art_sha1: Optional[str] = None
    codec: Optional[str] = None
    bit_depth: Optional[int] = None
    sample_rate_hz: Optional[int] = None
    artist_mbid: Optional[str] = None
    album_mbid: Optional[str] = None
    mb_release_id: Optional[str] = None
    path: Optional[str] = None
    album_artist: Optional[str] = None
    track_no: Optional[int] = None
    disc_no: Optional[int] = None
    release_date: Optional[str] = None
    bitrate: Optional[int] = None
    plays: Optional[int] = None
    loudness_lufs: Optional[float] = None
    true_peak_db: Optional[float] = None
    loudness_gain_db: Optional[float] = None
    loudness_gain_mode: Optional[str] = None
    loudness_target_lufs: Optional[float] = None
    loudness_normalized: bool = False
    logged: bool = False
    artists: Optional[List[Dict[str, Optional[str]]]] = None
    # Identity of this occurrence in a queue, assigned by the server when the
    # track enters one (#325). The same track id can appear twice; edits are
    # matched on this, never on the track id. Ignored where tracks are added.
    entry_id: Optional[str] = None


class PlayerState(BaseModel):
    queue: List[Track]
    current_index: int
    # Moves whenever the queue's membership or order changes (#332); send it
    # back as expected_revision with an edit to have a stale edit refused.
    queue_revision: int = 0
    position_seconds: float
    is_playing: bool
    renderer: str  # UDN
    renderer_id: Optional[str] = None
    renderer_kind: Optional[str] = None
    transport_state: Optional[str] = "STOPPED"
    volume: Optional[int] = None
    # Mute as the renderer last reported it (UPnP RenderingControl events,
    # Cast receiver status), so a mute made on the device shows; None when unknown.
    muted: Optional[bool] = None
    # Set when the queue halted by itself rather than because the listener
    # stopped it: "renderer_stopped" (the device dropped out or was stopped
    # mid-track), "renderer_error" (the device reported a playback error) or
    # "load_failed" (the device rejected the track or never confirmed it).
    # Lets the UI say what happened instead of going quiet.
    stopped_reason: Optional[str] = None
    # Renderer audio output plan for the current track (see
    # app/services/playback_plan.py): action, format, mime_type, reason,
    # source_label, quality_label, ... None for local playback.
    output_plan: Optional[Dict[str, Any]] = None


class QueueUpdate(BaseModel):
    queue: List[Track]
    start_index: int = 0
    # The queue_revision this edit was made against. When it is no longer the
    # live revision the edit is refused with 409 and the current state.
    # Omitted: the edit applies unconditionally (older clients).
    expected_revision: Optional[int] = None


class AppendQueue(BaseModel):
    tracks: List[Track]
    expected_revision: Optional[int] = None


class ClearQueue(BaseModel):
    expected_revision: Optional[int] = None


class IndexUpdate(BaseModel):
    index: int


class ProgressUpdate(BaseModel):
    position_seconds: float
    is_playing: bool


class LogPlayRequest(BaseModel):
    track_id: int
