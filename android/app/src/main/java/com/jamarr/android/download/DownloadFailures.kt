package com.jamarr.android.download

import java.io.IOException
import java.net.ConnectException
import java.net.SocketException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

/**
 * Why a download stopped for good — the part of Media3's `finalException`
 * worth keeping. Stored by name in Room so the reason survives a restart,
 * where Media3's own index only remembers "failed".
 */
enum class DownloadFailureReason {
    /** The stream token or session was rejected (HTTP 401/403): sign in again, then retry. */
    AUTH,
    /** The server has no such track (HTTP 404/410). */
    NOT_FOUND,
    /** Could not reach the server or the connection dropped: retry when back online. */
    NETWORK,
    /** The server failed (5xx) or answered with something that was not audio. */
    SERVER,
    /** The device ran out of space mid-write: free space, then retry. */
    STORAGE_FULL,
    /** Storage refused the write for another reason (read-only, permission, corrupt index). */
    STORAGE_IO,
    UNKNOWN;

    val label: String
        get() = when (this) {
            AUTH -> "sign-in expired"
            NOT_FOUND -> "not on server"
            NETWORK -> "network error"
            SERVER -> "server error"
            STORAGE_FULL -> "no space left"
            STORAGE_IO -> "storage error"
            UNKNOWN -> "failed"
        }

    /** What the user can do about it, for the Downloads screen. */
    val advice: String
        get() = when (this) {
            AUTH -> "Sign in again, then retry."
            NOT_FOUND -> "The server no longer has this track."
            NETWORK -> "Retries when the server is reachable."
            SERVER -> "Retry later."
            STORAGE_FULL -> "Free up space, then retry."
            STORAGE_IO -> "Check the device's storage, then retry."
            UNKNOWN -> "Retry."
        }

    /** False for the reasons a retry cannot change. */
    val retryable: Boolean get() = this != NOT_FOUND

    companion object {
        fun fromName(name: String?): DownloadFailureReason? =
            name?.let { n -> entries.firstOrNull { it.name == n } }
    }
}

object DownloadFailures {
    private val noSpace = Regex("""ENOSPC|No space left|EDQUOT|disk quota""", RegexOption.IGNORE_CASE)
    private val readOnly = Regex("""EROFS|Read-only file system|EACCES|Permission denied|EIO\b|I/O error""", RegexOption.IGNORE_CASE)

    /**
     * Classifies a failure from its HTTP status (when the data source saw a
     * response) and the exception chain. [httpStatus] is extracted by the
     * caller because the media3 exception type that carries it needs Android
     * classes, and this stays testable on the JVM.
     */
    fun classify(httpStatus: Int?, error: Throwable?): DownloadFailureReason {
        when (httpStatus) {
            401, 403 -> return DownloadFailureReason.AUTH
            404, 410 -> return DownloadFailureReason.NOT_FOUND
            in 500..599 -> return DownloadFailureReason.SERVER
            else -> Unit
        }
        var cause = error
        var hops = 0
        while (cause != null && hops++ < 10) {
            val text = (cause.message ?: "") + " " + cause.javaClass.simpleName
            when {
                noSpace.containsMatchIn(text) -> return DownloadFailureReason.STORAGE_FULL
                readOnly.containsMatchIn(text) -> return DownloadFailureReason.STORAGE_IO
                cause.javaClass.simpleName == "CacheException" -> return DownloadFailureReason.STORAGE_IO
                cause is UnknownHostException || cause is ConnectException ||
                    cause is SocketTimeoutException || cause is SocketException -> return DownloadFailureReason.NETWORK
            }
            cause = cause.cause
        }
        if (httpStatus != null && httpStatus >= 400) return DownloadFailureReason.SERVER
        // A generic IOException from an HTTP source is a dropped connection far
        // more often than anything else.
        return if (error is IOException) DownloadFailureReason.NETWORK else DownloadFailureReason.UNKNOWN
    }
}
