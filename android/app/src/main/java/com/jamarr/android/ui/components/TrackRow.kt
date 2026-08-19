package com.jamarr.android.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import com.jamarr.android.download.DownloadProgress
import com.jamarr.android.download.db.DownloadRecordState
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrType

@Composable
fun TrackRow(
    number: Int?,
    title: String,
    subtitle: String?,
    duration: String?,
    active: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    missing: Boolean = false,
    downloadState: DownloadProgress? = null,
    onDownloadClick: (() -> Unit)? = null,
) {
    val background = if (active) JamarrColors.PrimaryTint else JamarrColors.Bg
    // Missing tracks are struck through and dimmed, matching the web UI's
    // TrackCard treatment; otherwise the only tell is an absent duration.
    val titleColor = when {
        active -> JamarrColors.Primary
        missing -> JamarrColors.Neutral
        else -> JamarrColors.Text
    }

    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(background)
            .clickable(onClick = onClick)
            .padding(horizontal = JamarrDims.ScreenPadding, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(modifier = Modifier.width(28.dp), contentAlignment = Alignment.Center) {
            if (active) {
                PlayIcon(tint = JamarrColors.Primary, size = 14.dp)
            } else if (number != null) {
                Text(
                    text = number.toString(),
                    style = JamarrType.TrackNumber,
                    color = JamarrColors.Neutral,
                    textAlign = TextAlign.Center,
                )
            }
        }
        Spacer(Modifier.width(8.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                // Carried as a span rather than the textDecoration parameter: the
                // parameter is applied at draw time and so is invisible to both
                // semantics and the text layout result, leaving it untestable.
                text = if (missing) struckThrough(title) else AnnotatedString(title),
                style = JamarrType.CardTitle,
                color = titleColor,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (!subtitle.isNullOrBlank()) {
                Text(
                    text = subtitle,
                    style = JamarrType.CaptionSmall,
                    color = JamarrColors.Muted,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        if (!duration.isNullOrBlank()) {
            Spacer(Modifier.width(8.dp))
            Text(
                text = duration,
                style = JamarrType.Caption,
                color = JamarrColors.Neutral,
            )
        }
        if (onDownloadClick != null) {
            Spacer(Modifier.width(4.dp))
            DownloadAffordance(state = downloadState, onClick = onDownloadClick)
        }
    }
}

/**
 * Trailing download control: tap to queue, tap again once complete to remove.
 * Mid-download it shows percentage rather than an icon, so a stalled transfer
 * is visible instead of looking idle.
 */
@Composable
private fun DownloadAffordance(state: DownloadProgress?, onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .size(32.dp)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        when (state?.state) {
            DownloadRecordState.COMPLETED ->
                DownloadDoneIcon(tint = JamarrColors.Primary, size = 16.dp)
            DownloadRecordState.DOWNLOADING -> Text(
                text = state.percent?.let { "${it.toInt()}%" } ?: "…",
                style = JamarrType.CaptionSmall,
                color = JamarrColors.Primary,
            )
            DownloadRecordState.QUEUED -> Text(
                text = "…",
                style = JamarrType.CaptionSmall,
                color = JamarrColors.Muted,
            )
            DownloadRecordState.FAILED -> Text(
                text = "!",
                style = JamarrType.CaptionSmall,
                color = JamarrColors.Neutral,
            )
            null -> DownloadIcon(tint = JamarrColors.Muted, size = 16.dp)
        }
    }
}

private fun struckThrough(text: String): AnnotatedString = buildAnnotatedString {
    withStyle(SpanStyle(textDecoration = TextDecoration.LineThrough)) { append(text) }
}

fun formatDuration(seconds: Double?): String? {
    val s = seconds?.toInt() ?: return null
    val m = s / 60
    val ss = s % 60
    return "%d:%02d".format(m, ss)
}

fun formatTotalDuration(seconds: Double?): String? {
    val s = seconds?.toInt() ?: return null
    val minutes = s / 60
    return if (minutes >= 60) {
        "${minutes / 60}h ${minutes % 60}m"
    } else {
        "${minutes} min"
    }
}
