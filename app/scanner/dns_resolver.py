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
    "coverartarchive.org",          # MB cover art CDN
    "ws.audioscrobbler.com",        # Last.fm API
    "webservice.fanart.tv",         # Fanart API
    "assets.fanart.tv",             # Fanart asset host
    "api.spotify.com",              # Spotify API
    "accounts.spotify.com",         # Spotify auth
    "i.scdn.co",                    # Spotify image CDN
    "en.wikipedia.org",             # Wikipedia HTML
    "upload.wikimedia.org",         # Wikipedia images
    "www.wikidata.org",             # Wikidata API
    "www.qobuz.com",                # Qobuz auth/search
    "play.qobuz.com",               # Qobuz links
]

class CachedDNSResolver:
    """
    Async DNS resolver with in-memory caching.
    
    Caches DNS results for the lifetime of the process to eliminate
    repeated lookups and reduce load on the DNS resolver.
    """
    
    def __init__(self):
        # User requested to use system DNS settings
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
            result = await self.resolver.query_dns(hostname, 'A')

            # Extract IP addresses from DNSResult.answer records
            ips = []
            for record in result.answer:
                addr = getattr(record.data, 'addr', None)
                if addr:
                    ips.append(addr)
            
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
                # If fallback works, maybe log it strongly?
                logger.info(f"System DNS fallback succeeded for {hostname}: {ip}")
                return [ip]
            except Exception as fallback_error:
                logger.error(f"DNS fallback also failed for {hostname}: {fallback_error}")
                raise

    # ... (rest of class)
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



def install_dns_patch():
    """
    Monkey-patch socket.getaddrinfo to use our cached resolver.
    This ensures that all libraries (httpx, httpcore, requests, etc.)
    that use socket.getaddrinfo will benefit from the cache.
    """
    # idempotency check
    if hasattr(socket, '_jamarr_patched'):
        return

    logger.info("Installing DNS cache monkey-patch...")
    
    # Store original getaddrinfo if not already stored
    if not hasattr(socket, '_original_getaddrinfo'):
        socket._original_getaddrinfo = socket.getaddrinfo
        
    def cached_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        """Synchronous wrapper that uses our async DNS cache."""
        try:
            # Get resolver dynamically to ensure we always use the latest cache
            resolver = get_resolver()
            
            # Convert bytes to string if needed (httpcore passes bytes)
            if isinstance(host, bytes):
                host_str = host.decode('utf-8')
            else:
                host_str = host
            
            # Try to get from cache (synchronous check)
            if host_str in resolver._cache:
                ips = resolver._cache[host_str]
                logger.debug(f"DNS cache HIT for {host_str}: {ips}")
                
                # Return in getaddrinfo format
                results = []
                for ip in ips:
                    if ':' in ip:
                        fam = socket.AF_INET6
                        sockaddr = (ip, port, 0, 0)
                    else:
                        fam = socket.AF_INET
                        sockaddr = (ip, port)
                    
                    results.append((
                        fam,
                        socket.SOCK_STREAM,
                        socket.IPPROTO_TCP,
                        '',
                        sockaddr
                    ))
                return results
            else:
                logger.debug(f"DNS cache MISS for {host_str} (cache has {len(resolver._cache)} entries)")
        except Exception as e:
            logger.debug(f"DNS cache lookup failed for {host}: {e}")
        
        # Cache miss or error - use original
        # logger.debug(f"Using standard DNS resolution for {host}")
        return socket._original_getaddrinfo(host, port, family, type, proto, flags)

    socket.getaddrinfo = cached_getaddrinfo
    socket._jamarr_patched = True
    logger.info("DNS cache monkey-patch installed successfully")


async def warm_dns_cache(hosts: List[str] = None):
    """
    Pre-resolve known hostnames to warm the DNS cache.
    Includes RETRY logic to ensure critical hosts are resolved.
    If all retries fail or cache verification fails, RAISES an exception
    to stop the process (prevents hammering upstream DNS during scans).
    """
    # Ensure the patch is installed
    install_dns_patch()
    
    if hosts is None:
        hosts = KNOWN_HOSTS
    
    resolver = get_resolver()
    logger.info(f"Warming DNS cache for {len(hosts)} known hosts...")
    
    # Retry configuration
    max_retries = 3
    
    for attempt in range(max_retries):
        tasks = [resolver.resolve(host) for host in hosts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        failures = []
        success_count = 0
        
        for host, result in zip(hosts, results):
            if isinstance(result, Exception):
                failures.append(host)
            else:
                success_count += 1
                
        if not failures:
            logger.info(f"DNS cache warmed: {success_count}/{len(hosts)} hosts resolved successfully.")
            break
        
        if attempt < max_retries - 1:
            wait_time = (attempt + 1) * 2
            logger.warning(f"DNS Warmup: Failed to resolve {len(failures)} hosts ({failures}). Retrying in {wait_time}s...")
            await asyncio.sleep(wait_time)
            # Only retry failures
            hosts = failures
        else:
            msg = f"DNS Warmup: CRITICAL - Failed to resolve {len(failures)} hosts after {max_retries} attempts: {failures}"
            logger.error(msg)
            # HARD FAILURE as requested
            raise RuntimeError(msg)

    # Verification pass: resolve again to ensure we produce cache hits (not just misses)
    hits_before = resolver.get_stats().get("hits", 0)
    cache_size_before = len(resolver._cache)

    verify_results = await asyncio.gather(
        *[resolver.resolve(host) for host in hosts],
        return_exceptions=True,
    )

    verify_failures = [host for host, res in zip(hosts, verify_results) if isinstance(res, Exception)]
    hits_after = resolver.get_stats().get("hits", 0)
    added_hits = hits_after - hits_before

    if verify_failures or added_hits < len(hosts):
        msg = (
            f"DNS Warmup verification failed: hits={added_hits}/{len(hosts)}, "
            f"failures={verify_failures}"
        )
        logger.error(msg)
        raise RuntimeError(msg)

    logger.info(
        f"DNS cache verification passed: cache_size={len(resolver._cache)}, "
        f"hits_added={added_hits}, warm_hosts={len(hosts)}, "
        f"cache_growth={len(resolver._cache) - cache_size_before}"
    )
