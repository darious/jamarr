"""ListenBrainz account endpoints: connect with a user token, toggle, disconnect, status."""

import logging
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app import listenbrainz as lb
from app.api.deps import get_current_user_jwt, get_current_user_jwt_released
from app.db import db_conn, get_db
from app.listenbrainz_submissions import (
    kick_submissions,
    skip_paused_plays,
    submission_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["listenbrainz"])


class ConnectRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=200)
    # Local plays at or after this time are sent. Defaults to now, or keeps
    # the existing value when the same ListenBrainz account reconnects.
    since: Optional[datetime] = None


class ToggleRequest(BaseModel):
    enabled: bool


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


@router.get("/api/listenbrainz/status")
async def get_listenbrainz_status(
    db: asyncpg.Connection = Depends(get_db),
    user: asyncpg.Record = Depends(get_current_user_jwt),
):
    """ListenBrainz connection and submission state for the current user. Never returns the token."""
    connected = bool(user.get("listenbrainz_token"))
    result = {
        "connected": connected,
        "username": user.get("listenbrainz_username"),
        "enabled": bool(user.get("listenbrainz_enabled")) if connected else False,
        "connected_at": _iso(user.get("listenbrainz_connected_at")),
        "since": _iso(user.get("listenbrainz_since")),
        "auth_error": user.get("listenbrainz_auth_error"),
    }
    if connected:
        result.update(await submission_summary(db, user["id"]))
    return result


@router.post("/api/listenbrainz/connect")
async def connect_listenbrainz(
    payload: ConnectRequest,
    user: asyncpg.Record = Depends(get_current_user_jwt_released),
):
    """Validate a ListenBrainz user token and store it.

    The token is checked against ListenBrainz before it is saved, so a typo
    fails here rather than silently at the first submission.
    """
    token = payload.token.strip()
    if not token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Token is empty")
    try:
        username = await lb.get_client().validate_token(token)
    except (lb.ListenBrainzUnavailableError, lb.ListenBrainzRateLimitedError) as exc:
        logger.info("ListenBrainz token check failed: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ListenBrainz is not responding. Try again later.",
        ) from exc
    except lb.ListenBrainzError as exc:
        logger.warning("ListenBrainz token check error: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"ListenBrainz error: {exc}"
        ) from exc
    if not username:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "ListenBrainz did not accept that token"
        )

    now = datetime.now(timezone.utc)
    if payload.since is not None:
        since = payload.since
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
    elif (
        user.get("listenbrainz_token")
        and user.get("listenbrainz_username") == username
        and user.get("listenbrainz_since")
    ):
        # Same account, new token (e.g. after a reset): carry on where it was.
        since = user["listenbrainz_since"]
    else:
        since = now

    async with db_conn() as db:
        if user.get("listenbrainz_paused_at") and since == user.get("listenbrainz_since"):
            # Reconnecting while paused resumes; the paused plays stay unsent.
            await skip_paused_plays(db, user["id"])
        await db.execute(
            """
            UPDATE "user"
            SET listenbrainz_token = $1,
                listenbrainz_username = $2,
                listenbrainz_enabled = TRUE,
                listenbrainz_connected_at = $3,
                listenbrainz_since = $4,
                listenbrainz_paused_at = NULL,
                listenbrainz_auth_error = NULL
            WHERE id = $5
            """,
            token,
            username,
            now,
            since,
            user["id"],
        )
    logger.info("User %s connected ListenBrainz account %s", user["username"], username)
    kick_submissions()
    return {"ok": True, "username": username, "since": since.isoformat()}


@router.post("/api/listenbrainz/disconnect")
async def disconnect_listenbrainz(
    db: asyncpg.Connection = Depends(get_db),
    user: asyncpg.Record = Depends(get_current_user_jwt),
):
    """Forget the ListenBrainz token. Plays made while disconnected are never sent."""
    await db.execute(
        """
        UPDATE "user"
        SET listenbrainz_token = NULL,
            listenbrainz_username = NULL,
            listenbrainz_enabled = FALSE,
            listenbrainz_connected_at = NULL,
            listenbrainz_since = NULL,
            listenbrainz_paused_at = NULL,
            listenbrainz_auth_error = NULL
        WHERE id = $1
        """,
        user["id"],
    )
    logger.info("User %s disconnected ListenBrainz", user["username"])
    return {"ok": True}


@router.post("/api/listenbrainz/toggle")
async def toggle_listenbrainz(
    payload: ToggleRequest,
    db: asyncpg.Connection = Depends(get_db),
    user: asyncpg.Record = Depends(get_current_user_jwt),
):
    """Pause or resume submission. Plays made while paused are not sent later."""
    if not user.get("listenbrainz_token"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ListenBrainz account not connected")
    if payload.enabled and not user.get("listenbrainz_enabled"):
        await skip_paused_plays(db, user["id"])
        await db.execute(
            'UPDATE "user" SET listenbrainz_enabled = TRUE WHERE id = $1', user["id"]
        )
        kick_submissions()
    elif not payload.enabled and user.get("listenbrainz_enabled"):
        await db.execute(
            """
            UPDATE "user" SET listenbrainz_enabled = FALSE, listenbrainz_paused_at = NOW()
            WHERE id = $1
            """,
            user["id"],
        )
    return {"ok": True, "enabled": payload.enabled}
