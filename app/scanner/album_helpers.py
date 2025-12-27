async def upsert_artist_album(db, artist_mbid: str, album_mbid: str, album_type: str):
    """
    Insert or update the artist/album link. Conflicts are keyed on (artist_mbid, album_mbid)
    matching the table primary key so we avoid invalid conflict targets.
    """
    await db.execute(
        """
        INSERT INTO artist_album (artist_mbid, album_mbid, type)
        VALUES ($1, $2, $3)
        ON CONFLICT (artist_mbid, album_mbid) DO UPDATE
        SET type = EXCLUDED.type
        """,
        artist_mbid,
        album_mbid,
        album_type,
    )
