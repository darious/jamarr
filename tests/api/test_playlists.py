import pytest


@pytest.mark.asyncio
async def test_playlist_lifecycle(auth_client, db, auth_token):
    """
    Test the full lifecycle of a playlist:
    1. Create
    2. Add Tracks (include duplicates)
    3. Get Layout
    4. Reorder
    5. Remove Track
    6. Delete
    """
    
    # 0. Setup dummy tracks
    track_ids = [9001, 9002, 9003]
    for tid in track_ids:
        await db.execute("""
            INSERT INTO track (id, title, artist, album, path, duration_seconds)
            VALUES ($1, $2, 'Test Artist', 'Test Album', $3, 180)
            ON CONFLICT (id) DO NOTHING
        """, tid, f'Track {tid}', f'/tmp/{tid}.flac')

    headers = {"Authorization": f"Bearer {auth_token}"}

    # 1. Create Playlist
    resp = await auth_client.post("/api/playlists", json={"name": "My Test Playlist", "description": "A description"}, headers=headers)
    assert resp.status_code == 200
    playlist = resp.json()
    playlist_id = playlist["id"]
    assert playlist["name"] == "My Test Playlist"
    assert playlist["track_count"] == 0

    # 2. Add Tracks
    # Add 9001, 9002
    resp = await auth_client.post(f"/api/playlists/{playlist_id}/tracks", json={"track_ids": [9001, 9002]}, headers=headers)
    assert resp.status_code == 200
    
    # Add 9001 again (duplicate)
    resp = await auth_client.post(f"/api/playlists/{playlist_id}/tracks", json={"track_ids": [9001]}, headers=headers)
    assert resp.status_code == 200

    # 3. Get Playlist Detail
    resp = await auth_client.get(f"/api/playlists/{playlist_id}", headers=headers)
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["track_count"] == 3
    assert len(detail["tracks"]) == 3
    # Order should be 9001, 9002, 9001
    assert detail["tracks"][0]["track_id"] == 9001
    assert detail["tracks"][1]["track_id"] == 9002
    assert detail["tracks"][2]["track_id"] == 9001
    
    pt_ids = [t["playlist_track_id"] for t in detail["tracks"]]
    
    # 4. Reorder
    # Move last item (duplicate 9001) to top
    new_order = [pt_ids[2], pt_ids[0], pt_ids[1]]
    resp = await auth_client.post(f"/api/playlists/{playlist_id}/reorder", json={"allowed_playlist_track_ids": new_order}, headers=headers)
    assert resp.status_code == 200
    
    # Verify order
    resp = await auth_client.get(f"/api/playlists/{playlist_id}", headers=headers)
    detail = resp.json()
    assert detail["tracks"][0]["playlist_track_id"] == pt_ids[2]
    assert detail["tracks"][1]["playlist_track_id"] == pt_ids[0]
    assert detail["tracks"][2]["playlist_track_id"] == pt_ids[1]

    # 5. Remove Track
    # Remove the middle one (original 9001, pt_ids[0])
    resp = await auth_client.delete(f"/api/playlists/{playlist_id}/tracks/{pt_ids[0]}", headers=headers)
    assert resp.status_code == 200
    
    resp = await auth_client.get(f"/api/playlists/{playlist_id}", headers=headers)
    detail = resp.json()
    assert detail["track_count"] == 2
    assert len(detail["tracks"]) == 2
    # Remaining: pt_ids[2] (9001), pt_ids[1] (9002)
    assert detail["tracks"][0]["playlist_track_id"] == pt_ids[2]
    assert detail["tracks"][1]["playlist_track_id"] == pt_ids[1]

    # 6. Delete Playlist
    resp = await auth_client.delete(f"/api/playlists/{playlist_id}", headers=headers)
    assert resp.status_code == 200
    
    # Verify gone
    resp = await auth_client.get(f"/api/playlists/{playlist_id}", headers=headers)
    assert resp.status_code == 404

    # 7. List Playlists
    # Create one again to list
    await auth_client.post("/api/playlists", json={"name": "Listable Playlist"}, headers=headers)
    
    # Create track with artwork
    artwork_hex = "12345678" * 5 # 40 chars hex
    aid = await db.fetchval("INSERT INTO artwork (path_on_disk, sha1) VALUES ('/tmp/art.jpg', $1) RETURNING id", artwork_hex)
    tid_art = 9999
    await db.execute("""
        INSERT INTO track (id, title, artist, album, path, duration_seconds, artwork_id)
        VALUES ($1, 'Art Track', 'Artist', 'Album', '/tmp/art_track.flac', 180, $2)
    """, tid_art, aid)
    
    # Add to the new playlist
    # reuse resp from create
    new_pid = (await auth_client.get("/api/playlists", headers=headers)).json()[0]["id"] # Get most recent
    await auth_client.post(f"/api/playlists/{new_pid}/tracks", json={"track_ids": [tid_art]}, headers=headers)

    resp = await auth_client.get("/api/playlists", headers=headers)
    assert resp.status_code == 200
    listed = resp.json()
    
    # Find our playlist
    target = next(p for p in listed if p["id"] == new_pid)
    assert target["track_count"] == 1
    assert "thumbnails" in target
    assert len(target["thumbnails"]) == 1
    assert target["thumbnails"][0] == artwork_hex

    detail = (await auth_client.get(f"/api/playlists/{new_pid}", headers=headers)).json()
    assert detail["tracks"][0]["art_sha1"] == artwork_hex
    assert detail["tracks"][0]["art_sha1"] == artwork_hex
    assert detail["tracks"][0]["path"] == "/tmp/art_track.flac"

@pytest.mark.asyncio
async def test_public_private_playlist(auth_client, db, auth_token):
    headers = {"Authorization": f"Bearer {auth_token}"}
    
    # Create private (default)
    resp = await auth_client.post("/api/playlists", json={"name": "Private Playlist"}, headers=headers)
    priv_id = resp.json()["id"]
    
    # Create public
    resp = await auth_client.post("/api/playlists", json={"name": "Public Playlist", "is_public": True}, headers=headers)
    pub_id = resp.json()["id"]
    
    # Another user
    # We can't easily switch users in one test without separate clients or managing cookies manually.
    # But we can verify the 'is_public' flag in DB or response.
    
    resp = await auth_client.get(f"/api/playlists/{priv_id}", headers=headers)
    assert resp.json()["is_public"] is False
    
    resp = await auth_client.get(f"/api/playlists/{pub_id}", headers=headers)
    assert resp.json()["is_public"] is True
