import mutagen
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from datetime import date as date_obj
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
            
            # Release Type Extraction (Raw)
            release_type_raw = get_first(
                t, 
                [
                    "releasetype",
                    "musicbrainz_albumtype", 
                    "musicbrainz release type",
                    "albumtype",
                    "album type",
                    "release type",
                    "release_type",
                    "itunes_albumtype"
                ]
            )

        # Normalize Release Type
        release_type = _normalize_release_type(release_type_raw)
        
        # Strict Date Parsing and Normalization
        # We pass the full mutagen file/tags object 'f' to inspect all potential date tags
        norm_date, date_raw, date_tag = _parse_date_strict(f, tags if 'tags' in locals() else {})

        tags.update(
            {
                "title": title,
                "artist": artist,
                "album": album,
                "album_artist": album_artist,
                "track_no": _parse_int(track_no),
                "disc_no": _parse_int(disc_no),
                "release_date": norm_date, # Now a date object or None
                # "genre": genre, # Removed from Track table as per user request
                "label": label,
                "artist_mbid": artist_mbid,
                "album_artist_mbid": album_artist_mbid,
                "track_mbid": track_mbid,
                "release_track_mbid": release_track_mbid,
                "release_mbid": release_mbid,
                "release_group_mbid": release_group_mbid,
                "release_type": release_type,
                "release_type_raw": release_type_raw,
                "release_date_raw": date_raw,
                "release_date_tag": date_tag,
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

def _normalize_release_type(raw_type):
    if not raw_type:
        return "album" # Default fallback
    
    # 1. Tokenization
    tokens = [t.strip().lower() for t in raw_type.split(";")]
    tokens = [t for t in tokens if t] # Filter empty
    
    if not tokens:
        return "album"

    # 2. Mapping Rules (First match wins)
    
    # Live (Prioritized over album as per user request)
    for t in tokens:
        if t == "live":
            return "live"
    
    # Album: album, album+*
    for t in tokens:
        if t == "album" or t.startswith("album"):
            return "album"

    # Compilation
    comp_tokens = {"compilation", "soundtrack", "remix", "dj-mix", "mixtape/street", "demo", "spokenword"}
    for t in tokens:
        if t in comp_tokens:
            return "compilation"
            
    # EP
    for t in tokens:
        if t == "ep":
            return "ep"
            
    # Single
    for t in tokens:
        if t == "single":
            return "single"
            
    # Other (if we have tokens but none matched above)
    return "other"


def _parse_date_strict(f, basic_tags):
    """
    Implements strict date parsing with precision-first priority.
    Returns (normalized_date_obj, raw_date_str, source_tag)
    """
    
    # helper to get list of values for a tag key (normalized to lower check)
    def get_values(key):
        key = key.lower()
        res = []
        if hasattr(f, "tags") and f.tags:
            # mutagen tags keys can be case sensitive depending on format (Vorbis yes, ID3 often custom)
            # We iterate to find match
            for k, v in f.tags.items():
                if k.lower() == key:
                    if isinstance(v, list):
                        res.extend([str(x).strip() for x in v])
                    else:
                        res.append(str(v).strip())
        return res

    # 1. Gather all candidates
    # (Key, TagName) tuples
    # Full Date Priority
    full_date_keys = [
        ("MUSICBRAINZ_ORIGINAL_RELEASE_DATE", "MUSICBRAINZ_ORIGINAL_RELEASE_DATE"),
        ("ORIGINALDATE", "ORIGINALDATE"),
        ("TDOR", "TDOR"), # ID3
        ("MUSICBRAINZ_RELEASEDATE", "MUSICBRAINZ_RELEASEDATE"),
        ("DATE", "DATE"),
        ("RELEASEDATE", "RELEASEDATE"),
        ("TDRC", "TDRC"), # ID3
    ]
    
    # Year Fallbacks
    year_keys = [
        ("MUSICBRAINZ_ORIGINAL_RELEASE_YEAR", "MUSICBRAINZ_ORIGINAL_RELEASE_YEAR"),
        ("ORIGINALYEAR", "ORIGINALYEAR"),
        ("TORY", "TORY"), # ID3
        ("MUSICBRAINZ_RELEASE_YEAR", "MUSICBRAINZ_RELEASE_YEAR"),
        ("YEAR", "YEAR"),
        ("TYER", "TYER"), # ID3
    ]
    
    candidates = []
    
    for key, label in full_date_keys + year_keys:
        vals = get_values(key)
        for v in vals:
            if v:
                candidates.append({"val": v, "tag": label})
                
    # Also check `date` from basic_tags if not found in list (e.g. mutagen mapped fallback)
    # But only if we found NOTHING else? No, treat as candidate?
    # Actually basic_tags['date'] comes from get_first(['DATE', 'TDRC'...]) so it duplicates.
    # We can trust the explicit scan above.
    
    if not candidates:
        return None, None, None

    # 2. Score/Classify Candidates
    # Precision: 3=Full(YYYY-MM-DD), 2=Month(YYYY-MM), 1=Year(YYYY)
    
    best_candidate = None
    best_precision = -1
    best_rank = 999
    
    # Identify index for rank
    all_keys_ordered = [k[1] for k in full_date_keys + year_keys]
    
    for c in candidates:
        val = c["val"]
        tag = c["tag"]
        
        # Determine format/precision
        precision = 0
        norm_obj = None
        
        # Simple regex-like checks
        parts = val.replace("/", "-").replace(".", "-").split("-")
        
        try:
            if len(parts) >= 3 and len(parts[0]) == 4 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
                 # YYYY-MM-DD
                 precision = 3
                 norm_obj = date_obj(int(parts[0]), int(parts[1]), int(parts[2]))
            elif len(parts) == 2 and len(parts[0]) == 4 and parts[0].isdigit() and parts[1].isdigit():
                 # YYYY-MM
                 precision = 2
                 norm_obj = date_obj(int(parts[0]), int(parts[1]), 1)
            elif len(parts) == 1 and len(parts[0]) == 4 and parts[0].isdigit():
                 # YYYY
                 precision = 1
                 norm_obj = date_obj(int(parts[0]), 1, 1)
            elif len(val) >= 4 and val[:4].isdigit():
                 # Fallback: starts with year?
                 precision = 1
                 norm_obj = date_obj(int(val[:4]), 1, 1)
        except ValueError:
            # Invalid date components
            continue
             
        if precision == 0:
            continue
            
        c["norm"] = norm_obj
        c["precision"] = precision
        
        # Rank
        try:
            rank = all_keys_ordered.index(tag)
        except ValueError:
            rank = 999
            
        # Selection Logic: Highest Precision, then Lower Rank (earlier in list)
        if precision > best_precision:
            best_precision = precision
            best_rank = rank
            best_candidate = c
        elif precision == best_precision:
            if rank < best_rank:
                 best_rank = rank
                 best_candidate = c
                 
    if best_candidate:
        return best_candidate["norm"], best_candidate["val"], best_candidate["tag"]
        
    return None, None, None
