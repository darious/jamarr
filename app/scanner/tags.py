import mutagen
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
import os


def extract_tags(path: str) -> dict:
    try:
        f = mutagen.File(path)
        if not f:
            return {}

        tags = {
            "path": path,
            "mtime": os.path.getmtime(path),
            "duration_seconds": f.info.length if f.info else 0,
            "sample_rate_hz": getattr(f.info, "sample_rate", 0),
            "bit_depth": getattr(f.info, "bits_per_sample", 0),  # Not always available
            "bitrate": getattr(f.info, "bitrate", 0),
            "channels": getattr(f.info, "channels", 0),
            "codec": type(f).__name__,
        }

        # Standardize tag keys
        # Mutagen keys vary by format. We try to grab common ones.

        title = None
        artist = None
        album = None
        album_artist = None
        track_no = None
        disc_no = None
        date = None
        genre = None

        # Helper to get first item safely
        def get_first(obj, keys):
            for k in keys:
                if k in obj:
                    val = obj[k]
                    if isinstance(val, list):
                        # Join multiple values with semicolon
                        return "; ".join([str(v) for v in val])
                    return str(val)
            return None

        # Vorbis/FLAC comments
        if isinstance(f, (FLAC, OggVorbis)) or hasattr(f, "tags"):
            # MP3 might use ID3, handled below if EasyID3 is used, but mutagen.File might return MP3 object
            # which has .tags as ID3.
            pass

        # We can use a more generic approach or specific per type.
        # For simplicity in v1, let's try to use EasyID3 for MP3 if possible, or just look at the dict.

        # Common keys in Vorbis/FLAC: TITLE, ARTIST, ALBUM, ALBUMARTIST, TRACKNUMBER, DISCNUMBER, DATE, GENRE
        # Common keys in ID3: TIT2, TPE1, TALB, TPE2, TRCK, TPOS, TDRC, TCON

        t = f.tags
        if t:
            title = get_first(t, ["TITLE", "TIT2", "title"])
            artist = get_first(t, ["ARTIST", "TPE1", "artist"])
            album = get_first(t, ["ALBUM", "TALB", "album"])
            album_artist = get_first(
                t, ["ALBUMARTIST", "TPE2", "albumartist", "album_artist"]
            )
            track_no = get_first(t, ["TRACKNUMBER", "TRCK", "tracknumber"])
            disc_no = get_first(t, ["DISCNUMBER", "TPOS", "discnumber"])
            date = get_first(t, ["DATE", "TDRC", "date", "year", "TYER"])
            genre = get_first(t, ["GENRE", "TCON", "genre"])
            label = get_first(t, ["ORGANIZATION", "TPUB", "label", "publisher"])
            artist_mbid = get_first(t, ["MUSICBRAINZ_ARTISTID", "musicbrainz_artistid"])
            album_artist_mbid = get_first(
                t, ["MUSICBRAINZ_ALBUMARTISTID", "musicbrainz_albumartistid"]
            )
            release_track_mbid = get_first(
                t, ["MUSICBRAINZ_RELEASETRACKID", "musicbrainz_releasetrackid"]
            )
            track_mbid = get_first(
                t,
                [
                    "MUSICBRAINZ_TRACKID",
                    "musicbrainz_trackid",
                    "UFID:http://musicbrainz.org",
                ],
            )
            # Fallback to AlbumID as release ID if needed, though they are usually distinct concepts but mapped similarly in simple taggers
            release_mbid = get_first(
                t,
                [
                    "MUSICBRAINZ_ALBUMID",
                    "musicbrainz_albumid",
                    "MUSICBRAINZ_RELEASEID",
                    "musicbrainz_releaseid",
                ],
            )
            release_group_mbid = get_first(
                t, ["MUSICBRAINZ_RELEASEGROUPID", "musicbrainz_releasegroupid"]
            )

        tags.update(
            {
                "title": title,
                "artist": artist,
                "album": album,
                "album_artist": album_artist,
                "track_no": _parse_int(track_no),
                "disc_no": _parse_int(disc_no),
                "date": date,
                "genre": genre,
                "label": label,
                "artist_mbid": artist_mbid,
                "album_artist_mbid": album_artist_mbid,
                "track_mbid": track_mbid,
                "release_track_mbid": release_track_mbid,
                "release_mbid": release_mbid,
                "release_group_mbid": release_group_mbid,
            }
        )

        return tags
    except Exception as e:
        print(f"Error parsing {path}: {e}")
        return {}


def _parse_int(val):
    if not val:
        return None
    try:
        # Handle "1/10" format
        if "/" in val:
            val = val.split("/")[0]
        return int(val)
    except ValueError:
        return None
