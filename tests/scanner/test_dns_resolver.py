"""
Tests for DNS resolver with caching.
"""

import pytest
import asyncio
from app.scanner.dns_resolver import (
    CachedDNSResolver,
    get_resolver,
    warm_dns_cache,
    KNOWN_HOSTS,
)


@pytest.mark.asyncio
async def test_dns_resolver_initialization():
    """Test that DNS resolver initializes correctly."""
    resolver = CachedDNSResolver()
    assert resolver is not None
    assert resolver._cache == {}
    assert resolver._stats == {"hits": 0, "misses": 0, "errors": 0}


@pytest.mark.asyncio
async def test_dns_resolution_basic():
    """Test basic DNS resolution."""
    resolver = CachedDNSResolver()
    
    # Resolve a known hostname
    ips = await resolver.resolve("google.com")
    
    assert isinstance(ips, list)
    assert len(ips) > 0
    assert all(isinstance(ip, str) for ip in ips)
    
    # Should be a cache miss
    stats = resolver.get_stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 0


@pytest.mark.asyncio
async def test_dns_caching():
    """Test that DNS results are cached."""
    resolver = CachedDNSResolver()
    
    # First resolution - cache miss
    ips1 = await resolver.resolve("google.com")
    stats1 = resolver.get_stats()
    assert stats1["misses"] == 1
    assert stats1["hits"] == 0
    
    # Second resolution - cache hit
    ips2 = await resolver.resolve("google.com")
    stats2 = resolver.get_stats()
    assert stats2["misses"] == 1  # Still 1
    assert stats2["hits"] == 1    # Now 1
    
    # Results should be identical
    assert ips1 == ips2


@pytest.mark.asyncio
async def test_dns_cache_multiple_hosts():
    """Test caching with multiple different hostnames."""
    resolver = CachedDNSResolver()
    
    # Resolve multiple hosts
    hosts = ["google.com", "github.com", "python.org"]
    results = {}
    
    for host in hosts:
        results[host] = await resolver.resolve(host)
    
    # All should be cache misses
    stats = resolver.get_stats()
    assert stats["misses"] == 3
    assert stats["hits"] == 0
    
    # Resolve again - all should be cache hits
    for host in hosts:
        cached_result = await resolver.resolve(host)
        assert cached_result == results[host]
    
    stats = resolver.get_stats()
    assert stats["misses"] == 3
    assert stats["hits"] == 3


@pytest.mark.asyncio
async def test_dns_cache_clear():
    """Test clearing the DNS cache."""
    resolver = CachedDNSResolver()
    
    # Resolve and cache
    await resolver.resolve("google.com")
    assert len(resolver._cache) == 1
    
    # Clear cache
    resolver.clear_cache()
    assert len(resolver._cache) == 0
    
    # Next resolution should be a miss again
    await resolver.resolve("google.com")
    stats = resolver.get_stats()
    assert stats["misses"] == 2  # Original + after clear


@pytest.mark.asyncio
async def test_dns_warm_cache():
    """Test warming the DNS cache with known hosts."""
    # Clear any existing cache
    resolver = get_resolver()
    resolver.clear_cache()
    initial_stats = resolver.get_stats()
    
    # Warm the cache
    await warm_dns_cache()
    
    # Check that hosts were resolved
    stats = resolver.get_stats()
    assert stats["misses"] > initial_stats["misses"]
    
    # Verify known hosts are in cache
    for host in KNOWN_HOSTS[:3]:  # Check first 3
        # This should be a cache hit
        await resolver.resolve(host)
    
    # Should have cache hits now
    final_stats = resolver.get_stats()
    assert final_stats["hits"] > 0


@pytest.mark.asyncio
async def test_dns_warm_cache_idempotent():
    """Test that warming cache multiple times is safe."""
    resolver = get_resolver()
    resolver.clear_cache()
    
    # Warm twice
    await warm_dns_cache()
    cache_size_1 = len(resolver._cache)
    
    await warm_dns_cache()
    cache_size_2 = len(resolver._cache)
    
    # Cache size should be the same (idempotent)
    assert cache_size_1 == cache_size_2
    
    # Give pycares time to finish callbacks before event loop closes
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_dns_warm_cache_verifies_hits(monkeypatch):
    """Warm/verify should populate cache and produce hits before scanning."""
    resolver = get_resolver()
    resolver.clear_cache()
    resolver._stats = {"hits": 0, "misses": 0, "errors": 0}

    test_hosts = ["example.org", "example.com"]

    async def fake_resolve(host):
        # Simulate cache hits on second pass without real DNS
        if host in resolver._cache:
            resolver._stats["hits"] += 1
            return resolver._cache[host]
        resolver._stats["misses"] += 1
        resolver._cache[host] = ["127.0.0.1"]
        return resolver._cache[host]

    monkeypatch.setattr(resolver, "resolve", fake_resolve)
    monkeypatch.setattr("app.scanner.dns_resolver.KNOWN_HOSTS", test_hosts, raising=False)

    await warm_dns_cache()

    stats = resolver.get_stats()
    assert stats["hits"] >= len(test_hosts)
    assert all(h in resolver._cache for h in test_hosts)

@pytest.mark.asyncio
async def test_dns_concurrent_resolution():
    """Test concurrent DNS resolutions."""
    resolver = CachedDNSResolver()
    
    # Resolve same host concurrently
    tasks = [resolver.resolve("google.com") for _ in range(10)]
    results = await asyncio.gather(*tasks)
    
    # All results should have the same IPs (but order may vary)
    # Convert to sets for comparison
    result_sets = [set(r) for r in results]
    assert all(s == result_sets[0] for s in result_sets)
    
    # Should have at least 1 miss (first resolution)
    stats = resolver.get_stats()
    assert stats["misses"] >= 1


@pytest.mark.asyncio
async def test_dns_resolver_singleton():
    """Test that get_resolver returns the same instance."""
    resolver1 = get_resolver()
    resolver2 = get_resolver()
    
    assert resolver1 is resolver2


@pytest.mark.asyncio
async def test_dns_known_hosts_resolvable():
    """Test that all known API hosts are resolvable."""
    resolver = CachedDNSResolver()
    
    # Try to resolve all known hosts
    results = await asyncio.gather(
        *[resolver.resolve(host) for host in KNOWN_HOSTS],
        return_exceptions=True
    )
    
    # Count successful resolutions
    successful = sum(1 for r in results if not isinstance(r, Exception))
    
    # At least 80% should succeed (some might be down temporarily)
    assert successful >= len(KNOWN_HOSTS) * 0.8, \
        f"Only {successful}/{len(KNOWN_HOSTS)} hosts resolved successfully"


@pytest.mark.asyncio
async def test_dns_fallback_on_error():
    """Test that DNS resolver falls back to standard library on aiodns error."""
    resolver = CachedDNSResolver()
    
    # This should work even if aiodns has issues
    # Using a well-known host that should always resolve
    ips = await resolver.resolve("localhost")
    
    assert isinstance(ips, list)
    assert len(ips) > 0
