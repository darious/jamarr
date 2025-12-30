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
                    # Detailed stats: category -> {searched: int, found: int, missing: int}
                    cls._instance._detailed_stats = defaultdict(lambda: {"searched": 0, "found": 0, "missing": 0})
        return cls._instance

    def increment(self, service: str):
        with self._stats_lock:
            self._stats[service] += 1

    def increment_processed(self, entity_type: str):
        """
        Legacy simple increment. Use track_processed for distinct counting.
        """
        # Fallback for simple counting if needed, but we prefer distinct
        pass

    def track_processed(self, entity_type: str, unique_id: str):
        """
        Track a unique item as processed.
        entity_type: 'tracks', 'albums', 'artists'
        unique_id: The limits of the uniqueness (e.g. MBID or path)
        """
        if not unique_id:
            return
        with self._stats_lock:
            if entity_type not in self._processed_sets:
                self._processed_sets[entity_type] = set()
            self._processed_sets[entity_type].add(unique_id)

    def track_detailed(self, category: str, status: str):
        """
        Track detailed stats for a category.
        status: 'found', 'missing'
        """
        with self._stats_lock:
            self._detailed_stats[category]["searched"] += 1
            if status == "found":
                self._detailed_stats[category]["found"] += 1
            elif status == "missing":
                self._detailed_stats[category]["missing"] += 1

    def get_stats(self):
        with self._stats_lock:
            return dict(self._stats)

    def get_processed_stats(self):
        with self._stats_lock:
            return {k: len(v) for k, v in self._processed_sets.items()}
            
    def get_detailed_stats(self):
        with self._stats_lock:
            # excessive defaultdict causes issues with serialization if not converted
            return {k: dict(v) for k, v in self._detailed_stats.items()}

    def reset(self):
        with self._stats_lock:
            self._stats.clear()
            for s in self._processed_sets.values():
                s.clear()
            self._detailed_stats.clear()


def get_api_tracker():
    return ApiTracker()
