"""Manual MusicBrainz release-group overrides for chart entries."""

import pytest
from httpx import AsyncClient

from app.auth import hash_password
from app.charts import ChartEntry, apply_match_overrides, load_match_overrides

RG_MBID = "c172c2de-65c8-400b-a742-caaa2b9ffbe5"


@pytest.fixture
async def chart_row(db):
    await db.execute("DELETE FROM chart_match_override")
    await db.execute("DELETE FROM chart_album")
    await db.execute(
        """
        INSERT INTO chart_album
        (position, title, artist, last_week, peak, weeks, status, release_mbid, release_group_mbid)
        VALUES (1, 'Mother Of Pearl', 'Freya Ridings', '2', '1', '5', 'up', '', 'wrong-mbid')
        """
    )
    yield
    await db.execute("DELETE FROM chart_match_override")
    await db.execute("DELETE FROM chart_album")


@pytest.mark.asyncio
async def test_set_override_updates_current_chart(auth_client: AsyncClient, db, chart_row):
    resp = await auth_client.put(
        "/api/charts/override",
        json={
            "artist": "Freya Ridings",
            "title": "Mother Of Pearl",
            "release_group_mbid": RG_MBID,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["release_group_mbid"] == RG_MBID

    row = await db.fetchrow("SELECT release_group_mbid, release_mbid FROM chart_album WHERE position = 1")
    assert row["release_group_mbid"] == RG_MBID
    assert row["release_mbid"] == ""

    chart = (await auth_client.get("/api/charts")).json()
    assert chart[0]["release_group_mbid"] == RG_MBID
    assert chart[0]["overridden"] is True


@pytest.mark.asyncio
async def test_set_override_accepts_musicbrainz_url(auth_client: AsyncClient, db, chart_row):
    resp = await auth_client.put(
        "/api/charts/override",
        json={
            "artist": "Freya Ridings",
            "title": "Mother Of Pearl",
            "release_group_mbid": f"https://musicbrainz.org/release-group/{RG_MBID}",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["release_group_mbid"] == RG_MBID


@pytest.mark.asyncio
async def test_set_override_rejects_garbage(auth_client: AsyncClient, chart_row):
    resp = await auth_client.put(
        "/api/charts/override",
        json={"artist": "A", "title": "B", "release_group_mbid": "not-a-uuid"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upsert_replaces_existing_override(auth_client: AsyncClient, db, chart_row):
    other = "11111111-2222-3333-4444-555555555555"
    for mbid in (other, RG_MBID):
        resp = await auth_client.put(
            "/api/charts/override",
            json={"artist": "Freya Ridings", "title": "Mother Of Pearl", "release_group_mbid": mbid},
        )
        assert resp.status_code == 200

    rows = await db.fetch("SELECT release_group_mbid FROM chart_match_override")
    assert [r["release_group_mbid"] for r in rows] == [RG_MBID]


@pytest.mark.asyncio
async def test_delete_override(auth_client: AsyncClient, db, chart_row):
    await auth_client.put(
        "/api/charts/override",
        json={"artist": "Freya Ridings", "title": "Mother Of Pearl", "release_group_mbid": RG_MBID},
    )
    resp = await auth_client.request(
        "DELETE",
        "/api/charts/override",
        json={"artist": "freya ridings", "title": "mother of pearl"},
    )
    assert resp.status_code == 200
    assert await db.fetchval("SELECT count(*) FROM chart_match_override") == 0

    resp = await auth_client.request(
        "DELETE",
        "/api/charts/override",
        json={"artist": "Freya Ridings", "title": "Mother Of Pearl"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_override_requires_admin(client: AsyncClient, db, chart_row):
    await db.execute('DELETE FROM "user" WHERE username = $1', "chart_nonadmin")
    await db.fetchrow(
        """
        INSERT INTO "user" (username, email, password_hash, display_name, is_admin, created_at)
        VALUES ($1, $2, $3, $4, FALSE, NOW())
        RETURNING *
        """,
        "chart_nonadmin",
        "chart_nonadmin@example.com",
        hash_password("password123"),
        "Chart Nonadmin",
    )
    login = await client.post(
        "/api/auth/login", json={"username": "chart_nonadmin", "password": "password123"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.put(
        "/api/charts/override",
        headers=headers,
        json={"artist": "A", "title": "B", "release_group_mbid": RG_MBID},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_enrichment_applies_override_case_insensitively(db, chart_row):
    await db.execute(
        "INSERT INTO chart_match_override (artist, title, release_group_mbid) VALUES ($1, $2, $3)",
        "Freya Ridings", "Mother Of Pearl", RG_MBID,
    )
    entries = [
        ChartEntry(
            position=1, title="MOTHER OF PEARL", artist="FREYA RIDINGS",
            last_week="2", peak="1", weeks="5", status="up",
        ),
        ChartEntry(
            position=2, title="Other Album", artist="Other Artist",
            last_week="", peak="", weeks="1", status="new entry",
        ),
    ]

    overrides = await load_match_overrides()
    remaining = apply_match_overrides(entries, overrides)

    assert entries[0].release_group_mbid == RG_MBID
    assert entries[0].confidence == 100
    # Only the non-overridden entry still needs a MusicBrainz lookup.
    assert remaining == [entries[1]]
