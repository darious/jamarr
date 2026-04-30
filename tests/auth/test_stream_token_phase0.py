from datetime import datetime, timezone

from jose import jwt


def test_phase0_stream_token_default_ttl_is_300_seconds():
    from app.auth_tokens import create_stream_token

    token = create_stream_token(track_id=901, user_id=42)
    claims = jwt.get_unverified_claims(token)

    issued_at = datetime.fromtimestamp(claims["iat"], tz=timezone.utc)
    expires_at = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)

    assert (expires_at - issued_at).total_seconds() == 300
    assert claims["sub"] == "stream"
    assert claims["track_id"] == 901
    assert claims["user_id"] == 42
    assert claims["aud"] == "jamarr-stream"
