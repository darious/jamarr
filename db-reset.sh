#!/bin/bash
# Wipes all data from the database EXCEPT user accounts.
# Safer than a full volume reset as it preserves logins.

set -e

# Warning Prompt
echo "⚠️  WARNING: THIS WILL DELETE ALL LIBRARY DATA!"
echo "   - Tracks, Albums, Artists, Playback History, Queues, etc."
echo "   - User accounts will be PRESERVED."
echo ""
read -p "Are you sure you want to continue? [y/N] " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

echo "Connected to database..."

# SQL Command to truncate everything except static/user tables
# We use TRUNCATE ... CASCADE to handle foreign keys automatically
SQL="
TRUNCATE TABLE 
    session,
    client_session,
    renderer_state,
    playback_history,
    track,
    artist,
    album,
    missing_album,
    artwork,
    renderer,
    top_track,
    similar_artist,
    artist_genre,
    external_link,
    image_map
RESTART IDENTITY CASCADE;
"

# Execute inside the database container
# We assume the container name is 'jamarr_db' from docker-compose.yml
# We must specify -p 8110 because the server runs on that port
docker compose exec -T jamarr_db psql -U jamarr -d jamarr -p 8110 -c "$SQL"

echo "✅ Database reset complete (User accounts preserved)."
