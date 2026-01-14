"""Unit tests for refresh token operations."""


def test_generate_refresh_token_format():
    """Test that generated refresh tokens are URL-safe strings with sufficient entropy."""
    from app.auth_tokens import generate_refresh_token
    
    token = generate_refresh_token()
    
    # Should be a string
    assert isinstance(token, str)
    
    # Should be URL-safe (no special characters that need encoding)
    assert all(c.isalnum() or c in "-_" for c in token)
    
    # Should have sufficient length (32 bytes = 43 chars in base64)
    assert len(token) >= 40


def test_generate_refresh_token_uniqueness():
    """Test that consecutive calls generate different tokens."""
    from app.auth_tokens import generate_refresh_token
    
    tokens = [generate_refresh_token() for _ in range(100)]
    
    # All tokens should be unique
    assert len(set(tokens)) == 100


def test_hash_refresh_token_deterministic():
    """Test that hashing the same token produces the same hash."""
    from app.auth_tokens import hash_refresh_token
    
    token = "test-token-123"
    
    hash1 = hash_refresh_token(token)
    hash2 = hash_refresh_token(token)
    
    assert hash1 == hash2
    assert isinstance(hash1, str)
    # SHA-256 hex digest is 64 characters
    assert len(hash1) == 64


def test_hash_refresh_token_different_inputs():
    """Test that different tokens produce different hashes."""
    from app.auth_tokens import hash_refresh_token
    
    token1 = "token-one"
    token2 = "token-two"
    
    hash1 = hash_refresh_token(token1)
    hash2 = hash_refresh_token(token2)
    
    assert hash1 != hash2


def test_hash_refresh_token_format():
    """Test that hash output is a valid hex string."""
    from app.auth_tokens import hash_refresh_token
    
    token = "test-token"
    hash_value = hash_refresh_token(token)
    
    # Should be lowercase hex
    assert all(c in "0123456789abcdef" for c in hash_value)
