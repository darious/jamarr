#!/usr/bin/env python3
"""Before/after harness for the Last.fm scrobble matcher.

Takes a read-only snapshot of the tables the matcher reads, loads it into a
throwaway Postgres container, runs the real re-match path
(``app.lastfm_archive.match_archive`` with ``rematch_all``) against that copy, and
exports every scrobble's match. Two runs can then be diffed: which scrobbles
moved to another track, which became (un)matched, and how the regression
metrics changed.

Subcommands: snapshot, up, load, run, subset, diff, down. See README.md.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import gzip
import json
import os
import shlex
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DEFAULT_WORKDIR = Path(
    os.environ.get("MATCH_EVAL_DIR", Path.home() / ".cache" / "jamarr" / "match-eval")
)
CONTAINER = "jamarr_match_eval"
IMAGE = "postgres:18.1-alpine"  # same as docker-compose.yml
PORT = int(os.environ.get("MATCH_EVAL_PORT", "8115"))
PG_USER = "jamarr"
PG_PASS = "match_eval"
PG_DB = "jamarr"
DSN = f"postgresql://{PG_USER}:{PG_PASS}@127.0.0.1:{PORT}/{PG_DB}"

# Everything the matcher and the history view read. "user" is left out on
# purpose (password hashes, Last.fm session keys): load() recreates its rows
# from users.csv with placeholder credentials.
DATA_TABLES = [
    "artist",
    "track",
    "track_artist",
    "lastfm_scrobble",
    "lastfm_scrobble_match",
    "lastfm_skip_artist",
    "playback_history",
]
USERS_SQL = (
    'COPY (SELECT id, username, lastfm_username FROM "user" '
    "WHERE lastfm_username IS NOT NULL AND lastfm_username <> '') "
    "TO STDOUT WITH CSV HEADER;\n"
)
MARKER_TABLE = "match_eval_marker"
AS_FOUND = "as-found"

EXPORT_SQL = """
SELECT s.id AS scrobble_id, s.lastfm_username, s.played_at,
       s.artist_name, s.track_name, s.album_name, s.album_mbid, s.track_mbid,
       m.track_id, t.artist AS matched_artist, t.title AS matched_title,
       t.album AS matched_album, t.release_mbid AS matched_release_mbid,
       m.match_score, m.match_method, m.match_reason
FROM lastfm_scrobble s
LEFT JOIN lastfm_scrobble_match m ON m.scrobble_id = s.id
LEFT JOIN track t ON t.id = m.track_id
ORDER BY s.id
"""
EXPORT_COLUMNS = [
    "scrobble_id", "lastfm_username", "played_at", "artist_name", "track_name",
    "album_name", "album_mbid", "track_mbid", "track_id", "matched_artist",
    "matched_title", "matched_album", "matched_release_mbid", "match_score",
    "match_method", "match_reason",
]

# Regression metrics: each query returns the ids of suspect scrobbles, and the
# metric is their count (lower is better). From the issue #366 investigation.
_VERSION_WORDS = "live|acoustic|remix|mix|edit|version|session|demo|instrumental|unplugged"
def _same_album(t: str) -> str:
    """SQL: track alias t is on the album the scrobble s names (by release
    MBID, or by name ignoring case and punctuation)."""
    return (
        f"({t}.release_mbid = s.album_mbid OR (s.album_name <> '' AND "
        f"regexp_replace(lower({t}.album), '[^[:alnum:]]+', '', 'g') = "
        f"regexp_replace(lower(s.album_name), '[^[:alnum:]]+', '', 'g')))"
    )


METRICS: Dict[str, Tuple[str, str]] = {
    "wrong_release": (
        "Scrobbles whose album_mbid names a library release holding a track of "
        "the same title, but which are matched to another release",
        """
        SELECT s.id FROM lastfm_scrobble s
        JOIN lastfm_scrobble_match m ON m.scrobble_id = s.id
        JOIN track t ON t.id = m.track_id
        WHERE s.album_mbid <> '' AND t.release_mbid IS DISTINCT FROM s.album_mbid
          AND EXISTS (SELECT 1 FROM track o WHERE o.release_mbid = s.album_mbid
                      AND lower(o.title) = lower(s.track_name))
        """,
    ),
    "version_collapse": (
        "Scrobbles of a labelled version (live, acoustic, edit, mix, demo, ...) "
        "matched to a differently titled track although the library has the "
        "exact title by that artist (unless only the other title is on the "
        "album the scrobble names)",
        f"""
        SELECT s.id FROM lastfm_scrobble s
        JOIN lastfm_scrobble_match m ON m.scrobble_id = s.id
        JOIN track t ON t.id = m.track_id
        WHERE lower(replace(t.title, '’', '''')) <> lower(replace(s.track_name, '’', ''''))
          AND s.track_name ~* '[\\(\\[-].*({_VERSION_WORDS})'
          AND EXISTS (SELECT 1 FROM track o
                      WHERE lower(replace(o.title, '’', '''')) = lower(replace(s.track_name, '’', ''''))
                        AND lower(o.artist) = lower(s.artist_name))
          AND NOT ({_same_album('t')} AND NOT EXISTS (
                SELECT 1 FROM track o
                WHERE lower(replace(o.title, '’', '''')) = lower(replace(s.track_name, '’', ''''))
                  AND lower(o.artist) = lower(s.artist_name) AND {_same_album('o')}))
        """,
    ),
    "version_drift": (
        "Scrobbles without a version label matched to a labelled version "
        "although the library has the exact title by that artist (the reverse "
        "of version_collapse, with the same album exception)",
        f"""
        SELECT s.id FROM lastfm_scrobble s
        JOIN lastfm_scrobble_match m ON m.scrobble_id = s.id
        JOIN track t ON t.id = m.track_id
        WHERE lower(replace(t.title, '’', '''')) <> lower(replace(s.track_name, '’', ''''))
          AND t.title ~* '[\\(\\[-].*({_VERSION_WORDS})'
          AND s.track_name !~* '[\\(\\[-].*({_VERSION_WORDS})'
          AND EXISTS (SELECT 1 FROM track o
                      WHERE lower(replace(o.title, '’', '''')) = lower(replace(s.track_name, '’', ''''))
                        AND lower(o.artist) = lower(s.artist_name))
          AND NOT ({_same_album('t')} AND NOT EXISTS (
                SELECT 1 FROM track o
                WHERE lower(replace(o.title, '’', '''')) = lower(replace(s.track_name, '’', ''''))
                  AND lower(o.artist) = lower(s.artist_name) AND {_same_album('o')}))
        """,
    ),
    "double_counted": (
        "History rows from Last.fm that coincide (same user, within 5 s) with a "
        "local play of a different track, so one play is counted twice",
        """
        SELECT m.scrobble_id FROM combined_playback_history_mat h
        JOIN lastfm_scrobble_match m ON m.id = h.source_id
        WHERE h.source = 'lastfm' AND EXISTS (
            SELECT 1 FROM playback_history p
            WHERE p.user_id = h.user_id AND p.track_id <> h.track_id
              AND p."timestamp" BETWEEN h.played_at - interval '5 seconds'
                                    AND h.played_at + interval '5 seconds')
        """,
    ),
}


# --------------------------------------------------------------------------
# helpers

def _log(msg: str) -> None:
    print(msg, flush=True)


def _git_state() -> Dict[str, object]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, text=True
        ).stdout.strip()

    return {"commit": git("rev-parse", "--short", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def _container_running() -> bool:
    out = subprocess.run(
        ["docker", "ps", "-q", "-f", f"name=^{CONTAINER}$"], capture_output=True, text=True
    )
    return bool(out.stdout.strip())


def _psql_container(sql: str, db: str = PG_DB) -> str:
    out = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "psql", "-U", PG_USER, "-d", db,
         "-v", "ON_ERROR_STOP=1", "-At"],
        input=sql, capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise SystemExit(f"psql failed: {out.stderr.strip()}")
    return out.stdout


def _snapshot_dir(workdir: Path, name: str) -> Path:
    path = workdir / "snapshots" / name
    if not (path / "schema.dump").exists():
        raise SystemExit(f"No snapshot at {path}")
    return path


def _run_dir(workdir: Path, label: str) -> Path:
    return workdir / "runs" / label


def _require_scratch() -> None:
    if not _container_running():
        raise SystemExit(f"Scratch DB container {CONTAINER} is not running (use: up, load)")


# --------------------------------------------------------------------------
# snapshot / up / load / down

def cmd_snapshot(args: argparse.Namespace) -> None:
    prefix = shlex.split(args.exec_prefix)
    name = args.name or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = args.workdir / "snapshots" / name
    if out.exists():
        raise SystemExit(f"{out} already exists")
    out.mkdir(parents=True)
    base = ["-U", args.db_user, "-d", args.db_name]

    def dump(target: Path, extra: List[str]) -> None:
        _log(f"Dumping {target.name} ...")
        with target.open("wb") as fh:
            proc = subprocess.run([*prefix, "pg_dump", *base, "-Fc", *extra], stdout=fh)
        if proc.returncode != 0:
            raise SystemExit(f"pg_dump failed for {target.name}")

    # Read-only on the source: pg_dump and a COPY TO STDOUT.
    dump(out / "schema.dump", ["--schema-only"])
    dump(out / "data.dump", ["--data-only", *[f"--table=public.{t}" for t in DATA_TABLES]])
    _log("Exporting Last.fm users (id, username, lastfm_username only) ...")
    proc = subprocess.run(
        [*prefix, "psql", *base, "-v", "ON_ERROR_STOP=1", "-q"],
        input=USERS_SQL, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"user export failed: {proc.stderr.strip()}")
    (out / "users.csv").write_text(proc.stdout)
    (out / "meta.json").write_text(json.dumps({
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "tables": DATA_TABLES,
    }, indent=2))
    size = sum(p.stat().st_size for p in out.iterdir()) / 1e6
    _log(f"Snapshot {name}: {out} ({size:.0f} MB)")


def cmd_up(args: argparse.Namespace) -> None:
    if _container_running():
        _log(f"{CONTAINER} already running on 127.0.0.1:{PORT}")
        return
    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
    subprocess.run([
        "docker", "run", "-d", "--name", CONTAINER,
        "-e", f"POSTGRES_USER={PG_USER}", "-e", f"POSTGRES_PASSWORD={PG_PASS}",
        "-e", f"POSTGRES_DB={PG_DB}", "-p", f"127.0.0.1:{PORT}:5432", IMAGE,
    ], check=True, stdout=subprocess.DEVNULL)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        ready = subprocess.run(
            ["docker", "exec", CONTAINER, "pg_isready", "-U", PG_USER, "-d", PG_DB, "-h", "127.0.0.1"],
            capture_output=True,
        )
        if ready.returncode == 0:
            _log(f"{CONTAINER} ready on 127.0.0.1:{PORT}")
            return
        time.sleep(1)
    raise SystemExit("Scratch DB did not become ready within 60 s")


def cmd_down(args: argparse.Namespace) -> None:
    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
    _log(f"Removed {CONTAINER}")


def _restore(dump: Path, extra: List[str]) -> None:
    with dump.open("rb") as fh:
        proc = subprocess.run(
            ["docker", "exec", "-i", CONTAINER, "pg_restore", "-U", PG_USER, "-d", PG_DB,
             "--no-owner", "--no-privileges", "--exit-on-error", *extra],
            stdin=fh, capture_output=True, text=True,
        )
    if proc.returncode != 0:
        raise SystemExit(f"pg_restore of {dump.name} failed: {proc.stderr.strip()}")


def cmd_load(args: argparse.Namespace) -> None:
    _require_scratch()
    snap = _snapshot_dir(args.workdir, args.snapshot)
    _log("Recreating scratch database ...")
    _psql_container(f"DROP DATABASE IF EXISTS {PG_DB} WITH (FORCE);\nCREATE DATABASE {PG_DB};\n", db="postgres")
    _log("Restoring schema ...")
    _restore(snap / "schema.dump", [])
    _log("Restoring data ...")
    # Only some tables are copied, so foreign keys to the rest would fail.
    _restore(snap / "data.dump", ["--disable-triggers"])

    rows = list(csv.DictReader((snap / "users.csv").open()))
    stmts = ["SET session_replication_role = replica;"]
    for row in rows:
        uid = int(row["id"])
        stmts.append(
            'INSERT INTO "user" (id, username, email, password_hash, lastfm_username) '
            f"VALUES ({uid}, {_sql_lit(row['username'])}, 'user{uid}@match-eval.invalid', '!', "
            f"{_sql_lit(row['lastfm_username'])});"
        )
    stmts.append("SET session_replication_role = origin;")
    stmts.append(f"CREATE TABLE {MARKER_TABLE} (snapshot text NOT NULL, loaded_at timestamptz DEFAULT now());")
    stmts.append(f"INSERT INTO {MARKER_TABLE} (snapshot) VALUES ({_sql_lit(args.snapshot)});")
    stmts.append("REFRESH MATERIALIZED VIEW combined_playback_history_mat;")
    _psql_container("\n".join(stmts) + "\n")
    _log(f"Loaded snapshot {args.snapshot} ({len(rows)} Last.fm user(s))")

    # The matches as they were on the source, before any re-match.
    label = f"{args.snapshot}-{AS_FOUND}"
    asyncio.run(_export_run(args.workdir, label, args.snapshot, {"kind": AS_FOUND}))


def _sql_lit(value: Optional[str]) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


# --------------------------------------------------------------------------
# run / export

async def _connect():
    import asyncpg

    return await asyncpg.connect(DSN)


async def _loaded_snapshot(conn) -> str:
    exists = await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", MARKER_TABLE)
    if not exists:
        raise SystemExit(f"{DSN} has no {MARKER_TABLE} table; refusing to touch it")
    return await conn.fetchval(f"SELECT snapshot FROM {MARKER_TABLE} LIMIT 1")


async def _flagged(conn) -> Dict[str, List[int]]:
    """Scrobble ids each metric flags in the scratch DB's current state."""
    return {name: [r[0] for r in await conn.fetch(sql)] for name, (_desc, sql) in METRICS.items()}


async def _metrics(conn, subset: Optional[List[int]] = None) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if subset is None:
        out["scrobbles"] = await conn.fetchval("SELECT count(*) FROM lastfm_scrobble")
    else:
        out["scrobbles"] = len(subset)
    # A subset run leaves every other scrobble unmatched, so matches and
    # flags only ever cover the subset.
    out["matched"] = await conn.fetchval("SELECT count(*) FROM lastfm_scrobble_match")
    out["unmatched"] = out["scrobbles"] - out["matched"]
    for name, ids in (await _flagged(conn)).items():
        out[name] = len(ids)
    for row in await conn.fetch(
        "SELECT match_method, count(*) AS n FROM lastfm_scrobble_match GROUP BY 1 ORDER BY 1"
    ):
        out[f"method:{row['match_method']}"] = row["n"]
    return out


async def _export_run(workdir: Path, label: str, snapshot: str, meta: Dict[str, object],
                      subset: Optional[List[int]] = None) -> None:
    conn = await _connect()
    try:
        loaded = await _loaded_snapshot(conn)
        if loaded != snapshot:
            raise SystemExit(f"Scratch DB holds snapshot {loaded}, not {snapshot}")
        out = _run_dir(workdir, label)
        out.mkdir(parents=True, exist_ok=True)
        if subset is None:
            rows = await conn.fetch(EXPORT_SQL)
        else:
            rows = await conn.fetch(EXPORT_SQL.replace("ORDER BY s.id", "WHERE s.id = ANY($1::bigint[])\nORDER BY s.id"), subset)
        with gzip.open(out / "matches.csv.gz", "wt", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(EXPORT_COLUMNS)
            for row in rows:
                writer.writerow(["" if row[c] is None else row[c] for c in EXPORT_COLUMNS])
        metrics = await _metrics(conn, subset)
    finally:
        await conn.close()
    meta = {"label": label, "snapshot": snapshot, "exported": dt.datetime.now().isoformat(timespec="seconds"), **meta}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    _log(f"Run {label}: {out}")
    for key in ("scrobbles", "matched", "unmatched", *METRICS):
        _log(f"  {key:18} {metrics[key]}")


SCROBBLE_SQL = """
SELECT id, lastfm_username, track_mbid, track_name, album_mbid, album_name,
       artist_mbid, artist_name
FROM lastfm_scrobble
WHERE lastfm_username = $1 AND id = ANY($2::bigint[])
ORDER BY played_at DESC, id DESC
"""


async def _run(args: argparse.Namespace) -> None:
    from app.lastfm_archive import match_archive
    from app.matching.matcher import match_and_store

    subset = _read_subset(args.workdir, args.subset) if args.subset else None
    conn = await _connect()
    try:
        snapshot = await _loaded_snapshot(conn)
        if subset is not None and subset["snapshot"] != snapshot:
            raise SystemExit(f"Subset {args.subset} was built from snapshot {subset['snapshot']}, not {snapshot}")
        users = await conn.fetch(
            'SELECT id, username, lastfm_username FROM "user" '
            "WHERE lastfm_username IS NOT NULL AND lastfm_username <> '' ORDER BY id"
        )
        # Same keys as the old Last.fm sync request, so saved runs compare.
        payload = {
            "fetch_new": False, "rematch_all": True, "limit": None,
            "fuzzy": not args.no_fuzzy, "fuzzy_title_threshold": args.fuzzy_title_threshold,
        }
        started = time.monotonic()
        results = []
        if subset is None:
            # The real sync path: delete the user's matches, re-match all.
            for user in users:
                _log(f"Re-matching scrobbles for user {user['id']} ...")
                matched, unmatched = await match_archive(
                    conn, user["lastfm_username"], rematch_all=True,
                    fuzzy=payload["fuzzy"], fuzzy_title_threshold=payload["fuzzy_title_threshold"],
                )
                results.append({"matched": matched, "unmatched": unmatched})
            await conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY combined_playback_history_mat")
        else:
            # Same matching loop on the subset only; every other scrobble is
            # left unmatched until the next full run.
            await conn.execute("DELETE FROM lastfm_scrobble_match")
            for user in users:
                scrobbles = await conn.fetch(SCROBBLE_SQL, user["lastfm_username"], subset["ids"])
                _log(f"Re-matching {len(scrobbles)} subset scrobbles for user {user['id']} ...")
                matched, unmatched = await match_and_store(
                    conn, scrobbles, fuzzy=payload["fuzzy"],
                    fuzzy_title_threshold=payload["fuzzy_title_threshold"],
                )
                results.append({"matched": matched, "unmatched": unmatched})
            await conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY combined_playback_history_mat")
        elapsed = round(time.monotonic() - started, 1)
    finally:
        await conn.close()
    _log(f"Re-match took {elapsed} s")
    await _export_run(args.workdir, args.label, snapshot, {
        "kind": "rematch", "git": _git_state(), "seconds": elapsed,
        "payload": payload, "per_user": results,
        "subset": args.subset,
    }, subset=subset["ids"] if subset else None)


# --------------------------------------------------------------------------
# subsets

def _subset_path(workdir: Path, name: str) -> Path:
    return workdir / "subsets" / f"{name}.json"


def _read_subset(workdir: Path, name: str) -> Dict[str, Any]:
    path = _subset_path(workdir, name)
    if not path.exists():
        raise SystemExit(f"No subset {name} at {path}")
    return json.loads(path.read_text())


def build_subset_ids(flagged: Iterable[int], runs: List[Dict[str, Dict[str, str]]],
                     all_ids: List[int], sample: int, seed: int) -> Tuple[List[int], Dict[str, int]]:
    """Flagged scrobbles + scrobbles whose match differs between any of the
    runs + a seeded random sample of the rest."""
    import random

    flagged_set = {int(i) for i in flagged}
    moved: set = set()
    if len(runs) > 1:
        for sid, row in runs[0].items():
            targets = {r[sid]["track_id"] for r in runs if sid in r}
            if len(targets) > 1:
                moved.add(int(sid))
    chosen = flagged_set | moved
    rest = sorted(set(all_ids) - chosen)
    sampled = random.Random(seed).sample(rest, min(sample, len(rest)))
    ids = sorted(chosen | set(sampled))
    return ids, {"flagged": len(flagged_set), "moved": len(moved), "sampled": len(sampled), "total": len(ids)}


async def _subset(args: argparse.Namespace) -> None:
    conn = await _connect()
    try:
        snapshot = await _loaded_snapshot(conn)
        matched = await conn.fetchval("SELECT count(*) FROM lastfm_scrobble_match")
        total = await conn.fetchval("SELECT count(*) FROM lastfm_scrobble")
        if matched < total * 0.5:
            raise SystemExit("Scratch DB doesn't hold a full run (a subset run was last?); do a full run first")
        flagged_by = await _flagged(conn)
        all_ids = [r[0] for r in await conn.fetch("SELECT id FROM lastfm_scrobble")]
    finally:
        await conn.close()
    runs = []
    for label in args.runs:
        meta, _metrics_unused, rows = _load_run(args.workdir, label)
        if meta["snapshot"] != snapshot or meta.get("subset"):
            raise SystemExit(f"Run {label} is not a full run of snapshot {snapshot}")
        runs.append(rows)
    flagged = [i for ids in flagged_by.values() for i in ids]
    ids, stats = build_subset_ids(flagged, runs, all_ids, args.sample, args.seed)
    path = _subset_path(args.workdir, args.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "name": args.name, "snapshot": snapshot, "runs": args.runs,
        "sample": args.sample, "seed": args.seed, "stats": stats, "ids": ids,
    }))
    _log(f"Subset {args.name}: {stats['total']} scrobbles "
         f"({stats['flagged']} flagged, {stats['moved']} moved between runs, {stats['sampled']} sampled)")


def cmd_subset(args: argparse.Namespace) -> None:
    _require_scratch()
    if _subset_path(args.workdir, args.name).exists() and not args.force:
        raise SystemExit(f"Subset {args.name} exists (use --force to overwrite)")
    asyncio.run(_subset(args))


def cmd_run(args: argparse.Namespace) -> None:
    _require_scratch()
    if _run_dir(args.workdir, args.label).exists() and not args.force:
        raise SystemExit(f"Run {args.label} exists (use --force to overwrite)")
    asyncio.run(_run(args))


async def _rescore(args: argparse.Namespace) -> None:
    for label in args.labels:
        meta, _metrics_old, rows = _load_run(args.workdir, label)
        subset = _read_subset(args.workdir, str(meta["subset"]))["ids"] if meta.get("subset") else None
        conn = await _connect()
        try:
            loaded = await _loaded_snapshot(conn)
            if meta["snapshot"] != loaded:
                raise SystemExit(f"Run {label} is from snapshot {meta['snapshot']}, scratch DB holds {loaded}")
            records = [
                (int(r["scrobble_id"]), int(r["track_id"]), float(r["match_score"] or 0),
                 r["match_method"], r["match_reason"] or None)
                for r in rows.values() if r["track_id"]
            ]
            async with conn.transaction():
                await conn.execute("DELETE FROM lastfm_scrobble_match")
                await conn.copy_records_to_table(
                    "lastfm_scrobble_match", records=records,
                    columns=["scrobble_id", "track_id", "match_score", "match_method", "match_reason"],
                )
            await conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY combined_playback_history_mat")
            metrics = await _metrics(conn, subset)
        finally:
            await conn.close()
        out = _run_dir(args.workdir, label)
        (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
        meta["rescored"] = dt.datetime.now().isoformat(timespec="seconds")
        (out / "meta.json").write_text(json.dumps(meta, indent=2))
        _log(f"Rescored {label}: " + ", ".join(f"{k} {metrics[k]}" for k in ("unmatched", *METRICS)))


def cmd_rescore(args: argparse.Namespace) -> None:
    _require_scratch()
    asyncio.run(_rescore(args))


# --------------------------------------------------------------------------
# diff

def _load_run(workdir: Path, label: str) -> Tuple[Dict[str, object], Dict[str, int], Dict[str, Dict[str, str]]]:
    path = _run_dir(workdir, label)
    if not (path / "matches.csv.gz").exists():
        raise SystemExit(f"No run {label} in {path.parent}")
    meta = json.loads((path / "meta.json").read_text())
    metrics = json.loads((path / "metrics.json").read_text())
    with gzip.open(path / "matches.csv.gz", "rt", newline="") as fh:
        rows = {row["scrobble_id"]: row for row in csv.DictReader(fh)}
    return meta, metrics, rows


def _scrobble_key(row: Dict[str, str]) -> str:
    album = f" [{row['album_name']}]" if row["album_name"] else ""
    return f"{row['artist_name']} - {row['track_name']}{album}"


def _target(row: Dict[str, str]) -> str:
    if not row["track_id"]:
        return "(unmatched)"
    return f"{row['matched_title']} [{row['matched_album']}] #{row['track_id']}"


def diff_runs(a: Dict[str, Dict[str, str]], b: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    """Classify every scrobble present in both runs and group the changes."""
    counts: Counter = Counter()
    groups: Dict[str, Counter] = {"moved": Counter(), "gained": Counter(), "lost": Counter()}
    for sid, row_a in a.items():
        row_b = b.get(sid)
        if row_b is None:
            counts["missing_in_b"] += 1
            continue
        ta, tb = row_a["track_id"], row_b["track_id"]
        if ta == tb:
            counts["same_match" if ta else "same_unmatched"] += 1
            continue
        kind = "moved" if ta and tb else ("gained" if tb else "lost")
        counts[kind] += 1
        groups[kind][(_scrobble_key(row_a), _target(row_a), _target(row_b))] += 1
    counts["missing_in_a"] = sum(1 for sid in b if sid not in a)
    return {"counts": counts, "groups": groups}


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def render_report(label_a: str, label_b: str, metrics_a: Dict[str, int], metrics_b: Dict[str, int],
                  result: Dict[str, Any], top: int) -> str:
    counts: Counter = result["counts"]
    groups: Dict[str, Counter] = result["groups"]
    lines = [f"# Match diff: `{label_a}` → `{label_b}`", "", "## Metrics (lower is better for the last three)", "",
             f"| metric | {label_a} | {label_b} | change |", "|---|---:|---:|---:|"]
    keys = ["scrobbles", "matched", "unmatched", *METRICS]
    keys += sorted(k for k in set(metrics_a) | set(metrics_b) if k.startswith("method:"))
    for key in keys:
        va, vb = metrics_a.get(key, 0), metrics_b.get(key, 0)
        lines.append(f"| {key} | {va} | {vb} | {vb - va:+d} |")
    lines += ["", "Metric definitions:", ""]
    lines += [f"- **{name}**: {desc}." for name, (desc, _sql) in METRICS.items()]
    lines += ["", "## Scrobbles", "", "| outcome | count |", "|---|---:|"]
    for key in ("same_match", "same_unmatched", "moved", "gained", "lost", "missing_in_a", "missing_in_b"):
        lines.append(f"| {key} | {counts.get(key, 0)} |")
    titles = {
        "moved": "Moved to another track",
        "gained": f"Matched in `{label_b}` only",
        "lost": f"Matched in `{label_a}` only",
    }
    for kind, title in titles.items():
        group = groups[kind]
        lines += ["", f"## {title} ({counts.get(kind, 0)} scrobbles, {len(group)} distinct)", ""]
        if not group:
            lines.append("None.")
            continue
        lines += ["| scrobbles | scrobble | before | after |", "|---:|---|---|---|"]
        for (key, before, after), n in group.most_common(top):
            lines.append(f"| {n} | {_md_escape(key)} | {_md_escape(before)} | {_md_escape(after)} |")
        if len(group) > top:
            lines.append(f"\n…{len(group) - top} more (raise --top).")
    return "\n".join(lines) + "\n"


def cmd_diff(args: argparse.Namespace) -> None:
    meta_a, metrics_a, rows_a = _load_run(args.workdir, args.a)
    meta_b, metrics_b, rows_b = _load_run(args.workdir, args.b)
    if meta_a["snapshot"] != meta_b["snapshot"]:
        raise SystemExit(f"Runs come from different snapshots ({meta_a['snapshot']} vs {meta_b['snapshot']})")
    if meta_a.get("subset") != meta_b.get("subset"):
        raise SystemExit(f"Runs cover different scrobbles (subset {meta_a.get('subset')} vs {meta_b.get('subset')})")
    result = diff_runs(rows_a, rows_b)
    report = render_report(args.a, args.b, metrics_a, metrics_b, result, args.top)
    out = args.out or (args.workdir / "runs" / f"diff-{args.a}--{args.b}.md")
    out.write_text(report)
    counts: Counter = result["counts"]
    _log(f"moved {counts.get('moved', 0)}, gained {counts.get('gained', 0)}, lost {counts.get('lost', 0)}, "
         f"unchanged {counts.get('same_match', 0) + counts.get('same_unmatched', 0)}")
    for key in METRICS:
        _log(f"  {key:18} {metrics_a.get(key, 0)} -> {metrics_b.get(key, 0)}")
    _log(f"Report: {out}")


# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workdir", type=Path, default=DEFAULT_WORKDIR,
                        help=f"Snapshots and runs (default {DEFAULT_WORKDIR}; env MATCH_EVAL_DIR)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("snapshot", help="Dump the matcher's tables from a Jamarr DB (read-only)")
    p.add_argument("--exec-prefix", default="docker exec -i jamarr_db",
                   help="Command prefix that runs pg_dump/psql next to the source DB, "
                        "e.g. 'ssh myhost docker exec -i jamarr_db'")
    p.add_argument("--db-user", default="jamarr")
    p.add_argument("--db-name", default="jamarr")
    p.add_argument("--name", help="Snapshot name (default: timestamp)")
    p.set_defaults(func=cmd_snapshot)

    sub.add_parser("up", help=f"Start the scratch Postgres ({CONTAINER}, 127.0.0.1:{PORT})").set_defaults(func=cmd_up)
    sub.add_parser("down", help="Remove the scratch Postgres").set_defaults(func=cmd_down)

    p = sub.add_parser("load", help="Load a snapshot into the scratch DB and export its matches as found")
    p.add_argument("snapshot")
    p.set_defaults(func=cmd_load)

    p = sub.add_parser("run", help="Re-match every scrobble with the code in this checkout and export")
    p.add_argument("label")
    p.add_argument("--force", action="store_true", help="Overwrite an existing run")
    p.add_argument("--no-fuzzy", action="store_true")
    p.add_argument("--fuzzy-title-threshold", type=int, default=92)
    p.add_argument("--subset", help="Re-match only this subset (see: subset); fast, but batch and cache effects differ from a full run")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("subset", help="Build a scrobble subset for quick runs (needs a full run loaded)")
    p.add_argument("name")
    p.add_argument("--runs", nargs="*", default=[], help="Full runs whose disagreements to include")
    p.add_argument("--sample", type=int, default=5000, help="Random scrobbles to add (default 5000)")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_subset)

    p = sub.add_parser("rescore", help="Recompute saved runs' metrics with the current metric definitions")
    p.add_argument("labels", nargs="+")
    p.set_defaults(func=cmd_rescore)

    p = sub.add_parser("diff", help="Compare two runs from the same snapshot")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--top", type=int, default=50, help="Rows per section (default 50)")
    p.add_argument("--out", type=Path)
    p.set_defaults(func=cmd_diff)
    return parser


def main(argv: Optional[Iterable[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    args.workdir = args.workdir.expanduser()
    args.func(args)


if __name__ == "__main__":
    main()
