
import asyncio
import os
import asyncpg
from rich.console import Console
from rich.table import Table
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

console = Console()

async def run():
    load_dotenv(ROOT / ".env")
    
    conn = await asyncpg.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "8110"),
        user=os.getenv("DB_USER", "jamarr"),
        password=os.getenv("DB_PASS", "jamarr"),
        database=os.getenv("DB_NAME", "jamarr"),
    )

    # 1. Overview of reasons
    print("\n--- Miss Reasons Overview ---")
    reasons = await conn.fetch("""
        SELECT reason, COUNT(*) as count 
        FROM lastfm_scrobble_miss 
        GROUP BY reason 
        ORDER BY count DESC
    """)
    t = Table(show_header=True, header_style="bold magenta")
    t.add_column("Reason")
    t.add_column("Count")
    for r in reasons:
        t.add_row(str(r['reason']), str(r['count']))
    console.print(t)

    # 2. Most frequent missing Artists
    print("\n--- Top Missing Artists (from Scrobble data) ---")
    # Join with scrobble table to get the names
    top_artists = await conn.fetch("""
        SELECT s.artist_name, COUNT(*) as count
        FROM lastfm_scrobble_miss m
        JOIN lastfm_scrobble s ON m.scrobble_id = s.id
        GROUP BY s.artist_name
        ORDER BY count DESC
        LIMIT 20
    """)
    t_art = Table(show_header=True, header_style="bold green")
    t_art.add_column("Artist")
    t_art.add_column("Miss Count")
    for row in top_artists:
        t_art.add_row(str(row['artist_name']), str(row['count']))
    console.print(t_art)

    # 3. Sample of 'no_candidates' misses to spot checking
    print("\n--- Sample 'no_candidates' Misses ---")
    no_cands = await conn.fetch("""
        SELECT s.id, s.artist_name, s.track_name, s.album_name, m.reason
        FROM lastfm_scrobble_miss m
        JOIN lastfm_scrobble s ON m.scrobble_id = s.id
        WHERE m.reason = 'no_candidates' OR m.reason = 'no_candidate_match'
        ORDER BY s.played_at DESC
        LIMIT 20
    """)
    t_samp = Table(show_header=True, header_style="bold blue")
    t_samp.add_column("ID")
    t_samp.add_column("Artist")
    t_samp.add_column("Track")
    t_samp.add_column("Album")
    t_samp.add_column("Reason")
    for row in no_cands:
        t_samp.add_row(str(row['id']), str(row['artist_name']), str(row['track_name']), str(row['album_name']), str(row['reason']))
    console.print(t_samp)

    # 4. Check for 'below_threshold' misses - these are close calls
    print("\n--- 'Below Threshold' Misses (Close calls) ---")
    close_calls = await conn.fetch("""
        SELECT s.artist_name, s.track_name, m.candidate_artist, m.candidate_track, m.candidate_score
        FROM lastfm_scrobble_miss m
        JOIN lastfm_scrobble s ON m.scrobble_id = s.id
        WHERE m.reason = 'below_threshold'
        ORDER BY m.candidate_score DESC
        LIMIT 20
    """)
    t_close = Table(show_header=True, header_style="bold yellow")
    t_close.add_column("Scrobble")
    t_close.add_column("Candidate")
    t_close.add_column("Score")
    for row in close_calls:
        scrob = f"{row['artist_name']} - {row['track_name']}"
        cand = f"{row['candidate_artist']} - {row['candidate_track']}"
        t_close.add_row(scrob, cand, f"{row['candidate_score']:.4f}")
    console.print(t_close)

    await conn.close()

if __name__ == "__main__":
    asyncio.run(run())
