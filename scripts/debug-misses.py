
import asyncio
import os
import asyncpg
from rich.console import Console
from rich.table import Table

console = Console()

async def main():
    db_host = os.environ.get("DB_HOST", "127.0.0.1")
    db_port = int(os.environ.get("DB_PORT", "8110"))
    db_user = os.environ.get("DB_USER", "jamarr")
    db_pass = os.environ.get("DB_PASS", "jamarr")
    db_name = os.environ.get("DB_NAME", "jamarr")

    conn = await asyncpg.connect(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_pass,
        database=db_name,
    )

    try:
        # Fetch misses for P!nk
        misses = await conn.fetch("""
            SELECT m.scrobble_id, m.reason, s.artist_name, s.track_name, s.album_name
            FROM lastfm_scrobble_miss m
            JOIN lastfm_scrobble s ON s.id = m.scrobble_id
            LEFT JOIN lastfm_scrobble_match sm ON sm.scrobble_id = m.scrobble_id
            WHERE sm.scrobble_id IS NULL
            ORDER BY m.attempted_at DESC
            LIMIT 20
        """)

        console.print("[bold red]Recent Misses (Filtered):[/bold red]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("ID")
        table.add_column("Artist")
        table.add_column("Track")
        table.add_column("Album")
        table.add_column("Reason")

        for row in misses:
            table.add_row(
                str(row['scrobble_id']),
                row['artist_name'],
                row['track_name'],
                row['album_name'] or "",
                row['reason']
            )
        console.print(table)

        import unicodedata
        import re

        def _normalize_basic(value):
            if not value: return ""
            value = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
            value = value.lower()
            value = value.replace("&", "and").replace("+", "and")
            # Remove common tokens
            tokens_to_remove = ["reissue", "version", "single", "original", "acoustic", "live", "mix", "album", "remix"]
            for token in tokens_to_remove:
                value = re.sub(r'\b' + re.escape(token) + r'\b', '', value)
            value = value.replace("’", "'")
            value = re.sub(r"[^a-z0-9]+", " ", value)
            return " ".join(value.split())

        def normalize_title(value):
             if not value: return ""
             stripped = value # match-lastfm logic simplified for check
             # copy relevant parts from match-lastfm.py if needed, but basic norm is usually the culprit
             return _normalize_basic(stripped)

        # For each miss, check if there were candidates
        for row in misses:
            scrobble_id = row['scrobble_id']
            # Re-fetch candidates
            candidates = await conn.fetch("""
                SELECT c.track_id, c.score, c.method, c.reason,
                       t.artist, t.title, t.album
                FROM lastfm_match_candidate c
                JOIN track t ON t.id = c.track_id
                WHERE c.scrobble_id = $1
                ORDER BY c.score DESC
            """, scrobble_id)

            if candidates:
                console.print(f"\n[bold yellow]Candidates for Scrobble {scrobble_id}:[/bold yellow]")
                c_table = Table(show_header=True, header_style="bold blue")
                c_table.add_column("Details")
                c_table.add_column("Norm Check")

                sc_artist = row['artist_name']
                sc_title = row['track_name']
                sc_norm_title = normalize_title(sc_title)
                
                console.print(f"Scrobble: {sc_artist} - {sc_title}")
                console.print(f"Scrobble Norm Title: '{sc_norm_title}'")

                for c in candidates:
                    c_norm_title = normalize_title(c['title'])
                    match = (sc_norm_title == c_norm_title)
                    
                    details = (
                        f"ID: {c['track_id']}\n"
                        f"Score: {c['score']:.4f}\n"
                        f"Method: {c['method']}\n"
                        f"Artist: {c['artist']}\n"
                        f"Title: {c['title']}\n"
                        f"Reason: {c['reason']}"
                    )
                    
                    norm_check = (
                         f"Cand Title: '{c['title']}'\n"
                         f"Cand Norm:  '{c_norm_title}'\n"
                         f"Match: {match}"
                    )
                    
                    c_table.add_row(details, norm_check)
                console.print(c_table)
            else:
                 console.print(f"\n[bold yellow]No candidates for Scrobble {scrobble_id}[/bold yellow]")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
