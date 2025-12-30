
import pytest
import asyncio
from app.scanner.services.coordinator import MetadataCoordinator

@pytest.mark.asyncio
async def test_writer_with_real_db(db):
    """
    Test coordinator with REAL database connection to find the actual hang.
    Uses the existing db fixture from conftest.py.
    """
    coord = MetadataCoordinator()
    
    # Insert 2 test artists into DB (simulating We Are KING and TINI)
    await db.execute("""
        INSERT INTO artist (mbid, name) 
        VALUES ('test-king-id', 'We Are KING'), ('test-tini-id', 'TINI')
        ON CONFLICT (mbid) DO NOTHING
    """)
    
    # Fetch them back
    artists = await db.fetch("""
        SELECT mbid, name FROM artist WHERE mbid IN ('test-king-id', 'test-tini-id')
    """)
    artists = [dict(a) for a in artists]
    
    print(f"Testing with {len(artists)} real artists from DB...")
    
    options = {
        "fetch_base_metadata": False,
        "fetch_artwork": False,
        "fetch_links": False,
        "fetch_top_tracks": False,
        "fetch_similar_artists": False,
        "fetch_singles": False,
        "fetch_bio": False
    }
    
    try:
        # Should complete quickly since all fetch options are False
        await asyncio.wait_for(coord.update_metadata(artists, options), timeout=10.0)
        print("Update completed successfully")
    except asyncio.TimeoutError:
        pytest.fail("Coordinator hung with real DB! Writer task deadlock detected.")
    except Exception as e:
        pytest.fail(f"Coordinator crashed: {e}")
