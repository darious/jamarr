"""
Tests for Last.fm API integration module.
"""

import pytest
from unittest.mock import Mock, patch
from app import lastfm


class TestLastfmModule:
    """Tests for Last.fm API module functions."""

    @patch('app.lastfm.pylast.LastFMNetwork')
    @patch('app.lastfm.pylast.SessionKeyGenerator')
    def test_get_auth_url(self, mock_skg_class, mock_network_class):
        """Test generating Last.fm authorization URL."""
        # Setup mocks
        mock_network = Mock()
        mock_network_class.return_value = mock_network
        
        mock_skg = Mock()
        mock_skg.get_web_auth_url.return_value = "https://www.last.fm/api/auth?token=abc123"
        mock_skg_class.return_value = mock_skg
        
        # Call function
        auth_url = lastfm.get_auth_url()
        
        # Assertions
        assert auth_url == "https://www.last.fm/api/auth?token=abc123"
        mock_skg.get_web_auth_url.assert_called_once()

    @pytest.mark.asyncio
    @patch('app.lastfm.pylast.LastFMNetwork')
    @patch('app.lastfm.pylast.SessionKeyGenerator')
    async def test_get_session_key(self, mock_skg_class, mock_network_class):
        """Test exchanging token for session key."""
        # Setup mocks
        mock_network = Mock()
        mock_network_class.return_value = mock_network
        
        mock_user = Mock()
        mock_user.get_name.return_value = "testuser"
        mock_network.get_authenticated_user.return_value = mock_user
        
        mock_skg = Mock()
        mock_skg.get_session_key.return_value = "session_key_123"
        mock_skg_class.return_value = mock_skg
        
        # Call function
        session_key, username = await lastfm.get_session_key("test_token")
        
        # Assertions
        assert session_key == "session_key_123"
        assert username == "testuser"
        mock_skg.get_session_key.assert_called_once_with("test_token")

    @pytest.mark.asyncio
    @patch('app.lastfm.pylast.LastFMNetwork')
    async def test_update_now_playing(self, mock_network_class):
        """Test updating Now Playing status."""
        # Setup mocks
        mock_network = Mock()
        mock_network.update_now_playing = Mock()
        mock_network_class.return_value = mock_network
        
        track_info = {
            'artist': 'Test Artist',
            'track': 'Test Track',
            'album': 'Test Album',
            'duration': 180,
            'mbid': 'mbid-123'
        }
        
        # Call function
        await lastfm.update_now_playing("session_key", track_info)
        
        # Assertions
        mock_network.update_now_playing.assert_called_once_with(
            artist='Test Artist',
            title='Test Track',
            album='Test Album',
            duration=180,
            track_number=None,
            mbid='mbid-123'
        )

    @pytest.mark.asyncio
    @patch('app.lastfm.pylast.LastFMNetwork')
    async def test_scrobble_track(self, mock_network_class):
        """Test scrobbling a track."""
        # Setup mocks
        mock_network = Mock()
        mock_network.scrobble = Mock()
        mock_network_class.return_value = mock_network
        
        track_info = {
            'artist': 'Test Artist',
            'track': 'Test Track',
            'album': 'Test Album',
            'duration': 180,
            'mbid': 'mbid-123'
        }
        timestamp = 1234567890
        
        # Call function
        await lastfm.scrobble_track("session_key", track_info, timestamp)
        
        # Assertions
        mock_network.scrobble.assert_called_once_with(
            artist='Test Artist',
            title='Test Track',
            timestamp=timestamp,
            album='Test Album',
            duration=180,
            track_number=None,
            mbid='mbid-123'
        )

    @pytest.mark.asyncio
    @patch('app.lastfm.pylast.LastFMNetwork')
    async def test_scrobble_without_optional_fields(self, mock_network_class):
        """Test scrobbling with minimal track info."""
        mock_network = Mock()
        mock_network.scrobble = Mock()
        mock_network_class.return_value = mock_network
        
        track_info = {
            'artist': 'Test Artist',
            'track': 'Test Track'
        }
        timestamp = 1234567890
        
        # Call function
        await lastfm.scrobble_track("session_key", track_info, timestamp)
        
        # Assertions
        mock_network.scrobble.assert_called_once_with(
            artist='Test Artist',
            title='Test Track',
            timestamp=timestamp,
            album=None,
            duration=None,
            track_number=None,
            mbid=None
        )
