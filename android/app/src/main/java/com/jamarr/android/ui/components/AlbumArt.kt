package com.jamarr.android.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil3.compose.AsyncImage
import com.jamarr.android.ui.theme.JamarrColors

@Composable
fun AlbumArt(
    title: String,
    seedName: String,
    artworkUrl: String?,
    modifier: Modifier = Modifier,
) {
    if (!artworkUrl.isNullOrBlank()) {
        AsyncImage(
            model = artworkUrl,
            contentDescription = title,
            modifier = modifier.background(gradientFor(seedName)),
        )
        return
    }

    Box(
        modifier = modifier.background(gradientFor(seedName)),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = initials(title),
            color = Color(0xFFFFFFFF).copy(alpha = 0.85f),
            fontWeight = FontWeight.W700,
            fontSize = 22.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(6.dp),
        )
    }
}

private fun initials(title: String): String {
    val words = title.trim().split(Regex("\\s+")).filter { it.isNotBlank() }
    return words.take(3).joinToString("") { it.first().uppercase() }
}

fun gradientFor(seed: String): Brush {
    val seedColor = seedColor(seed)
    return Brush.linearGradient(
        colors = listOf(seedColor, JamarrColors.Bg),
    )
}

internal fun seedColor(seed: String): Color {
    if (seed.isBlank()) return Color(0xFF2E1818)
    val hash = seed.fold(0) { acc, c -> (acc * 31 + c.code) and 0x7FFFFFFF }
    val hue = (hash % 360).toFloat()
    return hsvToColor(hue, 0.55f, 0.28f)
}

private fun hsvToColor(h: Float, s: Float, v: Float): Color {
    val c = v * s
    val hh = (h % 360f) / 60f
    val x = c * (1f - kotlin.math.abs((hh % 2f) - 1f))
    val (r1, g1, b1) = when (hh.toInt()) {
        0 -> Triple(c, x, 0f)
        1 -> Triple(x, c, 0f)
        2 -> Triple(0f, c, x)
        3 -> Triple(0f, x, c)
        4 -> Triple(x, 0f, c)
        else -> Triple(c, 0f, x)
    }
    val m = v - c
    return Color(red = r1 + m, green = g1 + m, blue = b1 + m, alpha = 1f)
}
