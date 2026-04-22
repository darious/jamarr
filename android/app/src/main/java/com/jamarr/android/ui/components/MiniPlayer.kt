package com.jamarr.android.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrShapes
import com.jamarr.android.ui.theme.JamarrType

@Composable
fun MiniPlayer(
    title: String,
    artist: String?,
    isPlaying: Boolean,
    artworkUrl: String?,
    seedName: String,
    onToggle: () -> Unit,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(JamarrDims.MiniPlayerHeight)
            .background(JamarrColors.Surface)
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
        }
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            ControlButton(onClick = onPrevious) {
                SkipPreviousIcon(tint = JamarrColors.Text, size = 18.dp)
            }
            PrimaryControlButton(onClick = onToggle) {
                if (isPlaying) {
                    PauseIcon(tint = Color.White, size = 18.dp)
                } else {
                    PlayIcon(tint = Color.White, size = 18.dp)
                }
            }
            ControlButton(onClick = onNext) {
                SkipNextIcon(tint = JamarrColors.Text, size = 18.dp)
            }
            ControlButton(onClick = onStop) {
                StopIcon(tint = JamarrColors.Muted, size = 14.dp)
            }
        }
    }
}

@Composable
private fun ControlButton(onClick: () -> Unit, content: @Composable () -> Unit) {
    Box(
        modifier = Modifier
            .size(36.dp)
            .clip(CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { content() }
}

@Composable
private fun PrimaryControlButton(onClick: () -> Unit, content: @Composable () -> Unit) {
    Box(
        modifier = Modifier
            .size(40.dp)
            .clip(CircleShape)
            .background(JamarrColors.Primary)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { content() }
}
