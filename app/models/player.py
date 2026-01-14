from typing import Dict, List, Optional
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
    logged: bool = False
    artists: Optional[List[Dict[str, Optional[str]]]] = None


class PlayerState(BaseModel):
    queue: List[Track]
    current_index: int
    position_seconds: float
    is_playing: bool
    renderer: str  # UDN
    transport_state: Optional[str] = "STOPPED"
    volume: Optional[int] = None


class QueueUpdate(BaseModel):
    queue: List[Track]
    start_index: int = 0


class AppendQueue(BaseModel):
    tracks: List[Track]


class IndexUpdate(BaseModel):
    index: int


class ProgressUpdate(BaseModel):
    position_seconds: float
    is_playing: bool


class LogPlayRequest(BaseModel):
    track_id: int
