"""
DNS Resolver with caching for scanner HTTP operations.

This module provides a custom DNS resolver using aiodns that caches
DNS results in memory to eliminate repeated DNS lookups and prevent
DNS resolver exhaustion during concurrent operations.
"""

import asyncio
import logging
from typing import Dict, List
import aiodns
import socket

logger = logging.getLogger("scanner.dns_resolver")

# Known API hostnames that we always use
KNOWN_HOSTS = [
    "musicbrainz.org",
    "ws.audioscrobbler.com",  # Last.fm
    "webservice.fanart.tv",
    "api.spotify.com",
    "accounts.spotify.com",
    "en.wikipedia.org",
    "www.wikidata.org",
    "www.qobuz.com",
    "play.qobuz.com",
]

class CachedDNSResolver:
    """
    Async DNS resolver with in-memory caching.
    
    Caches DNS results for the lifetime of the process to eliminate
    repeated lookups and reduce load on the DNS resolver.
    """
    
    def __init__(self):
        self.resolver = aiodns.DNSResolver()
        self._cache: Dict[str, List[str]] = {}
        self._stats = {"hits": 0, "misses": 0, "errors": 0}
        self._lock = asyncio.Lock()
    
    async def resolve(self, hostname: str) -> List[str]:
        """
        Resolve hostname to IP addresses with caching.
        
        Args:
            hostname: The hostname to resolve
            
        Returns:
            List of IP addresses (strings)
        """
        # Check cache first
        async with self._lock:
            if hostname in self._cache:
                self._stats["hits"] += 1
                logger.debug(f"DNS cache HIT for {hostname}: {self._cache[hostname]}")
                return self._cache[hostname]
            
            self._stats["misses"] += 1
        
        # Cache miss - resolve via aiodns
        try:
            logger.debug(f"DNS cache MISS for {hostname}, resolving...")
            result = await self.resolver.query(hostname, 'A')
            
            # Extract IP addresses from result
            ips = [r.host for r in result] if isinstance(result, list) else [result.host]
            
            # Cache the result
            async with self._lock:
                self._cache[hostname] = ips
            
            logger.debug(f"DNS resolved {hostname} -> {ips}")
            return ips
            
        except Exception as e:
            async with self._lock:
                self._stats["errors"] += 1
            logger.warning(f"DNS resolution failed for {hostname}: {e}")
            
            # Fallback to standard library (blocking, but better than failing)
            try:
                ip = socket.gethostbyname(hostname)
                async with self._lock:
                    self._cache[hostname] = [ip]
                return [ip]
            except Exception as fallback_error:
                logger.error(f"DNS fallback also failed for {hostname}: {fallback_error}")
                raise
    
    def get_stats(self) -> Dict[str, int]:
        """Get DNS cache statistics."""
        return self._stats.copy()
    
    def clear_cache(self):
        """Clear the DNS cache (mainly for testing)."""
        self._cache.clear()
        logger.info("DNS cache cleared")


# Global resolver instance
_resolver: CachedDNSResolver | None = None


def get_resolver() -> CachedDNSResolver:
    """Get the global DNS resolver instance."""
    global _resolver
    if _resolver is None:
        _resolver = CachedDNSResolver()
    return _resolver


async def warm_dns_cache(hosts: List[str] = None):
    """
    Pre-resolve known hostnames to warm the DNS cache.
    
    This should be called at scanner startup to eliminate DNS lookups
    during the actual scanning process.
    
    Args:
        hosts: List of hostnames to pre-resolve (defaults to KNOWN_HOSTS)
    """
    if hosts is None:
        hosts = KNOWN_HOSTS
    
    resolver = get_resolver()
    logger.info(f"Warming DNS cache for {len(hosts)} known hosts...")
    
    tasks = [resolver.resolve(host) for host in hosts]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    success_count = sum(1 for r in results if not isinstance(r, Exception))
    logger.info(f"DNS cache warmed: {success_count}/{len(hosts)} hosts resolved successfully")
    
    # Log any failures
    for host, result in zip(hosts, results):
        if isinstance(result, Exception):
            logger.warning(f"Failed to pre-resolve {host}: {result}")
