#!/usr/bin/env python
"""
Interactive reviewer for Last.fm match candidates.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

import asyncpg
import httpx
from rich.console import Console
from rich.table import Table

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

console = Console()


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


async def ensure_tables(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lastfm_match_candidate (
            id BIGSERIAL PRIMARY KEY,
            scrobble_id BIGINT NOT NULL,
            track_id BIGINT NOT NULL,
            score DOUBLE PRECISION NOT NULL,
            method TEXT NOT NULL,
            reason TEXT,
            rank INTEGER,
            cache_key TEXT,
            candidate_artist TEXT,
            candidate_album TEXT,
            candidate_track TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(scrobble_id, track_id),
            FOREIGN KEY(scrobble_id) REFERENCES lastfm_scrobble(id) ON DELETE CASCADE,
            FOREIGN KEY(track_id) REFERENCES track(id) ON DELETE CASCADE
        );
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lastfm_match_feedback (
            id BIGSERIAL PRIMARY KEY,
            scrobble_id BIGINT NOT NULL,
            track_id BIGINT NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('accept', 'reject')),
            notes TEXT,
            cache_key TEXT,
            reviewed_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(scrobble_id, track_id, decision),
            FOREIGN KEY(scrobble_id) REFERENCES lastfm_scrobble(id) ON DELETE CASCADE,
            FOREIGN KEY(track_id) REFERENCES track(id) ON DELETE CASCADE
        );
        """
    )
    await conn.execute(
        "ALTER TABLE lastfm_match_candidate ADD COLUMN IF NOT EXISTS cache_key TEXT"
    )
    await conn.execute(
        "ALTER TABLE lastfm_match_feedback ADD COLUMN IF NOT EXISTS cache_key TEXT"
    )


async def get_next_scrobble(
    conn: asyncpg.Connection, username: str
) -> Optional[asyncpg.Record]:
    return await conn.fetchrow(
        """
        SELECT DISTINCT ON (COALESCE(c.cache_key, 'scrobble:' || s.id::text))
            s.id,
            s.played_at,
            s.artist_name,
            s.track_name,
            s.album_name,
            COALESCE(c.cache_key, 'scrobble:' || s.id::text) AS group_key
        FROM lastfm_scrobble s
        JOIN lastfm_match_candidate c ON c.scrobble_id = s.id
        LEFT JOIN lastfm_match_feedback f
          ON f.cache_key = COALESCE(c.cache_key, 'scrobble:' || s.id::text)
        WHERE s.lastfm_username = $1
          AND f.cache_key IS NULL
        ORDER BY COALESCE(c.cache_key, 'scrobble:' || s.id::text), s.played_at DESC
        """,
        username,
    )


async def get_candidates(
    conn: asyncpg.Connection, scrobble_id: int
) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT c.track_id, c.score, c.method, c.reason, c.rank,
               t.artist, t.title, t.album, t.album_artist, t.release_type
        FROM lastfm_match_candidate c
        JOIN track t ON t.id = c.track_id
        WHERE c.scrobble_id = $1
        ORDER BY c.score DESC, c.rank ASC
        """,
        scrobble_id,
    )


async def get_existing_match(
    conn: asyncpg.Connection, scrobble_id: int
) -> Optional[asyncpg.Record]:
    return await conn.fetchrow(
        """
        SELECT m.track_id, m.match_score, m.match_method, m.match_reason,
               t.artist, t.title, t.album, t.album_artist, t.release_type
        FROM lastfm_scrobble_match m
        JOIN track t ON t.id = m.track_id
        WHERE m.scrobble_id = $1
        """,
        scrobble_id,
    )


async def record_feedback(
    conn: asyncpg.Connection,
    scrobble_id: int,
    track_id: int,
    decision: str,
    notes: Optional[str] = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO lastfm_match_feedback
            (scrobble_id, track_id, decision, notes, cache_key)
        VALUES
            (
                $1,
                $2,
                $3,
                $4,
                COALESCE(
                    (SELECT cache_key FROM lastfm_match_candidate
                     WHERE scrobble_id = $1 LIMIT 1),
                    'scrobble:' || $1::text
                )
            )
        ON CONFLICT (scrobble_id, track_id, decision) DO UPDATE SET
            notes = EXCLUDED.notes,
            cache_key = EXCLUDED.cache_key,
            reviewed_at = NOW()
        """,
        scrobble_id,
        track_id,
        decision,
        notes,
    )


async def apply_match(
    conn: asyncpg.Connection,
    scrobble_id: int,
    track_id: int,
) -> None:
    await conn.execute(
        """
        INSERT INTO lastfm_scrobble_match
            (scrobble_id, track_id, match_score, match_method, match_reason, match_version)
        VALUES
            ($1, $2, 1.0, 'manual', 'review_accept', 'manual')
        ON CONFLICT (scrobble_id) DO UPDATE SET
            track_id = EXCLUDED.track_id,
            match_score = EXCLUDED.match_score,
            match_method = EXCLUDED.match_method,
            match_reason = EXCLUDED.match_reason,
            match_version = EXCLUDED.match_version,
            matched_at = NOW()
        """,
        scrobble_id,
        track_id,
    )


def render_scrobble(scrobble: asyncpg.Record) -> None:
    console.print(
        f"[bold]Scrobble {scrobble['id']}[/bold] "
        f"{scrobble['played_at']} — {scrobble['artist_name']} "
        f"• {scrobble['track_name']} • {scrobble['album_name'] or '-'}"
    )


def render_candidates(
    candidates: list[asyncpg.Record], existing_track_id: Optional[int]
) -> None:
    table = Table(title="Candidates")
    table.add_column("#", justify="right")
    table.add_column("Track ID", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Method")
    table.add_column("Artist")
    table.add_column("Title")
    table.add_column("Album")
    table.add_column("Album Artist")
    table.add_column("Type")
    for idx, row in enumerate(candidates, start=1):
        style = "magenta" if existing_track_id == row["track_id"] else ""
        table.add_row(
            str(idx),
            str(row["track_id"]),
            f"{row['score']:.2f}",
            row["method"],
            row["artist"] or "",
            row["title"] or "",
            row["album"] or "",
            row["album_artist"] or "",
            row["release_type"] or "",
            style=style,
        )
    console.print(table)


def render_existing(match: asyncpg.Record) -> None:
    console.print(
        f"[yellow]Existing match[/yellow] {match['track_id']} "
        f"{match['artist']} • {match['title']} • {match['album']} "
        f"(score {match['match_score']}, {match['match_method']})"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review and confirm Last.fm match candidates.",
    )
    parser.add_argument("--user", default="darious1472", help="Last.fm username")
    parser.add_argument(
        "--auto-pass",
        action="store_true",
        help="Auto-accept obvious matches and exit",
    )
    parser.add_argument(
        "--auto-limit",
        type=int,
        default=200,
        help="Max scrobbles to auto-review per run",
    )
    parser.add_argument(
        "--ollama",
        action="store_true",
        help="Use Ollama to auto-review candidates",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://192.168.0.22:11434",
        help="Ollama base URL",
    )
    parser.add_argument(
        "--ollama-model",
        default="mistral-nemo:12b-instruct-2407-fp16",
        help="Ollama model name",
    )
    parser.add_argument(
        "--ollama-limit",
        type=int,
        default=100,
        help="Max scrobbles to send to Ollama per run",
    )
    return parser


async def run(args: argparse.Namespace) -> None:
    load_dotenv(ROOT / ".env")

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
        await ensure_tables(conn)
        if args.ollama:
            processed = 0
            accepted = 0
            rejected = 0
            client = httpx.Client(timeout=60.0)
            try:
                while processed < args.ollama_limit:
                    scrobble = await get_next_scrobble(conn, args.user)
                    if not scrobble:
                        break
                    candidates = await get_candidates(conn, scrobble["id"])
                    if not candidates:
                        break
                    processed += 1
                    prompt_lines = [
                        "You are a music librarian. Pick the best matching local track for the scrobble below.",
                        'If none are a real match, respond with {"decision":"reject_all","reason":"..."}.',
                        'Otherwise respond with {"decision":"accept","track_id":<id>,"reason":"..."}.',
                        "Only output JSON. No extra text.",
                        "",
                        "Scrobble:",
                        f'artist: "{scrobble["artist_name"]}"',
                        f'title: "{scrobble["track_name"]}"',
                        f'album: "{scrobble["album_name"] or ""}"',
                        "",
                        "Candidates:",
                    ]
                    for idx, row in enumerate(candidates, start=1):
                        prompt_lines.append(
                            f'{idx}) track_id={row["track_id"]} | artist="{row["artist"]}" | '
                            f'title="{row["title"]}" | album="{row["album"]}" | '
                            f'album_artist="{row["album_artist"]}" | type="{row["release_type"]}"'
                        )
                    prompt = "\n".join(prompt_lines)
                    resp = client.post(
                        f"{args.ollama_url}/api/generate",
                        json={
                            "model": args.ollama_model,
                            "prompt": prompt,
                            "stream": False,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    answer = (data.get("response") or "").strip()
                    if not answer:
                        continue
                    try:
                        import json

                        parsed = json.loads(answer)
                    except json.JSONDecodeError:
                        continue
                    if parsed.get("decision") == "accept":
                        track_id = int(parsed.get("track_id"))
                        await record_feedback(
                            conn, scrobble["id"], track_id, "accept", "ollama"
                        )
                        await apply_match(conn, scrobble["id"], track_id)
                        accepted += 1
                        continue
                    if parsed.get("decision") == "reject_all":
                        for row in candidates:
                            await record_feedback(
                                conn,
                                scrobble["id"],
                                row["track_id"],
                                "reject",
                                "ollama",
                            )
                        rejected += 1
                        continue
                console.print(
                    f"[green]Ollama review complete[/green]: processed {processed}, "
                    f"accepted {accepted}, rejected {rejected}."
                )
                return
            finally:
                client.close()

        if args.auto_pass:
            processed = 0
            accepted = 0
            rejected = 0
            while processed < args.auto_limit:
                scrobble = await get_next_scrobble(conn, args.user)
                if not scrobble:
                    break
                existing = await get_existing_match(conn, scrobble["id"])
                candidates = await get_candidates(conn, scrobble["id"])
                processed += 1
                if candidates:
                    all_partial = all(row["method"] == "name_partial" for row in candidates)
                    max_score = max(float(row["score"]) for row in candidates)
                    any_title_match = any("track_name" in (row["reason"] or "") for row in candidates)
                    if all_partial and not any_title_match and max_score <= 0.9:
                        for row in candidates:
                            await record_feedback(
                                conn,
                                scrobble["id"],
                                row["track_id"],
                                "reject",
                                "auto_reject_no_title_match",
                            )
                        rejected += 1
                        continue
                if existing:
                    if existing["match_method"] == "mbid_track" or (
                        existing["match_score"] is not None
                        and existing["match_score"] >= 0.98
                    ):
                        track_id = existing["track_id"]
                        await record_feedback(
                            conn, scrobble["id"], track_id, "accept", "auto_pass"
                        )
                        await apply_match(conn, scrobble["id"], track_id)
                        accepted += 1
                        continue
                if candidates:
                    top = candidates[0]
                    second = candidates[1] if len(candidates) > 1 else None
                    top_score = float(top["score"])
                    second_score = float(second["score"]) if second else None
                    if top["method"] in ("mbid_track", "mbid_artist_release"):
                        await record_feedback(
                            conn, scrobble["id"], top["track_id"], "accept", "auto_pass"
                        )
                        await apply_match(conn, scrobble["id"], top["track_id"])
                        accepted += 1
                        continue
                    if top_score >= 0.98 and top["method"] in (
                        "name_artist_album",
                        "name_artist_title",
                    ):
                        await record_feedback(
                            conn, scrobble["id"], top["track_id"], "accept", "auto_pass"
                        )
                        await apply_match(conn, scrobble["id"], top["track_id"])
                        accepted += 1
                        continue
                    if (
                        top_score >= 0.95
                        and second_score is not None
                        and (top_score - second_score) >= 0.1
                    ):
                        await record_feedback(
                            conn, scrobble["id"], top["track_id"], "accept", "auto_pass"
                        )
                        await apply_match(conn, scrobble["id"], top["track_id"])
                        accepted += 1
                        continue
            console.print(
                f"[green]Auto-pass complete[/green]: processed {processed}, "
                f"accepted {accepted}, rejected {rejected}."
            )
            return

        while True:
            scrobble = await get_next_scrobble(conn, args.user)
            if not scrobble:
                console.print("[green]No scrobbles left in review queue.[/green]")
                return
            render_scrobble(scrobble)
            existing = await get_existing_match(conn, scrobble["id"])
            existing_track_id = existing["track_id"] if existing else None
            if existing:
                render_existing(existing)
            candidates = await get_candidates(conn, scrobble["id"])
            if not candidates:
                console.print("[yellow]No candidates for this scrobble.[/yellow]")
                await record_feedback(
                    conn, scrobble["id"], 0, "reject", "no_candidates"
                )
                continue
            render_candidates(candidates, existing_track_id)
            console.print(
                "Enter: [green]1-9[/green] accept candidate by index, "
                "[green]a[/green] accept existing match, "
                "[red]r[/red] reject all candidates, "
                "[yellow]s[/yellow] skip, [cyan]q[/cyan] quit"
            )
            choice = input("> ").strip()
            if not choice:
                if not existing:
                    console.print("[yellow]No existing match to accept.[/yellow]")
                    continue
                track_id = existing["track_id"]
                await record_feedback(conn, scrobble["id"], track_id, "accept")
                await apply_match(conn, scrobble["id"], track_id)
                console.print(f"[green]Accepted existing {track_id}[/green]")
                continue
            if choice.lower() == "q":
                return
            if choice.lower() == "s":
                continue
            if choice.lower() == "a":
                if not existing:
                    console.print("[yellow]No existing match to accept.[/yellow]")
                    continue
                track_id = existing["track_id"]
                await record_feedback(conn, scrobble["id"], track_id, "accept")
                await apply_match(conn, scrobble["id"], track_id)
                console.print(f"[green]Accepted existing {track_id}[/green]")
                continue
            if choice.lower() == "r":
                for row in candidates:
                    await record_feedback(conn, scrobble["id"], row["track_id"], "reject")
                console.print("[red]Rejected all candidates[/red]")
                continue
            if choice.isdigit():
                idx = int(choice)
                if idx < 1 or idx > len(candidates):
                    console.print("[yellow]Invalid index.[/yellow]")
                    continue
                track_id = candidates[idx - 1]["track_id"]
                await record_feedback(conn, scrobble["id"], track_id, "accept")
                await apply_match(conn, scrobble["id"], track_id)
                console.print(f"[green]Accepted {track_id}[/green]")
                continue
            console.print("[yellow]Unknown command.[/yellow]")
    finally:
        await conn.close()


def main() -> None:
    args = build_parser().parse_args()
    try:
        import asyncio

        asyncio.run(run(args))
    except KeyboardInterrupt:
        console.print("Interrupted.")


if __name__ == "__main__":
    main()
