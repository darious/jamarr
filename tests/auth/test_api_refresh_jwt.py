"""Integration tests for JWT refresh endpoint."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_refresh_with_valid_cookie(client: AsyncClient, test_user):
    """Test that refresh returns new access token with valid refresh cookie."""
    # First login to get refresh cookie
    login_response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"}
    )
    assert login_response.status_code == 200
    
    # Use refresh endpoint
    refresh_response = await client.post("/api/auth/refresh")
    
    assert refresh_response.status_code == 200
    data = refresh_response.json()
    
    # Should have new access token
    assert "access_token" in data
    assert isinstance(data["access_token"], str)
    assert len(data["access_token"]) > 0
    
    # Should have token_type
    assert data.get("token_type") == "bearer"
    
    # Verify it's a valid JWT structure (header.payload.signature)
    assert data["access_token"].count(".") == 2
    assert len(data["access_token"]) > 100  # JWTs are long strings



@pytest.mark.asyncio
async def test_refresh_rotates_token(client: AsyncClient, test_user, db):
    """Test that refresh rotates the refresh token (old one revoked)."""
    # Login to get initial refresh cookie
    login_response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"}
    )
    assert login_response.status_code == 200
    initial_refresh = login_response.cookies["jamarr_refresh"]
    
    # Count active sessions before refresh
    await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
        test_user["id"]
    )
    
    # Refresh token
    refresh_response = await client.post("/api/auth/refresh")
    assert refresh_response.status_code == 200
    
    # Should have new refresh cookie
    new_refresh = refresh_response.cookies.get("jamarr_refresh")
    assert new_refresh is not None
    assert new_refresh != initial_refresh
    
    # Should still have only 1 active session (old revoked, new created)
    count_after = await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
        test_user["id"]
    )
    assert count_after == 1


@pytest.mark.asyncio
async def test_refresh_without_cookie(client: AsyncClient):
    """Test that refresh without cookie returns 401."""
    response = await client.post("/api/auth/refresh")
    
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_with_revoked_token(client: AsyncClient, test_user, db):
    """Test that refresh with revoked token returns 401."""
    from app.auth_tokens import generate_refresh_token, hash_refresh_token
    from app.auth import create_refresh_session, revoke_refresh_session
    from datetime import datetime, timedelta, timezone
    
    # Create and immediately revoke a refresh session
    token = generate_refresh_token()
    token_hash = hash_refresh_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=21)
    
    await create_refresh_session(
        db=db,
        user_id=test_user["id"],
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent="Test",
        ip="127.0.0.1"
    )
    await revoke_refresh_session(db, token_hash)
    
    # Try to use revoked token
    client.cookies.set("jamarr_refresh", token)
    response = await client.post("/api/auth/refresh")
    
    assert response.status_code == 401



@pytest.mark.asyncio
async def test_refresh_with_expired_token(client: AsyncClient, test_user, db):
    """Test that refresh with expired token returns 401."""
    from app.auth_tokens import generate_refresh_token, hash_refresh_token
    from app.auth import create_refresh_session
    from datetime import datetime, timedelta, timezone
    
    # Create an already-expired refresh session
    token = generate_refresh_token()
    token_hash = hash_refresh_token(token)
    expires_at = datetime.now(timezone.utc) - timedelta(days=1)  # Already expired
    
    await create_refresh_session(
        db=db,
        user_id=test_user["id"],
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent="Test",
        ip="127.0.0.1"
    )
    
    # Try to use expired token
    client.cookies.set("jamarr_refresh", token)
    response = await client.post("/api/auth/refresh")
    
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_immediate_replay_is_reissued(client: AsyncClient, test_user):
    """An immediate replay of a just-rotated token (lost response / concurrent
    refresh) is benign: the family still has a live tip within the grace window,
    so we re-issue a fresh token instead of logging the client out."""
    login_response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"}
    )
    assert login_response.status_code == 200
    first_refresh = login_response.cookies["jamarr_refresh"]

    # Rotate once (first_refresh -> S, S is now the live tip)
    refresh1 = await client.post("/api/auth/refresh")
    assert refresh1.status_code == 200

    # Replay the old token immediately: benign, re-issued (not 401)
    client.cookies.set("jamarr_refresh", first_refresh)
    refresh2 = await client.post("/api/auth/refresh")
    assert refresh2.status_code == 200
    reissued = refresh2.cookies.get("jamarr_refresh")
    assert reissued is not None

    # The re-issued token must itself be usable
    client.cookies.set("jamarr_refresh", reissued)
    refresh3 = await client.post("/api/auth/refresh")
    assert refresh3.status_code == 200


@pytest.mark.asyncio
async def test_refresh_immediate_replay_keeps_one_live_session(
    client: AsyncClient, test_user, db
):
    """Re-issuing a benign replay must leave exactly one live token in the family."""
    login_response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"},
    )
    assert login_response.status_code == 200
    first_refresh = login_response.cookies["jamarr_refresh"]

    refresh1 = await client.post("/api/auth/refresh")
    assert refresh1.status_code == 200

    # Replay the just-rotated token immediately -> re-issued
    client.cookies.set("jamarr_refresh", first_refresh)
    refresh2 = await client.post("/api/auth/refresh")
    assert refresh2.status_code == 200

    # Still exactly one live session (old tip revoked, successor created)
    active = await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
        test_user["id"],
    )
    assert active == 1


@pytest.mark.asyncio
async def test_refresh_reuse_after_grace_revokes_family(
    client: AsyncClient, test_user, db
):
    """Replaying an old rotated token (past the grace window) is treated as
    theft and revokes that token's family."""
    from app.auth_tokens import hash_refresh_token

    login_response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"},
    )
    assert login_response.status_code == 200
    first_refresh = login_response.cookies["jamarr_refresh"]

    refresh1 = await client.post("/api/auth/refresh")
    assert refresh1.status_code == 200

    # Pretend the rotation happened well outside the grace window
    await db.execute(
        "UPDATE auth_refresh_session SET revoked_at = NOW() - INTERVAL '10 minutes' "
        "WHERE token_hash = $1",
        hash_refresh_token(first_refresh),
    )

    client.cookies.set("jamarr_refresh", first_refresh)
    refresh2 = await client.post("/api/auth/refresh")
    assert refresh2.status_code == 401

    # The whole family (this single-login user) must now be revoked
    active = await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
        test_user["id"],
    )
    assert active == 0


@pytest.mark.asyncio
async def test_reuse_detection_is_scoped_to_one_family(
    client: AsyncClient, test_user, db
):
    """Theft detection on one device's family must NOT sign the user out on
    their other devices (other families)."""
    import uuid
    from datetime import datetime, timedelta, timezone
    from app.auth_tokens import generate_refresh_token, hash_refresh_token
    from app.auth import create_refresh_session

    # Device A: a real login (family A, cookie a0)
    login = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"},
    )
    assert login.status_code == 200
    a0 = login.cookies["jamarr_refresh"]
    family_a = await db.fetchval(
        "SELECT family_id FROM auth_refresh_session WHERE token_hash = $1",
        hash_refresh_token(a0),
    )

    # Device B: an independent family with its own live token
    family_b = uuid.uuid4()
    b0 = generate_refresh_token()
    await create_refresh_session(
        db=db,
        user_id=test_user["id"],
        token_hash=hash_refresh_token(b0),
        expires_at=datetime.now(timezone.utc) + timedelta(days=21),
        user_agent="DeviceB",
        ip="127.0.0.1",
        family_id=family_b,
    )

    # Device A rotates (a0 -> a1)
    r1 = await client.post("/api/auth/refresh")
    assert r1.status_code == 200

    # Backdate a0's rotation and replay it -> reuse/theft on family A only
    await db.execute(
        "UPDATE auth_refresh_session SET revoked_at = NOW() - INTERVAL '10 minutes' "
        "WHERE token_hash = $1",
        hash_refresh_token(a0),
    )
    client.cookies.set("jamarr_refresh", a0)
    r2 = await client.post("/api/auth/refresh")
    assert r2.status_code == 401

    # Family A is fully revoked...
    a_live = await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE family_id = $1 AND revoked_at IS NULL",
        family_a,
    )
    assert a_live == 0

    # ...but family B (the other device) is untouched and still works.
    b_live = await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE family_id = $1 AND revoked_at IS NULL",
        family_b,
    )
    assert b_live == 1

    client.cookies.set("jamarr_refresh", b0)
    r3 = await client.post("/api/auth/refresh")
    assert r3.status_code == 200


@pytest.mark.asyncio
async def test_refresh_rejected_for_inactive_user(client: AsyncClient, test_user, db):
    """Refresh must fail once the user is deactivated."""
    login_response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"},
    )
    assert login_response.status_code == 200

    await db.execute(
        'UPDATE "user" SET is_active = FALSE WHERE id = $1', test_user["id"]
    )

    response = await client.post("/api/auth/refresh")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_many_rotations_keep_single_live_session(
    client: AsyncClient, test_user, db
):
    """Rotating repeatedly (normal usage) always leaves exactly one live token."""
    login_response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"},
    )
    assert login_response.status_code == 200

    for _ in range(10):
        r = await client.post("/api/auth/refresh")
        assert r.status_code == 200

    active = await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
        test_user["id"],
    )
    assert active == 1


@pytest.mark.asyncio
async def test_benign_replay_ping_pong_self_heals(client: AsyncClient, test_user, db):
    """Two holders one step apart (e.g. two tabs) can both keep refreshing: each
    replay re-issues from the live tip and the family stays alive throughout."""
    login_response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"},
    )
    assert login_response.status_code == 200
    t0 = login_response.cookies["jamarr_refresh"]

    r1 = await client.post("/api/auth/refresh")
    assert r1.status_code == 200
    t1 = r1.cookies["jamarr_refresh"]

    # Holder B still has the original t0 -> benign re-issue (revokes t1, mints t2)
    client.cookies.set("jamarr_refresh", t0)
    r2 = await client.post("/api/auth/refresh")
    assert r2.status_code == 200

    # Holder A still has t1 (now superseded) -> benign re-issue again
    client.cookies.set("jamarr_refresh", t1)
    r3 = await client.post("/api/auth/refresh")
    assert r3.status_code == 200

    # Family never died; still exactly one live token
    active = await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
        test_user["id"],
    )
    assert active == 1


@pytest.mark.asyncio
async def test_replay_after_family_fully_revoked_returns_401(
    client: AsyncClient, test_user
):
    """Once the family has no live tip (e.g. after logout), a replay is a plain
    401 with no crash and no attempt to recover."""
    login_response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"},
    )
    assert login_response.status_code == 200
    t0 = login_response.cookies["jamarr_refresh"]

    logout = await client.post("/api/auth/logout")
    assert logout.status_code == 200

    # Replay the token from the now-dead family
    client.cookies.set("jamarr_refresh", t0)
    replay = await client.post("/api/auth/refresh")
    assert replay.status_code == 401


@pytest.mark.asyncio
async def test_rotation_preserves_family_id(client: AsyncClient, test_user, db):
    """Rotating a token keeps the same family_id (one chain, one family)."""
    from app.auth_tokens import hash_refresh_token

    login = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"},
    )
    assert login.status_code == 200
    t0 = login.cookies["jamarr_refresh"]
    fam0 = await db.fetchval(
        "SELECT family_id FROM auth_refresh_session WHERE token_hash = $1",
        hash_refresh_token(t0),
    )

    r1 = await client.post("/api/auth/refresh")
    assert r1.status_code == 200
    t1 = r1.cookies["jamarr_refresh"]
    fam1 = await db.fetchval(
        "SELECT family_id FROM auth_refresh_session WHERE token_hash = $1",
        hash_refresh_token(t1),
    )

    assert fam0 is not None
    assert fam0 == fam1


@pytest.mark.asyncio
async def test_each_login_starts_a_new_family(client: AsyncClient, test_user, db):
    """Two separate logins produce two distinct families (independent devices)."""
    from app.auth_tokens import hash_refresh_token

    login1 = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"},
    )
    assert login1.status_code == 200
    t_a = login1.cookies["jamarr_refresh"]
    fam_a = await db.fetchval(
        "SELECT family_id FROM auth_refresh_session WHERE token_hash = $1",
        hash_refresh_token(t_a),
    )

    login2 = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"},
    )
    assert login2.status_code == 200
    t_b = login2.cookies["jamarr_refresh"]
    fam_b = await db.fetchval(
        "SELECT family_id FROM auth_refresh_session WHERE token_hash = $1",
        hash_refresh_token(t_b),
    )

    assert fam_a is not None and fam_b is not None
    assert fam_a != fam_b
