"""
Last.fm API integration using pylast library.

Provides authentication and scrobbling functionality for Last.fm.
"""

import logging
from typing import Dict, Any, Optional
import pylast
from app.config import get_lastfm_api_key, get_lastfm_shared_secret

logger = logging.getLogger(__name__)


def _get_network(session_key: Optional[str] = None) -> pylast.LastFMNetwork:
    """
    Create a Last.fm network instance.
    
    Args:
        session_key: Optional session key for authenticated requests
        
    Returns:
        Configured LastFMNetwork instance
    """
    return pylast.LastFMNetwork(
        api_key=get_lastfm_api_key(),
        api_secret=get_lastfm_shared_secret(),
        session_key=session_key
    )


def get_auth_url() -> str:
    """
    Generate Last.fm authorization URL for user authentication.
    
    Returns:
        URL to redirect user to for Last.fm authorization
    """
    try:
        network = _get_network()
        skg = pylast.SessionKeyGenerator(network)
        auth_url = skg.get_web_auth_url()
        logger.info("Generated Last.fm auth URL")
        return auth_url
    except Exception as e:
        logger.error(f"Failed to generate Last.fm auth URL: {e}")
        raise


async def get_session_key(token: str) -> tuple[str, str]:
    """
    Exchange an approved token for a session key.
    
    Args:
        token: The token from Last.fm callback
        
    Returns:
        Tuple of (session_key, username)
        
    Raises:
        Exception if token exchange fails
    """
    try:
        network = _get_network()
        skg = pylast.SessionKeyGenerator(network)
        session_key = skg.get_web_auth_session_key(url="", token=token)
        
        # Get username for the session
        auth_network = _get_network(session_key)
        username = auth_network.get_authenticated_user().get_name()
        
        logger.info(f"Successfully obtained Last.fm session for user: {username}")
        return session_key, username
    except Exception as e:
        logger.error(f"Failed to get Last.fm session key: {e}")
        raise


async def update_now_playing(
    session_key: str,
    track_info: Dict[str, Any]
) -> None:
    """
    Update the "Now Playing" status on Last.fm.
    
    Args:
        session_key: User's Last.fm session key
        track_info: Dict with keys: track, artist, album (optional), duration (optional), mbid (optional)
    """
    try:
        network = _get_network(session_key)
        
        network.update_now_playing(
            artist=track_info['artist'],
            title=track_info['track'],
            album=track_info.get('album'),
            duration=track_info.get('duration'),
            track_number=None,
            mbid=track_info.get('mbid')
        )
        
        logger.info(f"Updated Now Playing on Last.fm: {track_info['artist']} - {track_info['track']}")
    except pylast.WSError as e:
        logger.error(f"Last.fm API error updating Now Playing: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to update Now Playing on Last.fm: {e}")
        raise


async def scrobble_track(
    session_key: str,
    track_info: Dict[str, Any],
    timestamp: int
) -> None:
    """
    Scrobble a track to Last.fm.
    
    Args:
        session_key: User's Last.fm session key
        track_info: Dict with keys: track, artist, album (optional), duration (optional), mbid (optional)
        timestamp: Unix timestamp when the track started playing
    """
    try:
        network = _get_network(session_key)
        
        network.scrobble(
            artist=track_info['artist'],
            title=track_info['track'],
            timestamp=timestamp,
            album=track_info.get('album'),
            duration=track_info.get('duration'),
            track_number=None,
            mbid=track_info.get('mbid')
        )
        
        logger.info(f"Scrobbled to Last.fm: {track_info['artist']} - {track_info['track']}")
    except pylast.WSError as e:
        logger.error(f"Last.fm API error scrobbling track: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to scrobble to Last.fm: {e}")
        raise
