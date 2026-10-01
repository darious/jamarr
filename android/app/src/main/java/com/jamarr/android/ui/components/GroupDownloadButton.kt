package com.jamarr.android.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.jamarr.android.download.GroupDownloadStatus
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrType

/**
 * Download control for a whole album, playlist or list: an arrow when nothing
 * is requested, progress while it runs, a tick once every track is on disk.
 * Any failed track shows `!` so a group that will never finish does not sit at
 * 97% looking busy.
 */
@Composable
fun GroupDownloadButton(
    status: GroupDownloadStatus?,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    size: Dp = 48.dp,
) {
    val description = when {
        status == null -> "Download"
        status.isComplete -> "Downloaded, remove"
        status.hasFailures -> "Download failed for ${status.failed} tracks, remove"
        else -> "Downloading, cancel"
    }
    Box(
        modifier = modifier
            .size(size)
            .clip(CircleShape)
            .border(BorderStroke(1.dp, JamarrColors.Border), CircleShape)
            .clickable(onClick = onClick)
            .semantics { contentDescription = description },
        contentAlignment = Alignment.Center,
    ) {
        when {
            status == null -> DownloadIcon(tint = JamarrColors.Text, size = size * 0.42f)
            status.isComplete -> DownloadDoneIcon(tint = JamarrColors.Primary, size = size * 0.42f)
            status.hasFailures -> Text(text = "!", style = JamarrType.CardTitle, color = JamarrColors.Neutral)
            else -> Text(
                text = "${status.percent.toInt()}%",
                style = JamarrType.CaptionSmall,
                color = JamarrColors.Primary,
            )
        }
    }
}
