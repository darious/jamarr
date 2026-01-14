#!/usr/bin/env python3
"""
Demo script to test Phase 1 JWT authentication functionality.

Run with: docker compose exec jamarr python scripts/demo_jwt_phase1.py
Or: ./demo-jwt.sh
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Add app directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.auth_tokens import (
    create_access_token,
    verify_access_token,
    generate_refresh_token,
    hash_refresh_token,
)
from app.auth import (
    create_refresh_session,
    get_refresh_session,
    revoke_refresh_session,
    revoke_all_user_sessions,
)
from app.db import init_db, close_db, get_pool


async def demo():
    """Demonstrate Phase 1 JWT functionality."""
    print("=" * 70)
    print("Phase 1 JWT Authentication Demo")
    print("=" * 70)
    print()

    # Initialize database
    print("📦 Initializing database connection...")
    await init_db()
    pool = get_pool()
    
    async with pool.acquire() as db:
        # Get or create a test user
        user = await db.fetchrow('SELECT * FROM "user" LIMIT 1')
        if not user:
            print("❌ No users found in database. Please create a user first.")
            return
        
        user_id = user["id"]
        username = user["username"]
        print(f"✅ Using user: {username} (ID: {user_id})")
        print()

        # 1. JWT Access Token Demo
        print("🔑 JWT Access Token Demo")
        print("-" * 70)
        
        # Create access token
        access_token = create_access_token(
            user_id=user_id,
            expires_delta=timedelta(minutes=10)
        )
        print(f"Created access token (first 50 chars): {access_token[:50]}...")
        
        # Verify access token
        claims = verify_access_token(access_token)
        print(f"✅ Token verified successfully!")
        print(f"   User ID from token: {claims['sub']}")
        print(f"   Issuer: {claims['iss']}")
        print(f"   Audience: {claims['aud']}")
        print(f"   Expires: {datetime.fromtimestamp(claims['exp'], tz=timezone.utc)}")
        print()

        # 2. Refresh Token Demo
        print("🔄 Refresh Token Demo")
        print("-" * 70)
        
        # Generate refresh token
        refresh_token = generate_refresh_token()
        print(f"Generated refresh token: {refresh_token[:30]}...")
        
        # Hash refresh token
        token_hash = hash_refresh_token(refresh_token)
        print(f"Token hash (SHA-256): {token_hash[:40]}...")
        print()

        # 3. Refresh Session Database Demo
        print("💾 Refresh Session Database Demo")
        print("-" * 70)
        
        # Create refresh session
        expires_at = datetime.now(timezone.utc) + timedelta(days=21)
        session_id = await create_refresh_session(
            db=db,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            user_agent="Demo Script / Phase 1 Test",
            ip="127.0.0.1"
        )
        print(f"✅ Created refresh session ID: {session_id}")
        
        # Retrieve refresh session
        session = await get_refresh_session(db, token_hash)
        if session:
            print(f"✅ Retrieved session for user: {session['username']}")
            print(f"   Created: {session['created_at']}")
            print(f"   Expires: {session['expires_at']}")
            print(f"   User Agent: {session['user_agent']}")
        print()

        # 4. Session Management Demo
        print("🔧 Session Management Demo")
        print("-" * 70)
        
        # Create a second session
        token2 = generate_refresh_token()
        hash2 = hash_refresh_token(token2)
        session_id2 = await create_refresh_session(
            db=db,
            user_id=user_id,
            token_hash=hash2,
            expires_at=expires_at,
            user_agent="Demo Script / Second Session",
            ip="127.0.0.1"
        )
        print(f"✅ Created second session ID: {session_id2}")
        
        # Count active sessions
        count = await db.fetchval(
            "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
            user_id
        )
        print(f"✅ User has {count} active sessions")
        print()

        # Revoke first session
        await revoke_refresh_session(db, token_hash)
        print(f"✅ Revoked session {session_id}")
        
        # Try to retrieve revoked session
        revoked_session = await get_refresh_session(db, token_hash)
        if revoked_session is None:
            print(f"✅ Revoked session correctly returns None")
        print()

        # 5. Cleanup Demo
        print("🧹 Cleanup Demo")
        print("-" * 70)
        
        # Revoke all user sessions
        await revoke_all_user_sessions(db, user_id)
        print(f"✅ Revoked all sessions for user {username}")
        
        # Verify all sessions revoked
        active_count = await db.fetchval(
            "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
            user_id
        )
        print(f"✅ Active sessions remaining: {active_count}")
        print()

    # Close database
    await close_db()
    
    print("=" * 70)
    print("✅ Phase 1 Demo Complete!")
    print()
    print("What Phase 1 Provides:")
    print("  ✅ JWT token creation and verification")
    print("  ✅ Refresh token generation and hashing")
    print("  ✅ Database storage for refresh sessions")
    print("  ✅ Session management (create, retrieve, revoke)")
    print()
    print("What's Still Missing (Phase 2):")
    print("  ⏳ API endpoints don't use JWT yet (still use session cookies)")
    print("  ⏳ /api/auth/login doesn't return JWT tokens")
    print("  ⏳ /api/auth/refresh endpoint doesn't exist")
    print("  ⏳ Frontend doesn't use JWT tokens")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(demo())
