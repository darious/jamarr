import pytest
from unittest.mock import patch
from app.api.charts import get_chart
from app.charts import ChartEntry, enrich_entries, ChartScraper

@pytest.fixture
def mock_chart_entry():
    return ChartEntry(
        position=1,
        title="Test Album",
        artist="Test Artist",
        last_week="2",
        peak="1",
        weeks="5",
        status="up",
        release_mbid="mbid1",
        release_group_mbid="rg_mbid1"
    )

@pytest.mark.asyncio
async def test_enrich_entries(mock_chart_entry):
    entries = [mock_chart_entry]
    
    mock_data = {
        "releases": [
            {
                "title": "Test Album",
                "artist-credit": [{"artist": {"name": "Test Artist"}}],
                "id": "mbid_found",
                "release-group": {"id": "rg_mbid_found"}
            }
        ]
    }

    class MockResponse:
        status_code = 200
        def json(self):
            return mock_data

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass
        async def get(self, url, params=None, **kwargs):
            return MockResponse()

    with patch("app.charts.httpx.AsyncClient", side_effect=MockAsyncClient):
        await enrich_entries(entries)
        
        assert entries[0].release_mbid == "mbid_found"
        assert entries[0].release_group_mbid == "rg_mbid_found"
        assert entries[0].confidence > 60

@pytest.mark.asyncio
async def test_fetch_chart_parse_html():
    html = """
    <html><body>
    <div class="chart-positions">
        <div class="chart-positions__item">
            <span class="chart-positions__position">1</span>
            <div class="chart-positions__title">Album Title</div>
            <div class="chart-positions__artist">Artist Name</div>
            <div class="chart-positions__stats">
                <span>LW 2</span>
                <span>Peak 1</span>
                <span>Weeks 5</span>
            </div>
            <div class="status">Steady</div>
        </div>
    </div>
    </body></html>
    """
    
    scraper = ChartScraper()
    # Mock _extract_nuxt_payload to return None so it falls back to HTML parsing
    with patch.object(scraper, '_extract_nuxt_payload', return_value=None):
        entries = scraper._parse_chart(html)
        
    assert len(entries) == 1
    assert entries[0].position == 1
    assert entries[0].title == "Album Title"
    assert entries[0].artist == "Artist Name"
    assert entries[0].last_week == "2"
    assert entries[0].peak == "1"
    assert entries[0].weeks == "5"

def test_fetch_chart_parse_payload():
    # If explicit new/reentry flags are false, and we have numbers:
    # 1 < 2 => up.
    # HOWEVER, the implementation checks `is_new` and `is_reentry` BEFORE calculating trends.
    # In my previous test run, I asserted "up" but got "new entry".
    # This implies `is_new` evaluated to True?
    # In payload: "new": False.
    # `is_new = bool(self._resolve_payload(payload, obj.get("new")))`
    # If payload["new"] is False, bool(False) is False.
    # Maybe `_resolve_payload` is returning something else?
    
    payload = [
        {
            "position": "1",
            "title": "Payload Title",
            "artist": "Payload Artist",
            "lastWeek": "2",
            "peak": "1",
            "weeks": "10",
            "new": False,
            "reentry": False
        }
    ]
    
    scraper = ChartScraper()
    entries = scraper._parse_chart_from_payload(payload)
    
    assert len(entries) == 1
    assert entries[0].title == "Payload Title"
    # If logic is correct, 1 < 2 means UP.
    assert entries[0].status == "up"

@pytest.mark.asyncio
async def test_api_get_chart_empty(db):
    chart = await get_chart()
    assert isinstance(chart, list)
    assert len(chart) == 0
