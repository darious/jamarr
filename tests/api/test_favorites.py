import pytest
from httpx import AsyncClient


@pytest.fixture
async def favorite_data(db):
    await db.execute(
        """
        INSERT INTO artist (mbid, name, sort_name, letter)
        VALUES ('artist-fav-1', 'Favorite Artist', 'Favorite Artist', 'F')
        """
    )
    await db.execute(
        """
        INSERT INTO album (mbid, release_group_mbid, title, release_date)
        VALUES ('release-fav-1', 'release-group-fav-1', 'Favorite Release', '2024-01-01')
        """
    )


@pytest.mark.asyncio
async def test_toggle_artist_favorite(auth_client: AsyncClient, db, favorite_data):
    user = await db.fetchrow('SELECT id FROM "user" WHERE username = $1', "testuser")

    response = await auth_client.put(
        "/api/favorites/artists/artist-fav-1",
        json={"favorite": True},
    )
    assert response.status_code == 200
    assert response.json() == {"artist_mbid": "artist-fav-1", "favorite": True}

    favorite = await db.fetchval(
        """
        SELECT COUNT(*)
        FROM favorite_artist
        WHERE user_id = $1 AND artist_mbid = $2
        """,
        user["id"],
        "artist-fav-1",
    )
    assert favorite == 1

    response = await auth_client.put(
        "/api/favorites/artists/artist-fav-1",
        json={"favorite": False},
    )
    assert response.status_code == 200
    assert response.json() == {"artist_mbid": "artist-fav-1", "favorite": False}

    favorite = await db.fetchval(
        """
        SELECT COUNT(*)
        FROM favorite_artist
        WHERE user_id = $1 AND artist_mbid = $2
        """,
        user["id"],
        "artist-fav-1",
    )
    assert favorite == 0


@pytest.mark.asyncio
async def test_toggle_release_favorite_is_user_scoped(
    auth_client: AsyncClient, db, favorite_data
):
    current_user = await db.fetchrow('SELECT id FROM "user" WHERE username = $1', "testuser")
    other_user = await db.fetchrow(
        """
        INSERT INTO "user" (username, email, password_hash, display_name, created_at)
        VALUES ('favorite_other_user', 'favorite_other_user@example.com', 'hash', 'Favorite Other User', NOW())
        RETURNING id
        """
    )
    await db.execute(
        "INSERT INTO favorite_release (user_id, album_mbid) VALUES ($1, $2)",
        other_user["id"],
        "release-fav-1",
    )

    response = await auth_client.put(
        "/api/favorites/releases/release-fav-1",
        json={"favorite": True},
    )
    assert response.status_code == 200
    assert response.json() == {"album_mbid": "release-fav-1", "favorite": True}

    current_count = await db.fetchval(
        """
        SELECT COUNT(*)
        FROM favorite_release
        WHERE user_id = $1 AND album_mbid = $2
        """,
        current_user["id"],
        "release-fav-1",
    )
    other_count = await db.fetchval(
        """
        SELECT COUNT(*)
        FROM favorite_release
        WHERE user_id = $1 AND album_mbid = $2
        """,
        other_user["id"],
        "release-fav-1",
    )

    assert current_count == 1
    assert other_count == 1


@pytest.mark.asyncio
async def test_toggle_favorite_returns_404_for_unknown_entity(
    auth_client: AsyncClient, favorite_data
):
    response = await auth_client.put(
        "/api/favorites/artists/not-found",
        json={"favorite": True},
    )
    assert response.status_code == 404

    response = await auth_client.put(
        "/api/favorites/releases/not-found",
        json={"favorite": True},
    )
    assert response.status_code == 404
