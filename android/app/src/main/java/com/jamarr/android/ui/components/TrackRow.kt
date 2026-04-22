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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
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
) {
    val background = if (active) JamarrColors.PrimaryTint else JamarrColors.Bg
    val titleColor = if (active) JamarrColors.Primary else JamarrColors.Text

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
                text = title,
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
    }
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
