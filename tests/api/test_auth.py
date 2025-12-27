import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_signup_flow(client: AsyncClient, db):
    # 1. Signup Success
    response = await client.post("/api/auth/signup", json={
        "username": "newuser",
        "email": "new@example.com",
        "password": "valid_password",
        "display_name": "New User"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "newuser"
    assert "jamarr_session" in response.cookies
    
    # 2. Signup Duplicate
    response = await client.post("/api/auth/signup", json={
        "username": "newuser",
        "email": "another@example.com",
        "password": "valid_password"
    })
    assert response.status_code == 400
    assert "already taken" in response.json()["detail"]

    # 3. Signup Invalid Password
    response = await client.post("/api/auth/signup", json={
        "username": "shortpass",
        "email": "short@example.com",
        "password": "short",
    })
    assert response.status_code == 400
    assert "at least 8 characters" in response.json()["detail"]

@pytest.mark.asyncio
async def test_login_flow(client: AsyncClient, db):
    # Setup user
    await client.post("/api/auth/signup", json={
        "username": "loginuser",
        "email": "login@example.com",
        "password": "password123"
    })
    await client.post("/api/auth/logout")
    
    # 1. Login Success
    response = await client.post("/api/auth/login", json={
        "username": "loginuser",
        "password": "password123"
    })
    assert response.status_code == 200
    assert "jamarr_session" in response.cookies
    assert response.json()["username"] == "loginuser"
    
    # 2. Login Invalid Password
    response = await client.post("/api/auth/login", json={
        "username": "loginuser",
        "password": "wrongpassword"
    })
    assert response.status_code == 401
    
    # 3. Login Non-existent User
    response = await client.post("/api/auth/login", json={
        "username": "fakeuser",
        "password": "password123"
    })
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_me_and_logout(client: AsyncClient, db):
    # Unauthenticated
    response = await client.get("/api/auth/me")
    assert response.status_code == 401
    
    # Login
    await client.post("/api/auth/signup", json={
        "username": "meuser",
        "email": "me@example.com",
        "password": "password123"
    })
    
    # Authenticated
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["username"] == "meuser"
    
    # Logout
    response = await client.post("/api/auth/logout")
    assert response.status_code == 200
    assert "jamarr_session" not in response.cookies # Should be cleared/expired (httpx handles this slightly differently depending on implementation, but response should request deletion)
    
    # Check session cleared
    # Note: cookie jar might still have it if max-age=0, but next request shouldn't send it effectively?
    # Or specifically verify the Set-Cookie header for deletion
    response = await client.get("/api/auth/me")
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_profile_update(client: AsyncClient, db, auth_token):
    # 1. Update Profile Success
    response = await client.put("/api/auth/profile", json={
        "email": "updated@example.com",
        "display_name": "Updated Name"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "updated@example.com"
    assert data["display_name"] == "Updated Name"
    
    # Verify persistence
    response = await client.get("/api/auth/me")
    assert response.json()["email"] == "updated@example.com"

    # 2. Update Email Conflict
    # Create another user first
    await client.post("/api/auth/signup", json={
        "username": "other",
        "email": "taken@example.com",
        "password": "password123"
    })
    # Log back in as first user (cookie handling in tests with single client can be tricky if we don't manage cookies manually or use auth_token fixture properly)
    # The 'auth_token' fixture logs in 'testuser' at start. 
    # But wait, above we called signup for 'other', which overwrote cookies in the single `client` instance.
    # We need to re-login as the first user or use separate clients.
    # Let's re-login as testuser (created by auth_token fixture)
    await client.post("/api/auth/login", json={"username": "testuser", "password": "password123"})

    response = await client.put("/api/auth/profile", json={
        "email": "taken@example.com"
    })
    assert response.status_code == 400
    assert "Email already in use" in response.json()["detail"]

@pytest.mark.asyncio
async def test_password_change(client: AsyncClient, db, auth_token):
    # 1. Change Success
    response = await client.post("/api/auth/password", json={
        "current_password": "password123",
        "new_password": "newpassword123"
    })
    assert response.status_code == 200
    
    # 2. Login with new password
    await client.post("/api/auth/logout")
    response = await client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "newpassword123"
    })
    assert response.status_code == 200
    
    # 3. Fail with old password
    await client.post("/api/auth/logout")
    response = await client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "password123"
    })
    assert response.status_code == 401
