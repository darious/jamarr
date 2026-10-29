import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_stream_missing(auth_client: AsyncClient):
    # Stream non-existent track
    response = await auth_client.get("/api/stream/99999")
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_art_missing(auth_client: AsyncClient):
    # Art non-existent
    response = await auth_client.get("/api/art/file/0000000000000000000000000000000000000000")
    assert response.status_code == 404

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as unauth_client:
        unauth_response = await unauth_client.get("/api/art/file/0000000000000000000000000000000000000000")
        assert unauth_response.status_code == 404

@pytest.mark.asyncio
async def test_art_test_endpoint(auth_client: AsyncClient):
    # UPnP test art
    response = await auth_client.get("/api/art/test")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_concurrent_cold_resize_requests_share_one_resize(
    auth_client: AsyncClient, db, tmp_path, monkeypatch
):
    """Eight simultaneous cold requests for one size: one resize, eight
    complete and identical JPEGs, correct cache headers (#317)."""
    import asyncio
    import time
    from PIL import Image
    from app.media import art

    sha1 = "aaaa0000bbbb1111cccc2222dddd3333eeee4444"
    original = tmp_path / sha1
    Image.new("RGBA", (1200, 1200), (0, 0, 255, 0)).save(original, format="PNG")
    await db.execute(
        """
        INSERT INTO artwork (sha1, mime, width, height, path_on_disk, filesize_bytes, image_format, source)
        VALUES ($1, 'image/png', 1200, 1200, $2, $3, 'PNG', 'local')
        ON CONFLICT (sha1) DO UPDATE SET path_on_disk = EXCLUDED.path_on_disk
        """,
        sha1, str(original), original.stat().st_size,
    )
    cache = tmp_path / "cache"
    monkeypatch.setattr(art, "CACHE_DIR", str(cache))
    monkeypatch.setattr(art, "_inflight", {})

    calls = []
    real = art._create_resized

    def slow(original_path, resized_path, target_size):
        calls.append(resized_path)
        time.sleep(0.2)  # long enough for every request to arrive first
        real(original_path, resized_path, target_size)

    monkeypatch.setattr(art, "_create_resized", slow)

    responses = await asyncio.gather(
        *(auth_client.get(f"/api/art/file/{sha1}?max_size=300") for _ in range(8))
    )

    assert [r.status_code for r in responses] == [200] * 8
    assert {r.headers["content-type"] for r in responses} == {"image/jpeg"}
    bodies = {r.content for r in responses}
    assert len(bodies) == 1, "every waiter must get the same complete image"
    assert len(calls) == 1, "one resize per key per process"
    assert responses[0].headers["cache-control"].startswith("public")
    assert responses[0].headers["etag"]
    assert sorted(p.name for p in (cache / "resized" / "300" / "aa").iterdir()) == [sha1], (
        "no staging files left behind"
    )
    with Image.open(cache / "resized" / "300" / "aa" / sha1) as out:
        assert out.size == (300, 300) and out.mode == "RGB"
        assert min(out.getpixel((150, 150))) > 240, "transparent cover flattens to white"

    # A conditional request against the published file still 304s.
    etag = responses[0].headers["etag"]
    again = await auth_client.get(
        f"/api/art/file/{sha1}?max_size=300", headers={"If-None-Match": etag}
    )
    assert again.status_code == 304
    assert len(calls) == 1
