package com.jamarr.android.download

import coil3.intercept.Interceptor
import coil3.request.ImageResult
import java.io.File

/**
 * Cover art for downloaded music, one file per artwork hash.
 *
 * One size is kept rather than one per call site (lists ask for 200, heroes for
 * 800): Coil scales the file to whatever the view needs, and 600 px is sharp
 * enough for a hero while keeping a large library's art in the tens of MB.
 */
class OfflineArtworkStore(private val dir: File) {
    fun file(artSha1: String): File = File(dir, "$artSha1.img")

    /** The stored file, or null when this artwork is not on disk. */
    fun existing(artSha1: String): File? = file(artSha1).takeIf { it.isFile && it.length() > 0 }

    /**
     * Fetches [artSha1] unless it is already stored. Writes through a temp file
     * so a fetch that dies half-way never leaves a truncated image to be served.
     */
    suspend fun ensure(artSha1: String, fetch: suspend (String) -> ByteArray?) {
        if (existing(artSha1) != null) return
        val bytes = fetch(artSha1)?.takeIf { it.isNotEmpty() } ?: return
        dir.mkdirs()
        val tmp = File(dir, "$artSha1.tmp")
        tmp.writeBytes(bytes)
        if (!tmp.renameTo(file(artSha1))) tmp.delete()
    }

    /** Deletes stored art that nothing downloaded refers to any more. */
    fun prune(keep: Set<String>) {
        dir.listFiles()?.forEach { f ->
            if (f.nameWithoutExtension !in keep) f.delete()
        }
    }

    companion object {
        const val SIZE = 600
    }
}

object ArtworkUrls {
    private val pattern = Regex("""/api/art/file/([0-9a-fA-F]+)(?:\?|$)""")

    /** The artwork hash in a `/api/art/file/{sha1}?max_size=N` URL, or null. */
    fun sha1FromUrl(url: String): String? = pattern.find(url)?.groupValues?.get(1)
}

/**
 * Serves `/api/art/file/{sha1}` from [OfflineArtworkStore] when the art is on
 * disk, whatever size was asked for, so a downloaded album renders the same with
 * the server unreachable. Anything not stored goes to the network as before.
 */
class OfflineArtworkInterceptor(private val store: OfflineArtworkStore) : Interceptor {
    override suspend fun intercept(chain: Interceptor.Chain): ImageResult {
        val url = chain.request.data as? String ?: return chain.proceed()
        val file = ArtworkUrls.sha1FromUrl(url)?.let(store::existing) ?: return chain.proceed()
        return chain.withRequest(chain.request.newBuilder().data(file).build()).proceed()
    }
}
