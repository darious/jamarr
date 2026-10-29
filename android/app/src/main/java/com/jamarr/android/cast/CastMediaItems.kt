package com.jamarr.android.cast

import android.net.Uri
import com.google.android.gms.cast.MediaInfo
import com.google.android.gms.cast.MediaMetadata
import com.google.android.gms.common.images.WebImage
import com.jamarr.android.renderer.QueuedTrack
import org.json.JSONObject

/** Conversions between Jamarr tracks and Cast SDK media objects. */
internal object CastMediaItems {

    /** MediaInfo for [track], stamped with its Jamarr identity. */
    fun mediaInfo(track: QueuedTrack, serverUrl: String?): MediaInfo {
        val metadata = MediaMetadata(MediaMetadata.MEDIA_TYPE_MUSIC_TRACK).apply {
            putString(MediaMetadata.KEY_TITLE, track.title)
            putString(MediaMetadata.KEY_ARTIST, track.artist)
            putString(MediaMetadata.KEY_ALBUM_TITLE, track.album)
            track.artUrl?.let { addImage(WebImage(Uri.parse(it))) }
        }
        return MediaInfo.Builder(track.streamUrl)
            .setStreamType(MediaInfo.STREAM_TYPE_BUFFERED)
            .setContentType(track.mime)
            .setMetadata(metadata)
            .setCustomData(toJson(CastIdentity.customData(track, serverUrl)))
            .build()
    }

    /** What the receiver reports for one item, as plain data. */
    fun receiverItem(itemId: Int, media: MediaInfo?): ReceiverItem? {
        media ?: return null
        val metadata = media.metadata
        val duration = media.streamDuration.takeIf { it > 0 }?.let { it / 1000.0 }
        return ReceiverItem(
            itemId = itemId,
            contentId = media.contentId.takeIf { !it.isNullOrBlank() } ?: media.contentUrl,
            contentType = media.contentType,
            title = metadata?.getString(MediaMetadata.KEY_TITLE),
            artist = metadata?.getString(MediaMetadata.KEY_ARTIST),
            album = metadata?.getString(MediaMetadata.KEY_ALBUM_TITLE),
            artUrl = metadata?.images?.firstOrNull()?.url?.toString(),
            durationSeconds = duration,
            custom = toMap(media.customData),
        )
    }

    fun toJson(map: Map<String, Any?>): JSONObject = JSONObject().apply {
        map.forEach { (key, value) -> if (value != null) put(key, value) }
    }

    fun toMap(json: JSONObject?): Map<String, Any?> {
        json ?: return emptyMap()
        val out = mutableMapOf<String, Any?>()
        val keys = json.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            out[key] = json.opt(key)?.takeIf { it != JSONObject.NULL }
        }
        return out
    }
}
