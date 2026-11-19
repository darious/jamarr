"""Reload a user's Last.fm history into ListenBrainz.

One-off migration tool. It sends every stored Last.fm scrobble from before the
user's ListenBrainz cutover (``user.listenbrainz_since``) as ``import`` listens.
Plays from the cutover on reach ListenBrainz through the submission queue
(local plays) or straight from other scrobblers, so nothing is sent twice.

- Names are sent exactly as Last.fm recorded them.
- MusicBrainz IDs come from Jamarr's own match, and only where the match is
  confident: matched on Last.fm's track MBID, or on artist + title + album.
  Weaker matches and unmatched scrobbles go by name and ListenBrainz maps
  them itself.
- Duplicate scrobbles are dropped. Two scrobbles of the same track closer
  together than Last.fm's own scrobble rule allows (half the track, at most
  4 minutes) cannot both be listens, so one is kept: the earlier one, or the
  one that lines up with a Jamarr play.

Run inside the server container (it reads the same DB_* environment):

    uv run python -m app.listenbrainz_import --user NAME --dry-run --report /tmp/lb-import
    uv run python -m app.listenbrainz_import --user NAME --cutover 2026-11-28T09:00:00Z
    uv run python -m app.listenbrainz_import --user NAME            # send
    uv run python -m app.listenbrainz_import --user NAME --after UTS  # resume

The user must have connected ListenBrainz in Settings first.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import asyncpg

from app import listenbrainz as lb
from app.version import __version__

logger = logging.getLogger("listenbrainz_import")

BATCH_SIZE = 1000
MAX_RETRIES = 8
# Match methods whose MBIDs are trusted enough to send to ListenBrainz.
RECORDING_METHODS = {"mbid_track", "name_artist_album"}
# Last.fm counts a scrobble after half the track, or 4 minutes if sooner.
SCROBBLE_RULE_CAP_SECONDS = 240
# Unmatched scrobbles have no known duration; treat repeats this close as one.
UNMATCHED_DUPLICATE_SECONDS = 30
# A Jamarr play this close to a scrobble of the same track is that scrobble.
LOCAL_PLAY_WINDOW_SECONDS = 5

ROWS_SQL = """
    SELECT ls.id, ls.played_at, ls.played_at_uts, ls.artist_name, ls.track_name,
           ls.album_name,
           m.track_id, m.match_method, m.match_score,
           t.album AS track_album, t.duration_seconds, t.artist_mbid,
           t.track_mbid, t.release_mbid, t.release_group_mbid, t.release_track_mbid,
           (m.track_id IS NOT NULL AND EXISTS (
               SELECT 1 FROM playback_history ph
               WHERE ph.track_id = m.track_id
                 AND ph."timestamp" BETWEEN ls.played_at - make_interval(secs => $3)
                                        AND ls.played_at + make_interval(secs => $3)
           )) AS jamarr_play
    FROM lastfm_scrobble ls
    LEFT JOIN lastfm_scrobble_match m ON m.scrobble_id = ls.id
    LEFT JOIN track t ON t.id = m.track_id
    WHERE ls.lastfm_username = $1
      AND ls.played_at < $2
    ORDER BY ls.played_at, ls.id
"""


@dataclass
class Plan:
    listens: list[dict] = field(default_factory=list)
    uts: list[int] = field(default_factory=list)
    duplicates: list[tuple[dict, dict]] = field(default_factory=list)  # (dropped, kept)
    skipped_empty: list[dict] = field(default_factory=list)
    with_recording: int = 0
    with_release: int = 0


def _uts(row: dict) -> int:
    if row.get("played_at_uts"):
        return int(row["played_at_uts"])
    return int(row["played_at"].timestamp())


def _duplicate_key(row: dict) -> str:
    if row.get("track_id"):
        return f"t{row['track_id']}"
    return "n" + (row.get("artist_name") or "").strip().lower() + "\x1f" + (
        row.get("track_name") or ""
    ).strip().lower()


def _duplicate_window(row: dict) -> float:
    duration = row.get("duration_seconds")
    if row.get("track_id") and duration and duration > 0:
        return min(float(duration) / 2, SCROBBLE_RULE_CAP_SECONDS)
    return UNMATCHED_DUPLICATE_SECONDS


def drop_duplicates(rows: Sequence[dict]) -> tuple[list[dict], list[tuple[dict, dict]]]:
    """Return (kept rows in time order, [(dropped, kept_instead)])."""
    by_key: dict[str, list[dict]] = {}
    for row in rows:
        by_key.setdefault(_duplicate_key(row), []).append(row)

    dropped: list[tuple[dict, dict]] = []
    kept_ids: set[int] = set()
    for group in by_key.values():
        group.sort(key=lambda r: (_uts(r), r["id"]))
        last: Optional[dict] = None
        for row in group:
            if last is not None and _uts(row) - _uts(last) < _duplicate_window(row):
                if row.get("jamarr_play") and not last.get("jamarr_play"):
                    # The later scrobble is Jamarr's own: keep it instead.
                    kept_ids.discard(last["id"])
                    dropped.append((last, row))
                    kept_ids.add(row["id"])
                    last = row
                else:
                    dropped.append((row, last))
                continue
            kept_ids.add(row["id"])
            last = row
    kept = [row for row in rows if row["id"] in kept_ids]
    return kept, dropped


def build_import_listen(row: dict) -> Optional[dict]:
    """A ListenBrainz listen for one stored scrobble, or None if it has no names."""
    artist = (row.get("artist_name") or "").strip()
    title = (row.get("track_name") or "").strip()
    if not artist or not title:
        return None

    info: dict[str, Any] = {
        "submission_client": lb.SUBMISSION_CLIENT,
        "submission_client_version": __version__,
    }
    method = row.get("match_method")
    album = (row.get("album_name") or "").strip()
    if row.get("track_id") and method in RECORDING_METHODS:
        metadata_with_mbids = lb.build_track_metadata(
            {
                "artist": artist,
                "title": title,
                "artist_mbid": row.get("artist_mbid"),
                "track_mbid": row.get("track_mbid"),
                "release_mbid": row.get("release_mbid"),
                "release_group_mbid": row.get("release_group_mbid"),
                "release_track_mbid": row.get("release_track_mbid"),
            }
        )
        mbids = metadata_with_mbids["additional_info"] if metadata_with_mbids else {}
        for key in ("artist_mbids", "recording_mbid"):
            if key in mbids:
                info[key] = mbids[key]
        # The release is only known when the album matched too: a track MBID
        # match says nothing about which release was playing.
        album_matches = method == "name_artist_album" or (
            album and album.casefold() == (row.get("track_album") or "").strip().casefold()
        )
        if album_matches:
            for key in ("release_mbid", "release_group_mbid", "track_mbid"):
                if key in mbids:
                    info[key] = mbids[key]

    metadata: dict[str, Any] = {
        "artist_name": artist,
        "track_name": title,
        "additional_info": info,
    }
    if album:
        metadata["release_name"] = album
    return {"listened_at": _uts(row), "track_metadata": metadata}


def build_plan(rows: Sequence[dict]) -> Plan:
    plan = Plan()
    kept, plan.duplicates = drop_duplicates(rows)
    for row in kept:
        listen = build_import_listen(row)
        if listen is None:
            plan.skipped_empty.append(row)
            continue
        info = listen["track_metadata"]["additional_info"]
        plan.with_recording += "recording_mbid" in info
        plan.with_release += "release_mbid" in info
        plan.listens.append(listen)
        plan.uts.append(listen["listened_at"])
    return plan


async def load_rows(db: asyncpg.Connection, lastfm_username: str, before: datetime) -> list[dict]:
    rows = await db.fetch(ROWS_SQL, lastfm_username, before, float(LOCAL_PLAY_WINDOW_SECONDS))
    return [dict(r) for r in rows]


def write_report(plan: Plan, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "duplicates.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["dropped_played_at", "kept_played_at", "gap_s", "artist", "track", "album",
             "dropped_was_jamarr", "kept_was_jamarr"]
        )
        for dropped, kept in sorted(plan.duplicates, key=lambda p: _uts(p[0])):
            writer.writerow(
                [dropped["played_at"].isoformat(), kept["played_at"].isoformat(),
                 abs(_uts(dropped) - _uts(kept)), dropped["artist_name"],
                 dropped["track_name"], dropped.get("album_name") or "",
                 bool(dropped.get("jamarr_play")), bool(kept.get("jamarr_play"))]
            )
    sample = plan.listens[:: max(1, len(plan.listens) // 25)][:25]
    (directory / "sample_listens.json").write_text(json.dumps(sample, indent=2, default=str))


async def send(
    client: lb.ListenBrainzClient,
    token: str,
    plan: Plan,
    after: int = 0,
    sleep=asyncio.sleep,
    out=print,
) -> tuple[int, list[dict]]:
    """Submit the plan in time order. Returns (sent, rejected listens)."""
    pending = [listen for listen in plan.listens if listen["listened_at"] > after]
    sent = 0
    rejected: list[dict] = []

    async def submit(batch: list[dict]) -> None:
        nonlocal sent
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await client.submit_listens(
                    token, "single" if len(batch) == 1 else "import", batch
                )
                sent += len(batch)
                return
            except lb.ListenBrainzRejectedError:
                if len(batch) == 1:
                    rejected.append(batch[0])
                    return
                mid = len(batch) // 2
                await submit(batch[:mid])
                await submit(batch[mid:])
                return
            except lb.ListenBrainzRateLimitedError as exc:
                wait = exc.retry_after
            except lb.ListenBrainzAuthError:
                raise
            except lb.ListenBrainzError as exc:
                wait = min(300.0, 5.0 * 2 ** (attempt - 1))
                out(f"  ListenBrainz error ({exc}); retrying in {wait:.0f}s")
            if attempt == MAX_RETRIES:
                raise RuntimeError("ListenBrainz kept failing")
            await sleep(wait)

    total = len(pending)
    for start in range(0, total, BATCH_SIZE):
        batch = pending[start : start + BATCH_SIZE]
        try:
            await submit(batch)
        except Exception:
            last_ok = pending[start - 1]["listened_at"] if start else after
            out(f"Stopped. Resume with --after {last_ok}")
            raise
        last = batch[-1]["listened_at"]
        when = datetime.fromtimestamp(last, timezone.utc).date().isoformat()
        out(f"  {min(start + BATCH_SIZE, total)}/{total} up to {when} (--after {last})")
    return sent, rejected


async def run(args: argparse.Namespace, db: asyncpg.Connection, client=None, out=print) -> int:
    user = await db.fetchrow(
        """
        SELECT id, username, lastfm_username, listenbrainz_token, listenbrainz_username,
               listenbrainz_since
        FROM "user" WHERE username = $1
        """,
        args.user,
    )
    if user is None:
        out(f"No Jamarr user {args.user!r}")
        return 2
    if not user["lastfm_username"]:
        out("That user has no Last.fm account, so there is nothing to import")
        return 2
    if not user["listenbrainz_token"] and not args.dry_run:
        out("Connect ListenBrainz in Settings first")
        return 2

    cutover = user["listenbrainz_since"]
    if args.cutover:
        cutover = datetime.fromisoformat(args.cutover.replace("Z", "+00:00"))
        if cutover.tzinfo is None:
            cutover = cutover.replace(tzinfo=timezone.utc)
        if not args.dry_run:
            await db.execute(
                'UPDATE "user" SET listenbrainz_since = $1 WHERE id = $2', cutover, user["id"]
            )
            out(f"Cutover set: local plays from {cutover.isoformat()} go through the queue")
    if cutover is None:
        out("No cutover: pass --cutover with the time ListenBrainz was wiped")
        return 2

    last_sync = await db.fetchval(
        """
        SELECT MAX(r.started_at) FROM scheduled_task_run r
        JOIN scheduled_task t ON t.id = r.task_id
        WHERE t.job_key = 'lastfm_sync' AND r.status = 'success'
        """
    )
    if last_sync is None or last_sync < cutover:
        out(
            "Warning: no successful Last.fm sync since the cutover, so scrobbles from "
            "just before it may be missing. Run a sync first if Last.fm still works."
        )

    rows = await load_rows(db, user["lastfm_username"], cutover)
    plan = build_plan(rows)
    first = plan.listens[0]["listened_at"] if plan.listens else None
    last = plan.listens[-1]["listened_at"] if plan.listens else None
    out(f"Last.fm scrobbles before {cutover.isoformat()}: {len(rows)}")
    out(f"  duplicates dropped: {len(plan.duplicates)}")
    out(f"  without artist/title, skipped: {len(plan.skipped_empty)}")
    span = ""
    if first is not None and last is not None:
        span = (f" ({datetime.fromtimestamp(first, timezone.utc).date()} .. "
                f"{datetime.fromtimestamp(last, timezone.utc).date()})")
    out(f"  to send: {len(plan.listens)}{span}")
    out(f"  with recording MBID: {plan.with_recording}, with release MBID: {plan.with_release}")
    if args.report:
        write_report(plan, Path(args.report))
        out(f"Report written to {args.report}")
    if args.dry_run:
        return 0

    client = client or lb.get_client()
    out(f"Sending to ListenBrainz as {user['listenbrainz_username']}...")
    sent, rejected = await send(client, user["listenbrainz_token"], plan, after=args.after or 0, out=out)
    out(f"Sent {sent} listens; ListenBrainz refused {len(rejected)}")
    for listen in rejected[:20]:
        md = listen["track_metadata"]
        out(f"  refused: {listen['listened_at']} {md['artist_name']} - {md['track_name']}")
    out(
        "ListenBrainz processes imports in the background; its listen count "
        "catches up over a few minutes."
    )
    return 0 if not rejected else 1


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", required=True, help="Jamarr username")
    parser.add_argument("--cutover", help="ISO time ListenBrainz was wiped; sets the user's cutover")
    parser.add_argument("--dry-run", action="store_true", help="plan and report only, send nothing")
    parser.add_argument("--report", help="directory for duplicates.csv and sample_listens.json")
    parser.add_argument("--after", type=int, default=0, help="resume: skip listens at or before this unix time")
    return parser.parse_args(argv)


async def _main(argv: Optional[Sequence[str]] = None) -> int:
    from app.db import DB_HOST, DB_NAME, DB_PASS, DB_PORT, DB_USER

    args = parse_args(argv)
    db = await asyncpg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, database=DB_NAME
    )
    try:
        return await run(args, db)
    finally:
        await db.close()
        await lb.close_client()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(asyncio.run(_main()))
