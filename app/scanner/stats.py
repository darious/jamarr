from collections import defaultdict
import threading


class ApiTracker:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(ApiTracker, cls).__new__(cls)
                    cls._instance._stats = defaultdict(int)
                    cls._instance._stats_lock = threading.Lock()
                    # Use sets for distinct counting
                    cls._instance._processed_sets = {
                        "tracks": set(),
                        "albums": set(),
                        "artists": set(),
                        "artists_metadata": set(),
                    }
                    # New stage metrics: stage -> {missing, searched, hits, misses}
                    cls._instance._stage_metrics = defaultdict(lambda: {
                        "missing": 0,
                        "searched": 0,
                        "hits": 0,
                        "misses": 0
                    })
        return cls._instance

    def increment(self, service: str):
        """Increment API call counter for a service (musicbrainz, lastfm, wikidata, fanart, spotify, qobuz)."""
        with self._stats_lock:
            self._stats[service] += 1

    def track_processed(self, entity_type: str, unique_id: str):
        """
        Track a unique item as processed.
        entity_type: 'tracks', 'albums', 'artists', 'artists_metadata'
        unique_id: The unique identifier (e.g. MBID or path)
        """
        if not unique_id:
            return
        with self._stats_lock:
            if entity_type not in self._processed_sets:
                self._processed_sets[entity_type] = set()
            self._processed_sets[entity_type].add(unique_id)

    def track_stage_metrics(self, stage: str, missing: int, searched: int, hits: int):
        """
        Track comprehensive stage metrics.
        
        Args:
            stage: Stage name (e.g., "Bio", "Fanart", "MusicBrainz Core")
            missing: Artists missing this data before scan
            searched: Artists we searched for
            hits: Artists where we found data
        
        Misses are calculated as: missing - hits
        """
        with self._stats_lock:
            self._stage_metrics[stage]["missing"] = missing
            self._stage_metrics[stage]["searched"] = searched
            self._stage_metrics[stage]["hits"] = hits
            self._stage_metrics[stage]["misses"] = missing - hits

    def get_stats(self):
        """Get API call counters."""
        with self._stats_lock:
            return dict(self._stats)

    def get_processed_stats(self):
        """Get processed entity counts."""
        with self._stats_lock:
            return {k: len(v) for k, v in self._processed_sets.items()}
            
    def get_stage_metrics(self):
        """Get stage metrics (missing, searched, hits, misses)."""
        with self._stats_lock:
            return {k: dict(v) for k, v in self._stage_metrics.items()}

    def reset(self):
        """Reset all statistics."""
        with self._stats_lock:
            self._stats.clear()
            for s in self._processed_sets.values():
                s.clear()
            self._stage_metrics.clear()


def get_api_tracker():
    return ApiTracker()
