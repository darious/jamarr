from app.scanner.stats import get_api_tracker, ApiTracker

def test_api_tracker_singleton():
    t1 = get_api_tracker()
    t2 = ApiTracker()
    assert t1 is t2

def test_increment_api_stats():
    tracker = get_api_tracker()
    tracker.reset()
    
    tracker.increment("spotify")
    tracker.increment("spotify")
    tracker.increment("musicbrainz")
    
    stats = tracker.get_stats()
    assert stats["spotify"] == 2
    assert stats["musicbrainz"] == 1
    assert stats.get("wikidata", 0) == 0

def test_increment_processed_stats():
    tracker = get_api_tracker()
    tracker.reset()
    
    # Use track_processed with unique IDs
    tracker.track_processed("tracks", "track1")
    tracker.track_processed("tracks", "track2")
    tracker.track_processed("tracks", "track1") # Duplicate
    
    tracker.track_processed("albums", "album1")

    tracker.track_processed("metadata_artists", "mbid1")
    
    stats = tracker.get_processed_stats()
    assert stats["tracks"] == 2
    assert stats["albums"] == 1
    assert stats["metadata_artists"] == 1
    assert stats["artists"] == 0

def test_reset():
    tracker = get_api_tracker()
    tracker.increment("spotify")
    tracker.track_processed("tracks", "t1")
    
    tracker.reset()
    
    stats = tracker.get_stats()
    processed = tracker.get_processed_stats()
    
    assert len(stats) == 0
    assert processed["tracks"] == 0
