#!/usr/bin/env bash
set -euo pipefail

DB="../cache/library.sqlite"

echo "Using database: $DB"

if [[ ! -f "$DB" ]]; then
  echo "ERROR: Database not found: $DB"
  exit 1
fi

echo "Deleting data from tables (except users)..."

sqlite3 "$DB" <<'SQL'
PRAGMA foreign_keys = OFF;
BEGIN;

-- Core tables
DELETE FROM albums;
DELETE FROM artist_albums;
DELETE FROM artist_genres;
DELETE FROM artists;
DELETE FROM artwork;
DELETE FROM client_sessions;
DELETE FROM external_links;
DELETE FROM image_mapping;
DELETE FROM media_quality_issues;
DELETE FROM missing_albums;
DELETE FROM playback_history;
DELETE FROM renderer_states;
DELETE FROM renderers;
DELETE FROM sessions;
DELETE FROM similar_artists;
DELETE FROM track_artists;
DELETE FROM tracks;
DELETE FROM tracks_top;

-- Clear FTS properly (FTS5 special command; do NOT touch shadow tables)
INSERT INTO tracks_fts(tracks_fts) VALUES('delete-all');

COMMIT;
PRAGMA foreign_keys = ON;
SQL

echo "Vacuuming database..."
sqlite3 "$DB" "VACUUM;"

echo "Clearing cache/art and cache/log..."
rm -rf cache/art/* cache/log/*

echo "Done."
