import pytest
import uuid
from httpx import AsyncClient
from app.auth import hash_password

def random_user():
    uid = str(uuid.uuid4())[:8]
    return {
        "username": f"user_{uid}",
        "email": f"user_{uid}@example.com",
        "password": "password123",
        "display_name": f"User {uid}"
    }


async def seed_user(db, user_data):
    return await db.fetchrow(
        """
        INSERT INTO "user" (username, email, password_hash, display_name, is_admin, created_at)
        VALUES ($1, $2, $3, $4, $5, NOW())
        RETURNING *
        """,
        user_data["username"],
        user_data["email"],
        hash_password(user_data["password"]),
        user_data.get("display_name"),
        user_data.get("is_admin", False),
    )

@pytest.mark.asyncio
async def test_public_signup_removed(client: AsyncClient, db):
    u = random_user()
    response = await client.post("/api/auth/signup", json=u)
    assert response.status_code in {404, 405}


@pytest.mark.asyncio
async def test_create_user_flow(auth_client: AsyncClient, db, auth_token):
    u = random_user()

    response = await auth_client.post("/api/auth/users", json=u)
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == u["username"]
    assert data["email"] == u["email"]
    assert "access_token" not in data
    assert "jamarr_refresh" not in response.cookies

    response = await auth_client.post("/api/auth/users", json=u)
    assert response.status_code == 400
    assert "already taken" in response.json()["detail"]

    u2 = random_user()
    u2["password"] = "short"
    response = await auth_client.post("/api/auth/users", json=u2)
    assert response.status_code == 400
    assert "at least 8 characters" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_user_requires_auth(client: AsyncClient, db):
    response = await client.post("/api/auth/users", json=random_user())
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_user_requires_admin(client: AsyncClient, db):
    normal = random_user()
    await seed_user(db, normal)
    login_response = await client.post("/api/auth/login", json={
        "username": normal["username"],
        "password": normal["password"],
    })
    access_token = login_response.json()["access_token"]

    response = await client.post(
        "/api/auth/users",
        json=random_user(),
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Admin privileges required"

@pytest.mark.asyncio
async def test_login_flow(client: AsyncClient, db):
    u = random_user()
    await seed_user(db, u)
    
    # 1. Login Success
    response = await client.post("/api/auth/login", json={
        "username": u["username"],
        "password": u["password"]
    })
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert "jamarr_refresh" in response.cookies
    assert response.json()["username"] == u["username"]
    assert response.json()["is_admin"] is False
    
    # 2. Login Invalid Password
    response = await client.post("/api/auth/login", json={
        "username": u["username"],
        "password": "wrongpassword"
    })
    assert response.status_code == 401
    
    # 3. Login Non-existent User
    response = await client.post("/api/auth/login", json={
        "username": f"fake_{uuid.uuid4()}",
        "password": "password123"
    })
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_me_and_logout(client: AsyncClient, db):
    u = random_user()

    # Unauthenticated
    # (Ensure we are logged out first, as client session might persist if reused, though fixture usually yields fresh client)
    response = await client.get("/api/auth/me")
    assert response.status_code == 401
    
    await seed_user(db, u)
    login_response = await client.post("/api/auth/login", json={
        "username": u["username"],
        "password": u["password"]
    })
    access_token = login_response.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {access_token}"}
    
    # Authenticated
    response = await client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["username"] == u["username"]
    assert response.json()["is_admin"] is False
    
    # Logout
    response = await client.post("/api/auth/logout")
    assert response.status_code == 200
    
    # Check access token cleared client-side
    response = await client.get("/api/auth/me")
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_profile_update(auth_client: AsyncClient, db, auth_token):
    # Note: 'auth_token' logs in 'testuser' (helper fixture). 
    # Since we don't truncate, 'testuser' might have modified state from prev runs.
    # We should ensure we are testing expected transitions.
    
    new_email = f"updated_{uuid.uuid4()}@example.com"
    
    # 1. Update Profile Success
    response = await auth_client.put("/api/auth/profile", json={
        "email": new_email,
        "display_name": "Updated Name"
    })
    
    # If this fails with 400 'email taken', it implies UUID collision (unlikely) or logic error.
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == new_email
    assert data["display_name"] == "Updated Name"
    
    # Verify persistence
    response = await auth_client.get("/api/auth/me")
    # client session should still be valid
    assert response.status_code == 200
    assert response.json()["email"] == new_email

    # 2. Update Email Conflict
    # Create another user first
    other = random_user()
    
    # We need a fresh client to create the 'other' user to avoid logging out 'testuser' from the main client
    # Or just logout/login.
    
    await seed_user(db, other)
    
    # Try to change testuser email to other's email
    response = await auth_client.put("/api/auth/profile", json={
        "email": other["email"]
    })
    assert response.status_code == 400
    assert "Email already in use" in response.json()["detail"]

@pytest.mark.asyncio
async def test_password_change(auth_client: AsyncClient, db, auth_token):
    # 'auth_token' user (testuser)
    # We need to know current password. 
    # The fixture ensures it's 'password123' (by resetting if needed).
    
    new_pass = "newpassword123"
    
    # 1. Change Success
    response = await auth_client.post("/api/auth/password", json={
        "current_password": "password123",
        "new_password": new_pass
    })
    assert response.status_code == 200
    
    # 2. Login with new password
    await auth_client.post("/api/auth/logout")
    response = await auth_client.post("/api/auth/login", json={
        "username": "testuser",
        "password": new_pass
    })
    assert response.status_code == 200
    
    # 3. Fail with old password (revert state for next tests?)
    # Ideally tests shouldn't leave state 'dirty' for the 'testuser' since it's shared via auth_token.
    # We should revert the password back to 'password123' so other tests starting after this one (if any) 
    # don't fail logging in.
    
    await auth_client.post("/api/auth/logout")
    response = await auth_client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "password123"
    })
    assert response.status_code == 401
    
    # Revert password for future tests
    # Log back in with new pass
    await auth_client.post("/api/auth/login", json={"username": "testuser", "password": new_pass})
    await auth_client.post("/api/auth/password", json={
        "current_password": new_pass,
        "new_password": "password123"
    })


@pytest.mark.asyncio
async def test_accent_color_preferences(auth_client: AsyncClient, db, auth_token):
    """Test accent color preferences endpoint"""
    
    # 1. Get current user - should have default accent color
    response = await auth_client.get("/api/auth/me")
    assert response.status_code == 200
    user_data = response.json()
    assert "accent_color" in user_data
    assert user_data["accent_color"] == "#ff006e"  # Default pink
    
    # 2. Update accent color to cyan
    response = await auth_client.patch("/api/auth/preferences", json={
        "accent_color": "#00d9ff"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["accent_color"] == "#00d9ff"
    
    # 3. Verify persistence
    response = await auth_client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["accent_color"] == "#00d9ff"
    
    # 4. Test invalid color format
    response = await auth_client.patch("/api/auth/preferences", json={
        "accent_color": "invalid"
    })
    assert response.status_code == 400
    assert "Invalid color format" in response.json()["detail"]
    
    # 5. Test invalid hex (wrong length)
    response = await auth_client.patch("/api/auth/preferences", json={
        "accent_color": "#fff"
    })
    assert response.status_code == 400
    
    # 6. Update to another valid color (purple)
    response = await auth_client.patch("/api/auth/preferences", json={
        "accent_color": "#a855f7"
    })
    assert response.status_code == 200
    assert response.json()["accent_color"] == "#a855f7"
    
    # 7. Reset to default pink for other tests
    await auth_client.patch("/api/auth/preferences", json={
        "accent_color": "#ff006e"
    })


@pytest.mark.asyncio
async def test_theme_mode_preferences(auth_client: AsyncClient, db, auth_token):
    """Test theme mode preferences endpoint"""
    
    # 1. Get current user - should have default theme mode
    response = await auth_client.get("/api/auth/me")
    assert response.status_code == 200
    user_data = response.json()
    assert "theme_mode" in user_data
    assert user_data["theme_mode"] == "dark"  # Default
    
    # 2. Update theme mode to light
    response = await auth_client.patch("/api/auth/preferences", json={
        "theme_mode": "light"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["theme_mode"] == "light"
    
    # 3. Verify persistence
    response = await auth_client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["theme_mode"] == "light"
    
    # 4. Test invalid theme mode
    response = await auth_client.patch("/api/auth/preferences", json={
        "theme_mode": "invalid"
    })
    assert response.status_code == 400
    assert "Invalid theme mode" in response.json()["detail"]
    
    # 5. Reset to default dark
    await auth_client.patch("/api/auth/preferences", json={
        "theme_mode": "dark"
    })
