package com.jamarr.android.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import com.jamarr.android.playback.DiagnosticEntry
import com.jamarr.android.playback.PlaybackDetails
import com.jamarr.android.playback.PlaybackErrorPolicy
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrType
import java.util.Date

/**
 * Source, decoder and output details for the local player, plus the recent
 * failure record. Diagnostics only: every field the platform does not report
 * reads "not reported", and nothing claims a bit-perfect path.
 *
 * "Copy diagnostics" puts the redacted record on the clipboard; that is the
 * one way it leaves the device, and only by the user's hand.
 */
@Composable
fun PlaybackDetailsSheet(
    details: PlaybackDetails,
    diagnostics: List<DiagnosticEntry>,
    diagnosticsText: () -> String,
    onDismiss: () -> Unit,
) {
    val clipboard = LocalClipboardManager.current
    // The platform's time format follows the user's locale and 12/24 h setting.
    val timeFormat = android.text.format.DateFormat.getTimeFormat(LocalContext.current)
    Dialog(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .clip(RoundedCornerShape(16.dp))
                .background(JamarrColors.Card)
                .heightIn(max = 560.dp)
                .verticalScroll(rememberScrollState())
                .padding(vertical = 12.dp),
        ) {
            Text(
                text = "Playback details",
                style = JamarrType.SectionHeader,
                color = JamarrColors.Text,
                modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding, vertical = 6.dp),
            )

            Group("Source")
            DetailRow("From", details.source?.replaceFirstChar { it.uppercase() })
            DetailRow("In library", details.originalLabel)
            DetailRow("Delivered", details.deliveredLabel)
            DetailRow(
                "Source rate / depth",
                listOfNotNull(
                    details.sourceSampleRateHz?.let(PlaybackDetails::hz),
                    details.sourceBitDepth?.let { "$it-bit" },
                ).joinToString(" / ").ifBlank { null },
            )

            Group("Decoder")
            DetailRow("Stream", details.streamMimeType?.removePrefix("audio/")?.uppercase())
            DetailRow(
                "Stream rate / channels",
                listOfNotNull(
                    details.streamSampleRateHz?.let(PlaybackDetails::hz),
                    details.streamChannels?.let { channels(it) },
                ).joinToString(" / ").ifBlank { null },
            )
            DetailRow("Decoded as", PlaybackDetails.encodingName(details.streamPcmEncoding))
            DetailRow("Bitrate", details.streamBitrate?.let { "${it / 1000} kbps" })
            DetailRow("Decoder", details.decoderName)

            Group("Output")
            DetailRow("Route", details.route?.let { if (details.routeExact) it else "$it (likely)" })
            DetailRow("AudioTrack format", PlaybackDetails.encodingName(details.sinkEncoding))
            DetailRow(
                "AudioTrack rate / channels",
                listOfNotNull(
                    details.sinkSampleRateHz?.let(PlaybackDetails::hz),
                    details.sinkChannelCount?.let { channels(it) },
                ).joinToString(" / ").ifBlank { null },
            )
            DetailRow("Mixer rate", details.mixerSampleRateHz?.let(PlaybackDetails::hz))
            DetailRow("Buffer", details.sinkBufferBytes?.let { "${it / 1024} KB" })
            DetailRow(
                "Mode",
                when {
                    details.sinkOffload == null -> null
                    details.sinkOffload -> "Offload"
                    details.sinkTunneling == true -> "Tunneled"
                    else -> "Mixed (standard)"
                },
            )

            Group("Processing")
            val processing = details.processing()
            if (processing.isEmpty()) {
                Note("Nothing can be inferred yet.")
            } else {
                processing.forEach { Note("• $it") }
            }
            Note(
                "Inferred from reported numbers. Android does not expose the DAC or any DSP after " +
                    "the AudioTrack, so this is not a bit-perfect claim.",
            )

            Group("Recent problems")
            val recent = diagnostics.takeLast(5).asReversed()
            if (recent.isEmpty()) {
                Note("None recorded.")
            } else {
                recent.forEach { e ->
                    Note(
                        "${timeFormat.format(Date(e.atMs))}  " +
                            (e.kind?.let { PlaybackErrorPolicy.describe(it) } ?: "ok") +
                            " · ${e.stage}" +
                            (e.httpStatus?.let { " · HTTP $it" } ?: ""),
                    )
                }
            }
            Spacer(Modifier.height(8.dp))
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = JamarrDims.ScreenPadding),
                horizontalArrangement = androidx.compose.foundation.layout.Arrangement.End,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "Copy diagnostics",
                    style = JamarrType.Caption,
                    color = JamarrColors.Primary,
                    modifier = Modifier
                        .clickable { clipboard.setText(AnnotatedString(diagnosticsText())) }
                        .padding(8.dp),
                )
                Text(
                    text = "Close",
                    style = JamarrType.Caption,
                    color = JamarrColors.Text,
                    modifier = Modifier
                        .clickable(onClick = onDismiss)
                        .padding(8.dp),
                )
            }
        }
    }
}

private fun channels(count: Int): String = when (count) {
    1 -> "mono"
    2 -> "stereo"
    else -> "$count ch"
}

@Composable
private fun Group(title: String) {
    Text(
        text = title,
        style = JamarrType.CardTitle,
        color = JamarrColors.Primary,
        modifier = Modifier.padding(start = JamarrDims.ScreenPadding, end = JamarrDims.ScreenPadding, top = 12.dp, bottom = 2.dp),
    )
}

@Composable
private fun DetailRow(label: String, value: String?) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = JamarrDims.ScreenPadding, vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text = label, style = JamarrType.CaptionSmall, color = JamarrColors.Muted, modifier = Modifier.weight(1f))
        Text(
            text = value ?: "not reported",
            style = JamarrType.Caption,
            color = if (value == null) JamarrColors.Muted else JamarrColors.Text,
        )
    }
}

@Composable
private fun Note(text: String) {
    Text(
        text = text,
        style = JamarrType.CaptionSmall,
        color = JamarrColors.Muted,
        modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding, vertical = 2.dp),
    )
}
