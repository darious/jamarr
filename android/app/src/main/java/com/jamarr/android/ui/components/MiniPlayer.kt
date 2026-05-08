package com.jamarr.android.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.jamarr.android.ui.components.RepeatIcon
import com.jamarr.android.ui.components.RepeatOneIcon
import com.jamarr.android.ui.components.ShuffleIcon
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrShapes
import com.jamarr.android.ui.theme.JamarrType

@Composable
fun MiniPlayer(
    title: String,
    artist: String?,
    isPlaying: Boolean,
    artworkUrl: String?,
    seedName: String,
    progressMs: Long,
    durationMs: Long,
    originalQualityLabel: String = "Original",
    playbackQualityLabel: String = "Original",
    shuffleEnabled: Boolean = false,
    repeatMode: Int = 0,
    onToggle: () -> Unit,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
    onStop: () -> Unit,
    onSeek: (Long) -> Unit,
    onClick: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .background(JamarrColors.Surface)
            .clickable(onClick = onClick),
    ) {
        // Progress bar - tappable to seek
        ProgressBar(
            progressMs = progressMs,
            durationMs = durationMs,
            onSeek = onSeek,
        )

        // Controls row
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .clip(JamarrShapes.AlbumArt)
                    .background(JamarrColors.Card),
            ) {
                AlbumArt(
                    title = title,
                    seedName = seedName,
                    artworkUrl = artworkUrl,
                    modifier = Modifier.fillMaxSize(),
                )
            }
            Spacer(Modifier.width(10.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = title,
                    style = JamarrType.CardTitle,
                    color = JamarrColors.Text,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (!artist.isNullOrBlank()) {
                    Text(
                        text = artist,
                        style = JamarrType.CaptionSmall,
                        color = JamarrColors.Muted,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Text(
                    text = "$originalQualityLabel -> $playbackQualityLabel",
                    style = JamarrType.CaptionSmall,
                    color = JamarrColors.Muted,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (shuffleEnabled || repeatMode != 0) {
                Spacer(Modifier.width(4.dp))
                if (shuffleEnabled) {
                    ShuffleIcon(tint = JamarrColors.Primary, size = 14.dp)
                }
                if (repeatMode == 2) {
                    Spacer(Modifier.width(2.dp))
                    RepeatIcon(tint = JamarrColors.Primary, size = 14.dp)
                } else if (repeatMode == 1) {
                    Spacer(Modifier.width(2.dp))
                    RepeatOneIcon(tint = JamarrColors.Primary, size = 14.dp)
                }
            }
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                ControlButton(contentDescription = "Previous", onClick = onPrevious) {
                    SkipPreviousIcon(tint = JamarrColors.Text, size = 18.dp)
                }
                PrimaryControlButton(contentDescription = if (isPlaying) "Pause" else "Play", onClick = onToggle) {
                    if (isPlaying) {
                        PauseIcon(tint = Color.White, size = 18.dp)
                    } else {
                        PlayIcon(tint = Color.White, size = 18.dp)
                    }
                }
                ControlButton(contentDescription = "Next", onClick = onNext) {
                    SkipNextIcon(tint = JamarrColors.Text, size = 18.dp)
                }
                ControlButton(contentDescription = "Stop", onClick = onStop) {
                    StopIcon(tint = JamarrColors.Muted, size = 14.dp)
                }
            }
        }
    }
}

@Composable
private fun ProgressBar(
    progressMs: Long,
    durationMs: Long,
    onSeek: (Long) -> Unit,
) {
    val fraction = if (durationMs > 0) {
        (progressMs.toFloat() / durationMs.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(44.dp)
            .pointerInput(durationMs) {
                detectTapGestures { offset ->
                    if (durationMs > 0) {
                        val f = (offset.x / size.width.toFloat()).coerceIn(0f, 1f)
                        onSeek((f * durationMs).toLong())
                    }
                }
            },
        contentAlignment = Alignment.Center,
    ) {
        // Track background
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(3.dp)
                .clip(RoundedCornerShape(1.5.dp))
                .background(JamarrColors.Border),
        )
        // Filled portion
        if (fraction > 0f) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(fraction)
                    .height(3.dp)
                    .clip(RoundedCornerShape(1.5.dp))
                    .background(JamarrColors.Primary)
                    .align(Alignment.CenterStart),
            )
        }
    }
}

@Composable
private fun ControlButton(contentDescription: String, onClick: () -> Unit, content: @Composable () -> Unit) {
    Box(
        modifier = Modifier
            .size(36.dp)
            .clip(CircleShape)
            .semantics { this.contentDescription = contentDescription }
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { content() }
}

@Composable
private fun PrimaryControlButton(contentDescription: String, onClick: () -> Unit, content: @Composable () -> Unit) {
    Box(
        modifier = Modifier
            .size(40.dp)
            .clip(CircleShape)
            .background(JamarrColors.Primary)
            .semantics { this.contentDescription = contentDescription }
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { content() }
}
