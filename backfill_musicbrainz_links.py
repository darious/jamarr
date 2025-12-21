#!/usr/bin/env python3
"""
Backfill MusicBrainz external links for existing artists.
This script adds MusicBrainz artist URLs to the external_links table for all artists that don't have one yet.
"""
import asyncio
import aiosqlite
from app.config import get_musicbrainz_root_url

async def backfill_musicbrainz_links():
    db_path = "cache/library.sqlite"
    mb_root = get_musicbrainz_root_url()
    
    async with aiosqlite.connect(db_path) as db:
        # Get all artists
        async with db.execute("SELECT mbid FROM artists WHERE mbid IS NOT NULL") as cursor:
            artists = await cursor.fetchall()
        
        print(f"Found {len(artists)} artists")
        
        added = 0
        for (mbid,) in artists:
            mb_url = f"{mb_root}/artist/{mbid}"
            
            # Check if link already exists
            async with db.execute(
                "SELECT 1 FROM external_links WHERE entity_type = 'artist' AND entity_id = ? AND type = 'musicbrainz'",
                (mbid,)
            ) as cursor:
                exists = await cursor.fetchone()
            
            if not exists:
                await db.execute(
                    "INSERT INTO external_links (entity_type, entity_id, type, url) VALUES (?, ?, ?, ?)",
                    ('artist', mbid, 'musicbrainz', mb_url)
                )
                added += 1
        
        await db.commit()
        print(f"Added {added} MusicBrainz links")

if __name__ == "__main__":
    asyncio.run(backfill_musicbrainz_links())
