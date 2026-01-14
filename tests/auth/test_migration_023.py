"""Test migration 023 - auth_refresh_session table creation."""
import pytest
import asyncpg


@pytest.mark.asyncio
async def test_migration_023_creates_table(db: asyncpg.Connection):
    """Test that migration 023 creates the auth_refresh_session table."""
    # Check table exists
    table_exists = await db.fetchval(
        """
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'auth_refresh_session'
        )
        """
    )
    assert table_exists, "auth_refresh_session table should exist after migration"
    
    # Check columns
    columns = await db.fetch(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'auth_refresh_session'
        ORDER BY ordinal_position
        """
    )
    
    column_dict = {col["column_name"]: col for col in columns}
    
    # Verify required columns exist
    assert "id" in column_dict
    assert "user_id" in column_dict
    assert "token_hash" in column_dict
    assert "created_at" in column_dict
    assert "expires_at" in column_dict
    assert "revoked_at" in column_dict
    assert "last_used_at" in column_dict
    assert "user_agent" in column_dict
    assert "ip" in column_dict
    
    # Verify column types
    assert column_dict["id"]["data_type"] == "bigint"
    assert column_dict["user_id"]["data_type"] == "bigint"
    assert column_dict["token_hash"]["data_type"] == "text"
    assert "timestamp" in column_dict["created_at"]["data_type"]
    assert "timestamp" in column_dict["expires_at"]["data_type"]
    assert "timestamp" in column_dict["revoked_at"]["data_type"]
    assert "timestamp" in column_dict["last_used_at"]["data_type"]
    
    # Verify nullable constraints
    assert column_dict["user_id"]["is_nullable"] == "NO"
    assert column_dict["token_hash"]["is_nullable"] == "NO"
    assert column_dict["revoked_at"]["is_nullable"] == "YES"
    assert column_dict["user_agent"]["is_nullable"] == "YES"
    assert column_dict["ip"]["is_nullable"] == "YES"


@pytest.mark.asyncio
async def test_migration_023_indexes(db: asyncpg.Connection):
    """Test that migration 023 creates required indexes."""
    # Get all indexes on the table
    indexes = await db.fetch(
        """
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'auth_refresh_session'
        """
    )
    
    index_names = [idx["indexname"] for idx in indexes]
    
    # Check for required indexes
    assert any("token_hash" in name for name in index_names), \
        "Should have index on token_hash"
    assert any("user_id" in name for name in index_names), \
        "Should have index on user_id"
    assert any("expires_at" in name for name in index_names), \
        "Should have index on expires_at"
    
    # Verify token_hash unique constraint/index
    unique_constraint = await db.fetchval(
        """
        SELECT COUNT(*)
        FROM pg_constraint
        WHERE conrelid = 'auth_refresh_session'::regclass
        AND contype = 'u'
        AND conkey = (SELECT array_agg(attnum) FROM pg_attribute 
                      WHERE attrelid = 'auth_refresh_session'::regclass 
                      AND attname = 'token_hash')
        """
    )
    assert unique_constraint > 0, "token_hash should have unique constraint"


@pytest.mark.asyncio
async def test_migration_023_foreign_key(db: asyncpg.Connection):
    """Test that migration 023 creates foreign key to user table."""
    # Check foreign key constraint exists
    fk_exists = await db.fetchval(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.table_name = 'auth_refresh_session'
            AND tc.constraint_type = 'FOREIGN KEY'
            AND ccu.table_name = 'user'
        )
        """
    )
    assert fk_exists, "Should have foreign key constraint to user table"


@pytest.mark.asyncio
async def test_migration_023_cascade_delete(db: asyncpg.Connection):
    """Test that deleting a user cascades to refresh sessions."""
    # Create a test user
    user = await db.fetchrow(
        """
        INSERT INTO "user" (username, email, password_hash, created_at)
        VALUES ($1, $2, $3, NOW())
        RETURNING id
        """,
        "cascade_test_user",
        "cascade@test.com",
        "hashed_password"
    )
    
    # Create a refresh session for the user
    await db.execute(
        """
        INSERT INTO auth_refresh_session 
        (user_id, token_hash, created_at, expires_at, last_used_at)
        VALUES ($1, $2, NOW(), NOW() + INTERVAL '21 days', NOW())
        """,
        user["id"],
        "test_hash_cascade"
    )
    
    # Delete the user
    await db.execute('DELETE FROM "user" WHERE id = $1', user["id"])
    
    # Verify session was also deleted (cascade)
    session_exists = await db.fetchval(
        "SELECT EXISTS (SELECT 1 FROM auth_refresh_session WHERE user_id = $1)",
        user["id"]
    )
    assert not session_exists, "Refresh session should be deleted when user is deleted"
