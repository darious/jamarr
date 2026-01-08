"""
Last.fm API endpoints for authentication and account management.
"""

import logging
from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.auth import require_current_user
from app.db import get_db
from app import lastfm

logger = logging.getLogger(__name__)

router = APIRouter()


class ToggleRequest(BaseModel):
    enabled: bool


@router.get("/api/lastfm/status")
async def get_lastfm_status(
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
):
    """Get Last.fm connection status for current user."""
    user, _ = await require_current_user(request, db)
    
    return {
        "connected": bool(user.get("lastfm_session_key")),
        "username": user.get("lastfm_username"),
        "enabled": bool(user.get("lastfm_enabled", False)),
        "connected_at": user.get("lastfm_connected_at").isoformat() if user.get("lastfm_connected_at") else None,
    }


@router.get("/api/lastfm/auth/start")
async def start_lastfm_auth(
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
):
    """Initiate Last.fm authentication flow."""
    # Verify user is logged in
    await require_current_user(request, db)
    
    try:
        auth_url = lastfm.get_auth_url()
        return {"auth_url": auth_url}
    except Exception as e:
        logger.info(f"Generated Last.fm auth URL: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate Last.fm authentication"
        )


@router.get("/api/lastfm/callback")
async def lastfm_callback(
    token: str,
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
):
    """Handle Last.fm OAuth callback."""
    logger.info(f"Last.fm callback received with token: {token[:10]}...")
    
    try:
        user, _ = await require_current_user(request, db)
        logger.info(f"User authenticated: {user['username']}")
    except Exception as e:
        logger.error(f"Authentication failed in callback: {e}")
        return RedirectResponse(
            url="/settings/user?lastfm=auth_error",
            status_code=status.HTTP_302_FOUND
        )
    
    try:
        logger.info("Exchanging token for session key...")
        # Exchange token for session key
        session_key, username = await lastfm.get_session_key(token)
        logger.info(f"Got session key for Last.fm user: {username}")
        
        # Store session key in database and enable scrobbling by default
        await db.execute(
            """
            UPDATE "user"
            SET lastfm_session_key = $1,
                lastfm_username = $2,
                lastfm_enabled = TRUE,
                lastfm_connected_at = $3
            WHERE id = $4
            """,
            session_key,
            username,
            datetime.now(timezone.utc),
            user["id"]
        )
        
        logger.info(f"User {user['username']} connected Last.fm account: {username}")
        
        # Redirect to settings page with success message
        return RedirectResponse(
            url="/settings/user?lastfm=connected",
            status_code=status.HTTP_302_FOUND
        )
        
    except Exception as e:
        logger.error(f"Failed to complete Last.fm authentication: {e}", exc_info=True)
        # Redirect to settings with error
        return RedirectResponse(
            url="/settings/user?lastfm=error",
            status_code=status.HTTP_302_FOUND
        )


@router.post("/api/lastfm/disconnect")
async def disconnect_lastfm(
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
):
    """Disconnect Last.fm account."""
    user, _ = await require_current_user(request, db)
    
    await db.execute(
        """
        UPDATE "user"
        SET lastfm_session_key = NULL,
            lastfm_username = NULL,
            lastfm_enabled = FALSE,
            lastfm_connected_at = NULL
        WHERE id = $1
        """,
        user["id"]
    )
    
    logger.info(f"User {user['username']} disconnected Last.fm account")
    
    return {"ok": True}


@router.post("/api/lastfm/toggle")
async def toggle_lastfm(
    payload: ToggleRequest,
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
):
    """Enable or disable Last.fm scrobbling."""
    user, _ = await require_current_user(request, db)
    
    # Verify user has connected Last.fm
    if not user.get("lastfm_session_key"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Last.fm account not connected"
        )
    
    await db.execute(
        'UPDATE "user" SET lastfm_enabled = $1 WHERE id = $2',
        payload.enabled,
        user["id"]
    )
    
    logger.info(f"User {user['username']} {'enabled' if payload.enabled else 'disabled'} Last.fm scrobbling")
    
    return {"ok": True, "enabled": payload.enabled}
