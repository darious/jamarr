"""
Tests for individual pipeline stages.

Test naming convention: test_v3_stage_* for new pipeline stage tests.
"""

import pytest
from app.scanner.pipeline.stages import (
    CoreMetadataStage,
    ExternalLinksStage,
    ArtworkStage,
    WikipediaBioStage,
    TopTracksStage,
    SimilarArtistsStage,
    SinglesStage,
    AlbumMetadataStage,
)
from app.scanner.pipeline.models import (
    ArtistState,
    ScanOptions,
    EnrichmentContext,
    StageResult,
)
from unittest.mock import Mock, AsyncMock, patch
import httpx


@pytest.fixture
def mock_client():
    """Create a mock HTTP client."""
    return Mock(spec=httpx.AsyncClient)


@pytest.fixture
def basic_context(mock_client):
    """Create a basic enrichment context."""
    artist = ArtistState(mbid="test-mbid-123", name="Test Artist")
    options = ScanOptions()
    return EnrichmentContext(artist, options, mock_client)


class TestCoreMetadataStage:
    """Test CoreMetadataStage."""
    
    def test_v3_stage_core_metadata_name(self):
        """Test stage name."""
        stage = CoreMetadataStage()
        assert stage.name == "core_metadata"
    
    def test_v3_stage_core_metadata_no_dependencies(self):
        """Test stage has no dependencies."""
        stage = CoreMetadataStage()
        assert stage.dependencies() == []
    
    def test_v3_stage_core_metadata_skip_when_complete(self, mock_client):
        """Test skip logic when artist has all data."""
        stage = CoreMetadataStage()
        
        # Artist with all data
        artist = ArtistState(
            mbid="123",
            name="Beatles",
            external_links={
                "homepage": "http://beatles.com",
                "spotify": "http://spotify.com",
                "wikipedia": "http://wikipedia.org",
                "qobuz": "http://qobuz.com",
                "tidal": "http://tidal.com",
                "lastfm": "http://lastfm.com",
                "discogs": "http://discogs.com",
            }
        )
        
        ctx = EnrichmentContext(
            artist,
            ScanOptions(missing_only=True),
            mock_client
        )
        
        should_skip, reason = stage.should_skip(ctx)
        
        assert should_skip
        assert "core metadata and all links" in reason
    
    def test_v3_stage_core_metadata_no_skip_when_missing(self, mock_client):
        """Test no skip when data is missing."""
        stage = CoreMetadataStage()
        
        # Artist missing data
        artist = ArtistState(mbid="123", name="Beatles")
        
        ctx = EnrichmentContext(
            artist,
            ScanOptions(missing_only=True),
            mock_client
        )
        
        should_skip, reason = stage.should_skip(ctx)
        
        assert not should_skip
    
    @pytest.mark.asyncio
    async def test_v3_stage_core_metadata_execute_success(self, basic_context):
        """Test successful execution."""
        stage = CoreMetadataStage()
        
        mock_data = {
            "name": "The Beatles",
            "sort_name": "Beatles, The",
            "spotify_url": "http://spotify.com",
            "genres": [{"name": "rock", "count": 10}],
        }
        
        with patch("app.scanner.services.musicbrainz.fetch_core", AsyncMock(return_value=mock_data)):
            result = await stage.execute(basic_context)
        
        assert result.success
        assert result.data == mock_data
        assert result.metrics["api_calls"] == 1
        assert result.metrics["links_found"] == 1
        assert result.metrics["genres_found"] == 1
    
    @pytest.mark.asyncio
    async def test_v3_stage_core_metadata_execute_failure(self, basic_context):
        """Test execution when API returns no data."""
        stage = CoreMetadataStage()
        
        with patch("app.scanner.services.musicbrainz.fetch_core", AsyncMock(return_value=None)):
            result = await stage.execute(basic_context)
        
        assert not result.success
        assert result.metrics["api_calls"] == 1


class TestExternalLinksStage:
    """Test ExternalLinksStage."""
    
    def test_v3_stage_external_links_dependencies(self):
        """Test stage dependencies."""
        stage = ExternalLinksStage()
        assert "core_metadata" in stage.dependencies()
    
    def test_v3_stage_external_links_skip_no_wikidata(self, mock_client):
        """Test skip when no Wikidata URL available."""
        stage = ExternalLinksStage()
        
        ctx = EnrichmentContext(
            ArtistState(mbid="123"),
            ScanOptions(),
            mock_client
        )
        
        should_skip, reason = stage.should_skip(ctx)
        
        assert should_skip
        assert "No Wikidata URL" in reason
    
    @pytest.mark.asyncio
    async def test_v3_stage_external_links_execute_success(self, basic_context):
        """Test successful execution."""
        stage = ExternalLinksStage()
        
        # Add Wikidata URL to context
        basic_context.add_result(
            StageResult.success("core_metadata", {"wikidata_url": "http://wikidata.org/Q1"})
        )
        
        mock_links = {
            "spotify_url": "http://spotify.com",
            "qobuz_url": "http://qobuz.com",
        }
        
        with patch("app.scanner.services.wikidata.fetch_external_links", AsyncMock(return_value=mock_links)):
            result = await stage.execute(basic_context)
        
        assert result.success
        assert result.data == mock_links
        assert result.metrics["links_found"] == 2


class TestArtworkStage:
    """Test ArtworkStage."""
    
    def test_v3_stage_artwork_dependencies(self):
        """Test stage dependencies."""
        stage = ArtworkStage()
        deps = stage.dependencies()
        assert "core_metadata" in deps
        assert "external_links" in deps
    
    def test_v3_stage_artwork_skip_when_has_quality(self, mock_client):
        """Test skip when artist has high-quality artwork."""
        stage = ArtworkStage()
        
        artist = ArtistState(
            mbid="123",
            image_url="http://fanart.tv/img.jpg",
            image_source="fanart"
        )
        
        ctx = EnrichmentContext(
            artist,
            ScanOptions(missing_only=True),
            mock_client
        )
        
        should_skip, reason = stage.should_skip(ctx)
        
        assert should_skip
        assert "high-quality artwork" in reason
    
    def test_v3_stage_artwork_no_skip_spotify_upgrade(self, mock_client):
        """Test no skip when Spotify artwork can be upgraded."""
        stage = ArtworkStage()
        
        artist = ArtistState(
            mbid="123",
            image_url="http://spotify.com/img.jpg",
            image_source="spotify"
        )
        
        ctx = EnrichmentContext(
            artist,
            ScanOptions(missing_only=True),
            mock_client
        )
        
        should_skip, reason = stage.should_skip(ctx)
        
        assert not should_skip
    
    @pytest.mark.asyncio
    async def test_v3_stage_artwork_fanart_success(self, basic_context):
        """Test successful Fanart.tv fetch."""
        stage = ArtworkStage()
        
        mock_fanart = {
            "image_url": "http://fanart.tv/thumb.jpg",
            "background": "http://fanart.tv/bg.jpg",
        }
        
        with patch("app.scanner.services.artwork.fetch_fanart_artist_images", AsyncMock(return_value=mock_fanart)):
            result = await stage.execute(basic_context)
        
        assert result.success
        assert result.data["image_url"] == "http://fanart.tv/thumb.jpg"
        assert result.data["image_source"] == "fanart"
        assert result.data["background_url"] == "http://fanart.tv/bg.jpg"


class TestWikipediaBioStage:
    """Test WikipediaBioStage."""
    
    def test_v3_stage_bio_dependencies(self):
        """Test stage dependencies."""
        stage = WikipediaBioStage()
        deps = stage.dependencies()
        assert "core_metadata" in deps
        assert "external_links" in deps
    
    def test_v3_stage_bio_skip_when_has_bio(self, mock_client):
        """Test skip when artist has bio."""
        stage = WikipediaBioStage()
        
        artist = ArtistState(mbid="123", bio="British rock band")
        
        ctx = EnrichmentContext(
            artist,
            ScanOptions(missing_only=True),
            mock_client
        )
        
        should_skip, reason = stage.should_skip(ctx)
        
        assert should_skip
        assert "already has biography" in reason
    
    def test_v3_stage_bio_skip_no_wikipedia_url(self, mock_client):
        """Test skip when no Wikipedia URL."""
        stage = WikipediaBioStage()
        
        ctx = EnrichmentContext(
            ArtistState(mbid="123"),
            ScanOptions(),
            mock_client
        )
        
        should_skip, reason = stage.should_skip(ctx)
        
        assert should_skip
        assert "No Wikipedia URL" in reason
    
    @pytest.mark.asyncio
    async def test_v3_stage_bio_execute_success(self, basic_context):
        """Test successful bio fetch."""
        stage = WikipediaBioStage()
        
        # Add Wikipedia URL to context
        basic_context.add_result(
            StageResult.success("core_metadata", {"wikipedia_url": "http://en.wikipedia.org/wiki/Beatles"})
        )
        
        mock_bio = "The Beatles were an English rock band..."
        
        with patch("app.scanner.services.wikipedia.fetch_bio", AsyncMock(return_value=mock_bio)):
            result = await stage.execute(basic_context)
        
        assert result.success
        assert result.data["bio"] == mock_bio
        assert result.metrics["bio_length"] == len(mock_bio)


class TestTopTracksStage:
    """Test TopTracksStage."""
    
    def test_v3_stage_top_tracks_no_dependencies(self):
        """Test stage has no dependencies."""
        stage = TopTracksStage()
        assert stage.dependencies() == []
    
    def test_v3_stage_top_tracks_skip_when_has_tracks(self, mock_client):
        """Test skip when artist has top tracks."""
        stage = TopTracksStage()
        
        artist = ArtistState(mbid="123", has_top_tracks=True)
        
        ctx = EnrichmentContext(
            artist,
            ScanOptions(missing_only=True),
            mock_client
        )
        
        should_skip, reason = stage.should_skip(ctx)
        
        assert should_skip
    
    @pytest.mark.asyncio
    async def test_v3_stage_top_tracks_execute_success(self, basic_context):
        """Test successful top tracks fetch."""
        stage = TopTracksStage()
        
        mock_tracks = [
            {"name": "Hey Jude", "rank": 1, "popularity": 100, "mbid": "track-1"},
            {"name": "Let It Be", "rank": 2, "popularity": 95, "mbid": "track-2"},
        ]
        
        with patch("app.scanner.services.lastfm.fetch_top_tracks", AsyncMock(return_value=mock_tracks)):
            result = await stage.execute(basic_context)
        
        assert result.success
        assert result.data["top_tracks"] == mock_tracks
        assert result.metrics["tracks_found"] == 2


class TestSimilarArtistsStage:
    """Test SimilarArtistsStage."""
    
    def test_v3_stage_similar_skip_when_has_similar(self, mock_client):
        """Test skip when artist has similar artists."""
        stage = SimilarArtistsStage()
        
        artist = ArtistState(mbid="123", has_similar=True)
        
        ctx = EnrichmentContext(
            artist,
            ScanOptions(missing_only=True),
            mock_client
        )
        
        should_skip, reason = stage.should_skip(ctx)
        
        assert should_skip
    
    @pytest.mark.asyncio
    async def test_v3_stage_similar_execute_success(self, basic_context):
        """Test successful similar artists fetch."""
        stage = SimilarArtistsStage()
        
        mock_similar = [
            {"name": "The Rolling Stones", "mbid": "artist-1"},
            {"name": "The Who", "mbid": "artist-2"},
        ]
        
        with patch("app.scanner.services.lastfm.fetch_similar_artists", AsyncMock(return_value=mock_similar)):
            result = await stage.execute(basic_context)
        
        assert result.success
        assert result.data["similar_artists"] == mock_similar
        assert result.metrics["artists_found"] == 2


class TestSinglesStage:
    """Test SinglesStage."""
    
    def test_v3_stage_singles_skip_when_has_singles(self, mock_client):
        """Test skip when artist has singles."""
        stage = SinglesStage()
        
        artist = ArtistState(mbid="123", has_singles=True)
        
        ctx = EnrichmentContext(
            artist,
            ScanOptions(missing_only=True),
            mock_client
        )
        
        should_skip, reason = stage.should_skip(ctx)
        
        assert should_skip
    
    @pytest.mark.asyncio
    async def test_v3_stage_singles_execute_success(self, basic_context):
        """Test successful singles fetch."""
        stage = SinglesStage()
        
        mock_singles = [
            {"title": "Hey Jude", "mbid": "single-1", "date": "1968"},
            {"title": "Let It Be", "mbid": "single-2", "date": "1970"},
        ]
        
        with patch("app.scanner.services.musicbrainz.fetch_release_groups", AsyncMock(return_value=mock_singles)):
            result = await stage.execute(basic_context)
        
        assert result.success
        assert result.data["singles"] == mock_singles
        assert result.metrics["singles_found"] == 2


class TestAlbumMetadataStage:
    """Test AlbumMetadataStage."""
    
    def test_v3_stage_albums_skip_no_local_albums(self, mock_client):
        """Test skip when no local albums."""
        stage = AlbumMetadataStage()
        
        ctx = EnrichmentContext(
            ArtistState(mbid="123"),
            ScanOptions(),
            mock_client
        )
        
        should_skip, reason = stage.should_skip(ctx)
        
        assert should_skip
        assert "No local albums" in reason
    
    @pytest.mark.asyncio
    async def test_v3_stage_albums_execute_success(self, basic_context):
        """Test successful album metadata fetch."""
        stage = AlbumMetadataStage()
        
        # Add local release groups to context
        basic_context.local_release_groups = {"album-1", "album-2"}
        
        mock_album_data = {
            "description": "Classic album",
            "peak_chart_position": 1,
        }
        
        with patch("app.scanner.services.album.fetch_album_metadata", AsyncMock(return_value=mock_album_data)):
            result = await stage.execute(basic_context)
        
        assert result.success
        assert "albums_metadata" in result.data
        assert result.metrics["albums_processed"] == 2
