
import asyncio
import os
import re
import unicodedata
import asyncpg
from rich.console import Console
from typing import Optional, List, Set

console = Console()

# --- Normalization Logic (Copied from match-lastfm.py with fixes) ---
BENIGN_SUFFIX_TOKENS = {
    "remaster", "remastered", "mono", "stereo", "edit", "radio", 
    "explicit", "clean", "bonus", "deluxe", "expanded", "anniversary", 
    "reissue", "version", "single", "original", "acoustic", "live", "mix", "album", "remix"
}

def _normalize_basic(value: Optional[str]) -> str:
    if not value:
        return ""
    value = "".join(
        c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)
    )
    value = value.lower()
    value = value.replace("&", "and")
    value = value.replace("+", "and")
    value = value.replace("’", "'")
    value = value.replace(".", "")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())

def _strip_benign_suffix(title: str) -> str:
    if not title:
        return ""
    original = title
    pattern = re.compile(r"\s*[\(\[]([^\)\]]+)[\)\]]\s*$")
    while True:
        match = pattern.search(title)
        if not match:
            break
        suffix = match.group(1)
        tokens = re.findall(r"[a-z0-9]+", suffix.lower())
        if not tokens:
            break
        if all(token.isdigit() or token in BENIGN_SUFFIX_TOKENS for token in tokens):
            title = title[: match.start()].rstrip()
            continue
        break
    return title or original

def normalize_title(value: Optional[str]) -> str:
    if not value:
        return ""
    stripped = _strip_benign_suffix(value)
    stripped = re.sub(
        r"\s*-?\s*(radio edit|edit|remix|acoustic|version|mix|live|mono|stereo|12\" version|12 inch version|single version|album version)\s*$",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    stripped = stripped.replace("’", "'")
    return _normalize_basic(stripped)

def normalize_artist(value: Optional[str]) -> str:
    return _normalize_basic(value)

def split_artist_names(artist_name: str) -> List[str]:
    if not artist_name:
        return []
    # Logic matching match-lastfm.py but with comma support
    value = artist_name
    value = value.replace("&", "and").replace("feat.", "and").replace("featuring", "and")
    value = value.replace("ft.", "and").replace("/", "and")
    value = value.replace("+", "and")
    # Add comma to splitters
    import re
    parts = re.split(r"\s*(?:,| and )\s*", value, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p.strip()] 


from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and value[0] in ("'", '"') and value[-1] == value[0]:
            value = value[1:-1]
        os.environ.setdefault(key, value)

# --- Main Debug Logic ---
async def run():
    print(f"DEBUG: ROOT={ROOT}")
    load_dotenv(ROOT / ".env")
    print(f"DEBUG: DB_HOST={os.getenv('DB_HOST')}")
    print(f"DEBUG: DB_PORT={os.getenv('DB_PORT')}")
    
    conn = await asyncpg.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "8110"),
        user=os.getenv("DB_USER", "jamarr"),
        password=os.getenv("DB_PASS", "jamarr"),
        database=os.getenv("DB_NAME", "jamarr"),
    )

    # Scrobble IDs to check
    # 358: 7 Things (Single Version) -> Fixed
    # 492: YMCA -> Fixed
    # 3499: Pearl Jam - Last Kiss (Album Version) -> NEW CHECK
    # 183065: Dermot Kennedy - Something to Someone (Check why An Evening... failed)
    # Let's find invalid scrobbles for Dermot or explicitly check Last Kiss
    
    # Debug User Reported Misses
    print("\n--- Debugging User Reported Misses ---")
    
    # Pairs: (Scrobble ID, Track ID)
    miss_pairs = [
        (4024, 37364),
        (549, 35752),
        (3917, 39161)
    ]
    
    for s_id, t_id in miss_pairs:
        print(f"\n[bold cyan]Checking Scrobble {s_id} -> Track {t_id}[/bold cyan]")
        
        # Fetch Scrobble
        s_row = await conn.fetchrow("SELECT * FROM lastfm_scrobble WHERE id = $1", s_id)
        if not s_row:
            print("  [red]Scrobble not found![/red]")
            continue
            
        print(f"  Scrobble: Artist='{s_row['artist_name']}' Title='{s_row['track_name']}' Album='{s_row['album_name']}'")
        
            # Simulate preload_tracks query
        print(f"  [bold yellow]Testing Preload Query Logic[/bold yellow]")
        
        # Prepare args
        s_artist_norm = normalize_artist(s_row['artist_name'])
        s_artist_raw = s_row['artist_name'].lower().strip()
        search_artists = {s_artist_norm, s_artist_raw}
        
        s_title_norm = normalize_title(s_row['track_name'])
        s_title_raw = s_row['track_name'].lower().strip()
        search_titles = {s_title_norm, s_title_raw}
        
        print(f"    Artists: {search_artists}")
        print(f"    Titles : {search_titles}")
        
        # Query matching match-lastfm.py (Artist Title lookup) WITH SMART QUOTE FIX
        rows_pl = await conn.fetch("""
             SELECT t.id, t.title, t.artist
            FROM track t
             WHERE (
                (lower(t.artist) = ANY($1::text[]))
                AND (lower(t.title) = ANY($2::text[]) OR lower(replace(t.title, '.', '')) = ANY($2::text[]) OR lower(replace(t.title, '’', '''')) = ANY($2::text[]))
            )
        """, list(search_artists), list(search_titles))
        
        if rows_pl:
            print(f"    [green]Preload Query FOUND {len(rows_pl)} rows[/green]")
            for r in rows_pl:
                print(f"      Found: {r['artist']} - {r['title']} (ID: {r['id']})")
        else:
            print(f"    [red]Preload Query FOUND NOTHING[/red]")

        # Simulate Fuzzy DB Search Query WITH ARTIST TRIGRAM FIX
        print(f"  [bold yellow]Testing Fuzzy DB Search Query[/bold yellow]")
        fz_artist_input = s_row['artist_name']
        rows_fz = await conn.fetch("""
             SELECT t.id, t.title, t.artist
            FROM track t
            JOIN track_artist ta ON ta.track_id = t.id
            JOIN artist a ON a.mbid = ta.artist_mbid
            WHERE (a.name % $1 OR lower(a.name) = lower($1))
              AND t.title % $2
            ORDER BY (t.title <-> $2) + (a.name <-> $1) ASC
            LIMIT 5
        """, fz_artist_input, s_title_norm)
        
        if rows_fz:
             print(f"    [green]Fuzzy Query FOUND {len(rows_fz)} rows[/green]")
             for r in rows_fz:
                 print(f"      Found: {r['artist']} - {r['title']} (ID: {r['id']})")
        else:
             print(f"    [red]Fuzzy Query FOUND NOTHING[/red]")

        # Fetch Track
        t_row = await conn.fetchrow("""
            SELECT t.*, a.name as artist_name
            FROM track t
            LEFT JOIN track_artist ta ON ta.track_id = t.id
            LEFT JOIN artist a ON a.mbid = ta.artist_mbid
            WHERE t.id = $1
        """, t_id)
        
        if not t_row:
             print("  [red]Track not found![/red]")
             continue
             
        print(f"  Track   : Artist='{t_row['artist_name']}' Title='{t_row['title']}' Album='{t_row['album']}'")
        print(f"            Artist (denorm)='{t_row['artist']}' Album (denorm)='{t_row['album']}'")

        # Check normalization matches
        norm_s_artist = normalize_artist(s_row['artist_name'])
        norm_t_artist = normalize_artist(t_row['artist_name'] or t_row['artist'])
        
        norm_s_title = normalize_title(s_row['track_name'])
        norm_t_title = normalize_title(t_row['title'])
        
        print(f"  Norm Artist: '{norm_s_artist}' vs '{norm_t_artist}' (Match: {norm_s_artist == norm_t_artist})")
        print(f"  Norm Title : '{norm_s_title}' vs '{norm_t_title}' (Match: {norm_s_title == norm_t_title})")
        
        from rapidfuzz import fuzz
        print(f"  Fuzzy Title Ratio: {fuzz.ratio(norm_s_title, norm_t_title)}")
        print(f"  Token Set Ratio:   {fuzz.token_set_ratio(norm_s_title, norm_t_title)}")
        
        # Check token set with raw values just in case
        print(f"  Raw Token Set:     {fuzz.token_set_ratio(s_row['track_name'], t_row['title'])}")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(run())
