import pytest
from httpx import AsyncClient
from datetime import datetime, timedelta
import uuid

@pytest.fixture
async def recommendation_data(db, auth_token):
    """Insert test data for recommendations."""
    # Get the user_id from the auth_token user (testuser)
    user_id = await db.fetchval("""
        SELECT id FROM "user" WHERE username = 'testuser'
    """)
    
    # Create artists
    artist1_mbid = str(uuid.uuid4())
    artist2_mbid = str(uuid.uuid4())
    artist3_mbid = str(uuid.uuid4())
    
    await db.execute("""
        INSERT INTO artist (mbid, name)
        VALUES ($1, 'Taylor Swift'), ($2, 'Ed Sheeran'), ($3, 'Adele')
    """, artist1_mbid, artist2_mbid, artist3_mbid)
    
    # Create albums
    album1_mbid = str(uuid.uuid4())
    album2_mbid = str(uuid.uuid4())
    
    await db.execute("""
        INSERT INTO album (mbid, title, release_date)
        VALUES ($1, '1989', '2014-10-27'), ($2, 'Divide', '2017-03-03')
    """, album1_mbid, album2_mbid)
    
    # Link artists to albums
    await db.execute("""
        INSERT INTO artist_album (artist_mbid, album_mbid, type)
        VALUES ($1, $2, 'primary'), ($3, $4, 'primary')
    """, artist1_mbid, album1_mbid, artist2_mbid, album2_mbid)
    
    # Create tracks
    track1_id = await db.fetchval("""
        INSERT INTO track (title, artist, album, duration_seconds, path, artist_mbid, release_mbid)
        VALUES ('Shake It Off', 'Taylor Swift', '1989', 219, '/music/shake.flac', $1, $2)
        RETURNING id
    """, artist1_mbid, album1_mbid)
    
    track2_id = await db.fetchval("""
        INSERT INTO track (title, artist, album, duration_seconds, path, artist_mbid, release_mbid)
        VALUES ('Shape of You', 'Ed Sheeran', 'Divide', 233, '/music/shape.flac', $1, $2)
        RETURNING id
    """, artist2_mbid, album2_mbid)
    
    # Link tracks to artists via track_artist
    await db.execute("""
        INSERT INTO track_artist (track_id, artist_mbid)
        VALUES ($1, $2), ($3, $4)
    """, track1_id, artist1_mbid, track2_id, artist2_mbid)
    
    # Create playback history (last 7 days)
    for i in range(7):
        ts = datetime.now() - timedelta(days=i)
        # More plays for artist1 (Taylor Swift)
        for _ in range(3):
            await db.execute("""
                INSERT INTO playback_history (track_id, client_ip, timestamp, user_id)
                VALUES ($1, '127.0.0.1', $2, $3)
            """, track1_id, ts, user_id)
        
        # Fewer plays for artist2 (Ed Sheeran)
        await db.execute("""
            INSERT INTO playback_history (track_id, client_ip, timestamp, user_id)
            VALUES ($1, '127.0.0.1', $2, $3)
        """, track2_id, ts, user_id)
    
    # Create similar artists for recommendations
    await db.execute("""
        INSERT INTO similar_artist (artist_mbid, similar_artist_mbid, similar_artist_name, rank)
        VALUES ($1, $2, 'Adele', 1)
    """, artist1_mbid, artist3_mbid)
    
    # Create top tracks for album scoring
    await db.execute("""
        INSERT INTO top_track (track_id, artist_mbid, type, external_name, popularity, rank)
        VALUES ($1, $2, 'top', 'Shake It Off', 95, 1), ($3, $4, 'top', 'Shape of You', 88, 2)
    """, track1_id, artist1_mbid, track2_id, artist2_mbid)
    
    # Refresh materialized view
    await db.execute("REFRESH MATERIALIZED VIEW combined_playback_history_mat")
    
    return {
        'user_id': user_id,
        'artist1_mbid': artist1_mbid,
        'artist2_mbid': artist2_mbid,
        'artist3_mbid': artist3_mbid,
        'album1_mbid': album1_mbid,
        'album2_mbid': album2_mbid,
        'track1_id': track1_id,
        'track2_id': track2_id
    }


@pytest.mark.asyncio
async def test_get_seeds_basic(client: AsyncClient, db, recommendation_data, auth_token):
    """Test that seeds endpoint returns artists from playback history."""
    client.cookies = {"jamarr_session": auth_token}
    response = await client.get("/api/recommendations/seeds?days=7")
    assert response.status_code == 200
    
    seeds = response.json()
    assert isinstance(seeds, list)
    assert len(seeds) > 0


@pytest.mark.asyncio
async def test_get_recommended_artists(client: AsyncClient, db, recommendation_data, auth_token):
    """Test that artist recommendations are returned."""
    client.cookies = {"jamarr_session": auth_token}
    response = await client.get("/api/recommendations/artists?days=7")
    assert response.status_code == 200
    
    artists = response.json()
    assert isinstance(artists, list)
