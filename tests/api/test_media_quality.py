import pytest
from httpx import AsyncClient
import asyncpg

@pytest.fixture
async def seed_data(db: asyncpg.Connection):
    # Insert Artwork
    await db.execute("""
        INSERT INTO artwork (id, sha1, source, type) VALUES 
        (1, 'sha1_1', 'filesystem', 'image/jpeg'),
        (2, 'sha1_2', 'fanart', 'image/jpeg'),
        (3, 'sha1_3', 'spotify', 'image/jpeg')
    """)

    # Insert Artists
    await db.execute("""
        INSERT INTO artist (mbid, name, artwork_id, sort_name) VALUES 
        ('artist1', 'Artist One', 1, 'Artist One'),
        ('artist2', 'Artist Two', 2, 'Artist Two'),
        ('artist3', 'Artist Three', NULL, 'Artist Three')
    """)

    # Insert Albums with release_group_mbid
    # album1 and album1b are different releases of the same release group
    await db.execute("""
        INSERT INTO album (mbid, release_group_mbid, title, artwork_id) VALUES 
        ('album1', 'rg1', 'Album One', 1),
        ('album1b', 'rg1', 'Album One (Deluxe)', 1),
        ('album2', 'rg2', 'Album Two', NULL)
    """)

    # Artist-Album map (Primary)
    await db.execute("""
        INSERT INTO artist_album (artist_mbid, album_mbid, type) VALUES 
        ('artist1', 'album1', 'primary'),
        ('artist1', 'album1b', 'primary')
    """)

    # Image Map (Backgrounds)
    await db.execute("""
        INSERT INTO image_map (artwork_id, entity_type, entity_id, image_type) VALUES 
        (3, 'artist', 'artist1', 'artistbackground')
    """)

    # External Links (stored at release_group_mbid level for albums)
    await db.execute("""
        INSERT INTO external_link (entity_type, entity_id, type, url) VALUES 
        ('artist', 'artist1', 'spotify', 'http://spotify.com/artist1'),
        ('album', 'rg1', 'musicbrainz', 'http://mb.com/rg1')
    """)


@pytest.mark.asyncio
async def test_media_quality_summary(client: AsyncClient, seed_data):
    response = await client.get("/api/media-quality/summary")
    assert response.status_code == 200
    data = response.json()
    
    # Artist Stats
    all_stats = data["artist_stats"]["all"]
    assert all_stats["total"] == 3
    assert all_stats["with_background"] == 1
    # Sources: artist1->1(filesystem->Other), artist2->2(fanart->Fanart), artist3->NULL(None)
    assert all_stats["sources"]["Other"] == 1
    assert all_stats["sources"]["Fanart"] == 1
    assert all_stats["sources"]["None"] == 1
    assert all_stats["link_stats"]["spotify"] == 1

    # Primary Artist Stats (Only artist1 is primary)
    prim_stats = data["artist_stats"]["primary"]
    assert prim_stats["total"] == 1
    assert prim_stats["with_background"] == 1
    assert prim_stats["sources"]["Other"] == 1
    assert prim_stats["link_stats"]["spotify"] == 1

    # Album Stats
    # We have 3 releases but only 2 unique release groups (rg1, rg2)
    alb_stats = data["album_stats"]
    assert alb_stats["total"] == 2  # 2 unique release groups
    assert alb_stats["with_artwork"] == 1  # rg1 has artwork (both releases have it)
    assert alb_stats["link_stats"]["musicbrainz"] == 1  # rg1 has a link

@pytest.mark.asyncio
async def test_media_quality_items(client: AsyncClient, seed_data):
    # Test valid query - should return 2 release groups
    response = await client.get("/api/media-quality/items?category=album&filter_type=total")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2  # 2 unique release groups
    
    # Test missing artwork - should return rg2
    response = await client.get("/api/media-quality/items?category=album&filter_type=artwork&filter_value=missing")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["mbid"] == "rg2"  # release_group_mbid
    
    # Test with artwork - should return rg1
    response = await client.get("/api/media-quality/items?category=album&filter_type=artwork&filter_value=present")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["mbid"] == "rg1"  # release_group_mbid

    # Test source fanart (for artists)
    response = await client.get("/api/media-quality/items?category=artist&filter_type=source&filter_value=Fanart")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["mbid"] == "artist2"
    
    # Test primary artists
    response = await client.get("/api/media-quality/items?category=primary&filter_type=total")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["mbid"] == "artist1"
