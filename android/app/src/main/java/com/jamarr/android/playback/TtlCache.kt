package com.jamarr.android.playback

import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Short-lived memo for browse lookups.
 *
 * Browsing the car tree fans one screen out into several API calls, and
 * sibling nodes overlap heavily — an artist's Singles and Most Scrobbled
 * folders both re-read the artist detail the discography screen already
 * loaded. Caching for a few tens of seconds removes that duplication
 * without the tree ever looking stale in a single sitting.
 *
 * Loads are single-flighted per key so a burst of parallel node builds shares
 * one request rather than racing. The cache holds at most [maxEntries]
 * values, least recently used first out, so a long browsing session cannot
 * grow it without bound (#321).
 */
class TtlCache(
    private val ttlMs: Long,
    private val now: () -> Long = System::currentTimeMillis,
    private val maxEntries: Int = DEFAULT_MAX_ENTRIES,
) {
    private class Entry(val value: Any, val expiresAtMs: Long)

    private val guard = Mutex()
    private val entries = object : LinkedHashMap<String, Entry>(64, 0.75f, /* accessOrder= */ true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, Entry>?): Boolean = size > maxEntries
    }
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

    /** The live value for [key], or null; never loads. */
    @Suppress("UNCHECKED_CAST")
    suspend fun <T : Any> peek(key: String): T? = guard.withLock {
        val entry = entries[key] ?: return@withLock null
        if (entry.expiresAtMs <= now()) {
            entries.remove(key)
            null
        } else {
            entry.value as T
        }
    }

    suspend fun size(): Int = guard.withLock { entries.size }

    suspend fun invalidate(key: String) {
        guard.withLock { entries.remove(key) }
    }

    /** Drops everything — used when the session changes and content is no longer the same user's. */
    suspend fun invalidateAll() {
        guard.withLock { entries.clear() }
    }

    companion object {
        const val DEFAULT_MAX_ENTRIES = 256
    }
}
