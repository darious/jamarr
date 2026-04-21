package com.jamarr.android.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.sp
import coil3.compose.AsyncImage
import com.jamarr.android.ui.theme.JamarrColors

@Composable
fun ArtistArt(
    name: String,
    imageUrl: String?,
    size: Dp,
    modifier: Modifier = Modifier,
) {
    val shape = CircleShape
    if (!imageUrl.isNullOrBlank()) {
        AsyncImage(
            model = imageUrl,
            contentDescription = name,
            modifier = modifier
                .size(size)
                .clip(shape)
                .background(JamarrColors.Card),
        )
        return
    }

    Box(
        modifier = modifier
            .size(size)
            .clip(shape)
            .background(artistGradient(name)),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = name.firstOrNull()?.uppercaseChar()?.toString() ?: "?",
            color = Color.White.copy(alpha = 0.9f),
            fontWeight = FontWeight.W700,
            fontSize = (size.value * 0.4f).sp,
        )
    }
}

private fun artistGradient(name: String): Brush {
    val seed = seedColor(name)
    return Brush.sweepGradient(
        colors = listOf(seed, JamarrColors.Primary.copy(alpha = 0.4f), seed),
    )
}
