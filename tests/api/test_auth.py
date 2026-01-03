import pytest
import uuid
from httpx import AsyncClient

def random_user():
    uid = str(uuid.uuid4())[:8]
    return {
        "username": f"user_{uid}",
        "email": f"user_{uid}@example.com",
        "password": "password123",
        "display_name": f"User {uid}"
    }

@pytest.mark.asyncio
async def test_signup_flow(client: AsyncClient, db):
    u = random_user()
    
    # 1. Signup Success
    response = await client.post("/api/auth/signup", json=u)
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == u["username"]
    assert "jamarr_session" in response.cookies
    
    # 2. Signup Duplicate (Same User)
    response = await client.post("/api/auth/signup", json=u)
    assert response.status_code == 400
    assert "already taken" in response.json()["detail"]

    # 3. Signup Invalid Password
    u2 = random_user()
    u2["password"] = "short"
    response = await client.post("/api/auth/signup", json=u2)
    assert response.status_code == 400
    assert "at least 8 characters" in response.json()["detail"]

@pytest.mark.asyncio
async def test_login_flow(client: AsyncClient, db):
    u = random_user()
    
    # Setup user
    await client.post("/api/auth/signup", json=u)
    await client.post("/api/auth/logout")
    
    # 1. Login Success
    response = await client.post("/api/auth/login", json={
        "username": u["username"],
        "password": u["password"]
    })
    assert response.status_code == 200
    assert "jamarr_session" in response.cookies
    assert response.json()["username"] == u["username"]
    
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
    client.cookies.delete("jamarr_session") 
    
    response = await client.get("/api/auth/me")
    assert response.status_code == 401
    
    # Login (via Signup)
    await client.post("/api/auth/signup", json=u)
    
    # Authenticated
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["username"] == u["username"]
    
    # Logout
    response = await client.post("/api/auth/logout")
    assert response.status_code == 200
    assert "jamarr_session" not in response.cookies
    
    # Check session cleared
    response = await client.get("/api/auth/me")
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_profile_update(client: AsyncClient, db, auth_token):
    # Note: 'auth_token' logs in 'testuser' (helper fixture). 
    # Since we don't truncate, 'testuser' might have modified state from prev runs.
    # We should ensure we are testing expected transitions.
    
    new_email = f"updated_{uuid.uuid4()}@example.com"
    
    # 1. Update Profile Success
    response = await client.put("/api/auth/profile", json={
        "email": new_email,
        "display_name": "Updated Name"
    })
    
    # If this fails with 400 'email taken', it implies UUID collision (unlikely) or logic error.
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == new_email
    assert data["display_name"] == "Updated Name"
    
    # Verify persistence
    response = await client.get("/api/auth/me")
    # client session should still be valid
    assert response.status_code == 200
    assert response.json()["email"] == new_email

    # 2. Update Email Conflict
    # Create another user first
    other = random_user()
    
    # We need a fresh client to create the 'other' user to avoid logging out 'testuser' from the main client
    # Or just logout/login.
    
    current_cookie = client.cookies["jamarr_session"]
    
    # Create other user
    # We temporarily clear cookies to sign up 'other'
    client.cookies.delete("jamarr_session")
    await client.post("/api/auth/signup", json=other)
    
    # Restore 'testuser' login
    client.cookies["jamarr_session"] = current_cookie
    
    # Try to change testuser email to other's email
    response = await client.put("/api/auth/profile", json={
        "email": other["email"]
    })
    assert response.status_code == 400
    assert "Email already in use" in response.json()["detail"]

@pytest.mark.asyncio
async def test_password_change(client: AsyncClient, db, auth_token):
    # 'auth_token' user (testuser)
    # We need to know current password. 
    # The fixture ensures it's 'password123' (by resetting if needed).
    
    new_pass = "newpassword123"
    
    # 1. Change Success
    response = await client.post("/api/auth/password", json={
        "current_password": "password123",
        "new_password": new_pass
    })
    assert response.status_code == 200
    
    # 2. Login with new password
    await client.post("/api/auth/logout")
    response = await client.post("/api/auth/login", json={
        "username": "testuser",
        "password": new_pass
    })
    assert response.status_code == 200
    
    # 3. Fail with old password (revert state for next tests?)
    # Ideally tests shouldn't leave state 'dirty' for the 'testuser' since it's shared via auth_token.
    # We should revert the password back to 'password123' so other tests starting after this one (if any) 
    # don't fail logging in.
    
    await client.post("/api/auth/logout")
    response = await client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "password123"
    })
    assert response.status_code == 401
    
    # Revert password for future tests
    # Log back in with new pass
    await client.post("/api/auth/login", json={"username": "testuser", "password": new_pass})
    await client.post("/api/auth/password", json={
        "current_password": new_pass,
        "new_password": "password123"
    })


@pytest.mark.asyncio
async def test_accent_color_preferences(client: AsyncClient, db, auth_token):
    """Test accent color preferences endpoint"""
    
    # 1. Get current user - should have default accent color
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    user_data = response.json()
    assert "accent_color" in user_data
    assert user_data["accent_color"] == "#ff006e"  # Default pink
    
    # 2. Update accent color to cyan
    response = await client.patch("/api/auth/preferences", json={
        "accent_color": "#00d9ff"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["accent_color"] == "#00d9ff"
    
    # 3. Verify persistence
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["accent_color"] == "#00d9ff"
    
    # 4. Test invalid color format
    response = await client.patch("/api/auth/preferences", json={
        "accent_color": "invalid"
    })
    assert response.status_code == 400
    assert "Invalid color format" in response.json()["detail"]
    
    # 5. Test invalid hex (wrong length)
    response = await client.patch("/api/auth/preferences", json={
        "accent_color": "#fff"
    })
    assert response.status_code == 400
    
    # 6. Update to another valid color (purple)
    response = await client.patch("/api/auth/preferences", json={
        "accent_color": "#a855f7"
    })
    assert response.status_code == 200
    assert response.json()["accent_color"] == "#a855f7"
    
    # 7. Reset to default pink for other tests
    await client.patch("/api/auth/preferences", json={
        "accent_color": "#ff006e"
    })


@pytest.mark.asyncio
async def test_theme_mode_preferences(client: AsyncClient, db, auth_token):
    """Test theme mode preferences endpoint"""
    
    # 1. Get current user - should have default theme mode
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    user_data = response.json()
    assert "theme_mode" in user_data
    assert user_data["theme_mode"] == "dark"  # Default
    
    # 2. Update theme mode to light
    response = await client.patch("/api/auth/preferences", json={
        "theme_mode": "light"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["theme_mode"] == "light"
    
    # 3. Verify persistence
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["theme_mode"] == "light"
    
    # 4. Test invalid theme mode
    response = await client.patch("/api/auth/preferences", json={
        "theme_mode": "invalid"
    })
    assert response.status_code == 400
    assert "Invalid theme mode" in response.json()["detail"]
    
    # 5. Reset to default dark
    await client.patch("/api/auth/preferences", json={
        "theme_mode": "dark"
    })

