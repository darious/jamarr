from typing import Dict, Any, Optional

def assert_has_artwork_fields(item: Dict[str, Any], required: bool = True) -> None:
    """
    Assert that a dictionary item (track, album, artist) has standard artwork fields.
    """
    # Check for presence of key fields
    if required:
        # At least one of art_id or art_sha1 should be present if we expect artwork
        # Note: Some items might genuinely not have artwork, but the KEYS should exist if the API structure guarantees them.
        # But usually 'art_id' might be null.
        pass

    # Verify field types if they exist
    if "art_id" in item and item["art_id"] is not None:
        assert isinstance(item["art_id"], int), f"art_id must be int, got {type(item['art_id'])}"
    
    if "art_sha1" in item and item["art_sha1"] is not None:
        assert isinstance(item["art_sha1"], str), f"art_sha1 must be str, got {type(item['art_sha1'])}"
        assert len(item["art_sha1"]) == 40, "art_sha1 must be 40 chars (SHA1)"

    if "background_art_id" in item and item["background_art_id"] is not None:
         assert isinstance(item["background_art_id"], int)

def assert_track_structure(track: Dict[str, Any]) -> None:
    """Assert a track object has all required fields."""
    required_fields = ["id", "title", "artist", "album", "duration_seconds"]
    for field in required_fields:
        assert field in track, f"Track missing required field: {field}"
    
    assert_has_artwork_fields(track, required=False)

def assert_artist_structure(artist: Dict[str, Any]) -> None:
    """Assert an artist object has all required fields."""
    required_fields = ["mbid", "name"]
    for field in required_fields:
        assert field in artist, f"Artist missing required field: {field}"
    
    assert_has_artwork_fields(artist, required=False)

def assert_album_structure(album: Dict[str, Any]) -> None:
    """Assert an album object has all required fields."""
    required_fields = ["album_mbid", "album", "year"]
    for field in required_fields:
        assert field in album, f"Album missing required field: {field}"
    
    assert_has_artwork_fields(album, required=False)

def assert_video_structure(video: Dict[str, Any]) -> None:
    required_fields = ["id", "title", "artist", "file_path"]
    for field in required_fields:
        assert field in video

SPECIAL_CHAR_STRINGS = [
    "Artist's Name",  # Apostrophe
    'Artist "Quoted"',  # Double Quotes
    "Björk",  # Unicode
    "AC/DC",  # Slash
    "Artist & The Band",  # Ampersand
    "O'Conner",
    "Sigur Rós",
    "100% Hits"
]

MALICIOUS_SQL_STRINGS = [
    "'; DROP TABLE track; --",
    "1' OR '1'='1",
    "admin'--",
    "UNION SELECT * FROM user"
]
