package com.jamarr.android.playback

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Rect
import java.io.ByteArrayOutputStream

/**
 * Composites up to four covers into a 2x2 grid, matching the playlist covers
 * in the phone UI. Tiles are used in order so a folder keeps the same cover
 * between visits; fewer than four are repeated to fill the quadrants.
 */
object ArtworkGrid {
    const val JPEG_QUALITY = 90

    fun compose(tiles: List<ByteArray>, sizePx: Int): ByteArray? {
        val fetched = tiles.filter { it.isNotEmpty() }
        if (fetched.isEmpty()) return null
        if (fetched.size == 1) return fetched[0]

        val bitmaps = fetched.mapNotNull { decodeBounded(it, sizePx) }
        if (bitmaps.size <= 1) {
            bitmaps.forEach { it.recycle() }
            return fetched[0]
        }
        val padded = when (bitmaps.size) {
            2 -> listOf(bitmaps[0], bitmaps[1], bitmaps[1], bitmaps[0])
            3 -> listOf(bitmaps[0], bitmaps[1], bitmaps[2], bitmaps[0])
            else -> bitmaps.take(4)
        }
        val out = Bitmap.createBitmap(sizePx, sizePx, Bitmap.Config.ARGB_8888)
        try {
            val canvas = Canvas(out)
            val half = sizePx / 2
            val rects = listOf(
                Rect(0, 0, half, half),
                Rect(half, 0, sizePx, half),
                Rect(0, half, half, sizePx),
                Rect(half, half, sizePx, sizePx),
            )
            val paint = Paint(Paint.FILTER_BITMAP_FLAG or Paint.ANTI_ALIAS_FLAG)
            padded.forEachIndexed { i, bitmap -> canvas.drawBitmap(bitmap, null, rects[i], paint) }
            val stream = ByteArrayOutputStream()
            out.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, stream)
            return stream.toByteArray()
        } finally {
            out.recycle()
            bitmaps.forEach { it.recycle() }
        }
    }

    /** Decodes at no more than twice the target edge, so a hero-sized file costs a tile's memory. */
    private fun decodeBounded(bytes: ByteArray, sizePx: Int): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        var sample = 1
        val target = sizePx // a tile is half the grid; sizePx keeps it sharp
        while (bounds.outWidth / (sample * 2) >= target && bounds.outHeight / (sample * 2) >= target) sample *= 2
        val opts = BitmapFactory.Options().apply { inSampleSize = sample }
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, opts)
    }
}
