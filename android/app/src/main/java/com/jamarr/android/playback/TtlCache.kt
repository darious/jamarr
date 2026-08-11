package com.jamarr.android.playback

import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Short-lived memo for browse lookups.
 *
 * Browsing the car tree fans one screen out into several API calls, and
 * sibling nodes overlap heavily — Recently Played Artists / Albums and
 * Recently Added are all one `/api/home` payload, and an artist's Singles and
 * Most Scrobbled folders both re-read the artist detail the discography screen
 * already loaded. Caching for a few tens of seconds removes that duplication
 * without the tree ever looking stale in a single sitting.
 *
 * Loads are single-flighted per key so a burst of parallel node builds shares
 * one request rather than racing.
 */
class TtlCache(
    private val ttlMs: Long,
    private val now: () -> Long = System::currentTimeMillis,
) {
    private class Entry(val value: Any, val expiresAtMs: Long)

    private val guard = Mutex()
    private val entries = mutableMapOf<String, Entry>()
    private val loadLocks = mutableMapOf<String, Mutex>()

    /** Cached value for [key], loading (once) via [loader] on miss or expiry. */
    suspend fun <T : Any> get(key: String, loader: suspend () -> T): T {
        peek<T>(key)?.let { return it }
        val lock = guard.withLock { loadLocks.getOrPut(key) { Mutex() } }
        return lock.withLock {
            // Another caller may have populated the entry while we queued.
            peek<T>(key) ?: loader().also { value ->
                guard.withLock { entries[key] = Entry(value, now() + ttlMs) }
            }
        }
    }

    @Suppress("UNCHECKED_CAST")
    private suspend fun <T : Any> peek(key: String): T? = guard.withLock {
        val entry = entries[key] ?: return@withLock null
        if (entry.expiresAtMs <= now()) {
            entries.remove(key)
            null
        } else {
            entry.value as T
        }
    }

    suspend fun invalidate(key: String) {
        guard.withLock { entries.remove(key) }
    }

    /** Drops everything — used when the session changes and content is no longer the same user's. */
    suspend fun invalidateAll() {
        guard.withLock { entries.clear() }
    }
}
