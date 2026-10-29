package com.jamarr.android.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import com.jamarr.android.download.formatBytes
import com.jamarr.android.playback.StreamQualityLadder
import com.jamarr.android.playback.StreamingQualityPrefs
import com.jamarr.android.ui.components.ConfirmDialog
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrType

/** Disk used by each kind of stored media. */
data class StorageUsage(
    val downloadBytes: Long,
    val readAheadBytes: Long,
    val artworkBytes: Long,
)

/** The server's quality ladder (`app/services/stream_profiles.py`), described for a download. */
internal val DOWNLOAD_QUALITY_OPTIONS = listOf(
    "original" to ("Original" to "Exactly as in the library; hi-res files are large"),
    "flac_24_48" to ("FLAC 24-bit / 48 kHz" to "Lossless, hi-res capped at 48 kHz"),
    "flac_16_48" to ("FLAC 16-bit / 48 kHz" to "Lossless at CD depth; a fraction of hi-res size"),
    "mp3_320" to ("MP3 320" to "Lossy, about 2.4 MB a minute"),
    "opus_128" to ("Opus 128" to "Lossy, about 1 MB a minute"),
)

/** Test tag on the streaming-cap picker, whose options repeat the download quality labels. */
internal const val STREAMING_QUALITY_DIALOG_TAG = "streaming-quality-dialog"

internal val READ_AHEAD_CAP_OPTIONS = listOf(
    256L * 1024 * 1024,
    512L * 1024 * 1024,
    1024L * 1024 * 1024,
    2048L * 1024 * 1024,
    4096L * 1024 * 1024,
)

/**
 * Download quality, Wi-Fi-only transfers, the read-ahead cap and what is
 * using the phone's storage. Everything here works offline: it is all local.
 */
@Composable
fun SettingsScreen(
    downloadQuality: String,
    wifiOnly: Boolean,
    readAheadMaxBytes: Long,
    storage: StorageUsage?,
    onBack: () -> Unit,
    onDownloadQualityChange: (String) -> Unit,
    onWifiOnlyChange: (Boolean) -> Unit,
    onReadAheadMaxBytesChange: (Long) -> Unit,
    onClearReadAhead: () -> Unit,
    onDeleteAllDownloads: () -> Unit,
    contentPadding: PaddingValues = PaddingValues(0.dp),
    streamingQuality: StreamingQualityPrefs = StreamingQualityPrefs(),
    /** (unmetered, metered): null leaves that one unchanged. */
    onStreamingQualityChange: (String?, String?) -> Unit = { _, _ -> },
) {
    var confirmDeleteAll by remember { mutableStateOf(false) }
    // Which streaming cap is being picked: "unmetered", "metered" or null.
    var pickingStreamingCap by remember { mutableStateOf<String?>(null) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(JamarrColors.Bg)
            .verticalScroll(rememberScrollState())
            .padding(bottom = contentPadding.calculateBottomPadding() + 16.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .statusBarsPadding()
                .padding(horizontal = JamarrDims.ScreenPadding, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(34.dp)
                    .clip(CircleShape)
                    .background(Color(0x66000000))
                    .clickable(onClick = onBack),
                contentAlignment = Alignment.Center,
            ) {
                Text(text = "←", color = Color.White, style = JamarrType.CardTitle)
            }
            Spacer(Modifier.width(12.dp))
            Text(text = "Settings", style = JamarrType.ScreenTitle, color = JamarrColors.Text)
        }

        SectionHeader("Streaming quality")
        ChoiceRow(
            title = "On Wi-Fi (unmetered)",
            value = StreamQualityLadder.label(streamingQuality.unmetered),
            onClick = { pickingStreamingCap = "unmetered" },
        )
        ChoiceRow(
            title = "On mobile data (metered)",
            value = StreamQualityLadder.label(streamingQuality.metered),
            onClick = { pickingStreamingCap = "metered" },
        )
        Note(
            "The most playback asks for on each kind of network; it still steps down if a stream keeps " +
                "buffering. A lower limit applies straight away when the network changes; a higher one from " +
                "the next thing you play. Downloads play at the quality they were saved at.",
        )

        SectionHeader("Download quality")
        DOWNLOAD_QUALITY_OPTIONS.forEach { (key, text) ->
            RadioRow(
                title = text.first,
                subtitle = text.second,
                selected = key == downloadQuality,
                onClick = { onDownloadQualityChange(key) },
            )
        }
        Note("Applies to new downloads. What is already downloaded keeps its quality and plays as it is.")

        SectionHeader("Network")
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { onWifiOnlyChange(!wifiOnly) }
                .padding(horizontal = JamarrDims.ScreenPadding, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text("Downloads on Wi-Fi only", style = JamarrType.CardTitle, color = JamarrColors.Text)
                Text(
                    text = "Downloads and read-ahead wait for an unmetered network. Playback itself is " +
                        "governed by Streaming quality above.",
                    style = JamarrType.CaptionSmall,
                    color = JamarrColors.Muted,
                )
            }
            Switch(
                checked = wifiOnly,
                onCheckedChange = onWifiOnlyChange,
                colors = SwitchDefaults.colors(
                    checkedThumbColor = Color.White,
                    checkedTrackColor = JamarrColors.Primary,
                ),
            )
        }

        SectionHeader("Read-ahead cache")
        READ_AHEAD_CAP_OPTIONS.forEach { bytes ->
            RadioRow(
                title = formatBytes(bytes),
                subtitle = null,
                selected = bytes == readAheadMaxBytes,
                onClick = { onReadAheadMaxBytesChange(bytes) },
            )
        }
        Note("The next track is fetched ahead so it starts at once. Oldest data is dropped past this size.")

        SectionHeader("Storage")
        StorageRow("Downloads", storage?.downloadBytes)
        StorageRow("Read-ahead", storage?.readAheadBytes, actionLabel = "Clear", onAction = onClearReadAhead)
        StorageRow("Artwork", storage?.artworkBytes)
        Spacer(Modifier.height(8.dp))
        Text(
            text = "Delete all downloads",
            style = JamarrType.CardTitle,
            color = JamarrColors.Primary,
            modifier = Modifier
                .fillMaxWidth()
                .clickable { confirmDeleteAll = true }
                .padding(horizontal = JamarrDims.ScreenPadding, vertical = 12.dp),
        )
    }

    pickingStreamingCap?.let { which ->
        val current = if (which == "metered") streamingQuality.metered else streamingQuality.unmetered
        QualityPickerDialog(
            title = if (which == "metered") "Streaming on mobile data" else "Streaming on Wi-Fi",
            selected = current,
            onSelect = { key ->
                if (which == "metered") onStreamingQualityChange(null, key) else onStreamingQualityChange(key, null)
                pickingStreamingCap = null
            },
            onDismiss = { pickingStreamingCap = null },
        )
    }

    if (confirmDeleteAll) {
        ConfirmDialog(
            title = "Delete all downloads?",
            text = "Every downloaded track and its artwork will be removed from this device.",
            confirmLabel = "Delete",
            onConfirm = {
                confirmDeleteAll = false
                onDeleteAllDownloads()
            },
            onDismiss = { confirmDeleteAll = false },
        )
    }
}

/** A setting whose value is picked from a dialog: title on the left, current value on the right. */
@Composable
private fun ChoiceRow(title: String, value: String, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = JamarrDims.ScreenPadding, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text = title, style = JamarrType.CardTitle, color = JamarrColors.Text, modifier = Modifier.weight(1f))
        Text(text = value, style = JamarrType.Body, color = JamarrColors.Primary)
    }
}

@Composable
private fun QualityPickerDialog(
    title: String,
    selected: String,
    onSelect: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    Dialog(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .testTag(STREAMING_QUALITY_DIALOG_TAG)
                .clip(androidx.compose.foundation.shape.RoundedCornerShape(16.dp))
                .background(JamarrColors.Card)
                .padding(vertical = 12.dp),
        ) {
            Text(
                text = title,
                style = JamarrType.SectionHeader,
                color = JamarrColors.Text,
                modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding, vertical = 6.dp),
            )
            DOWNLOAD_QUALITY_OPTIONS.forEach { (key, text) ->
                RadioRow(
                    title = text.first,
                    subtitle = text.second,
                    selected = key == selected,
                    onClick = { onSelect(key) },
                )
            }
        }
    }
}

@Composable
private fun SectionHeader(text: String) {
    Text(
        text = text,
        style = JamarrType.SectionHeader,
        color = JamarrColors.Text,
        modifier = Modifier.padding(
            start = JamarrDims.ScreenPadding,
            end = JamarrDims.ScreenPadding,
            top = 20.dp,
            bottom = 4.dp,
        ),
    )
}

@Composable
private fun Note(text: String) {
    Text(
        text = text,
        style = JamarrType.CaptionSmall,
        color = JamarrColors.Muted,
        modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding, vertical = 4.dp),
    )
}

@Composable
private fun RadioRow(title: String, subtitle: String?, selected: Boolean, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = JamarrDims.ScreenPadding - 12.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(
            selected = selected,
            onClick = onClick,
            colors = RadioButtonDefaults.colors(selectedColor = JamarrColors.Primary),
        )
        Column {
            Text(text = title, style = JamarrType.CardTitle, color = JamarrColors.Text)
            if (subtitle != null) {
                Text(text = subtitle, style = JamarrType.CaptionSmall, color = JamarrColors.Muted)
            }
        }
    }
}

@Composable
private fun StorageRow(label: String, bytes: Long?, actionLabel: String? = null, onAction: () -> Unit = {}) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = JamarrDims.ScreenPadding, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text = label, style = JamarrType.Body, color = JamarrColors.Text, modifier = Modifier.weight(1f))
        Text(
            text = bytes?.let(::formatStorage) ?: "…",
            style = JamarrType.Body,
            color = JamarrColors.Muted,
        )
        if (actionLabel != null) {
            Text(
                text = actionLabel,
                style = JamarrType.Caption,
                color = JamarrColors.Primary,
                modifier = Modifier
                    .padding(start = 12.dp)
                    .clickable(onClick = onAction)
                    .padding(4.dp),
            )
        }
    }
}

/** Like [formatBytes], but an empty cache reads as nothing rather than "1 MB". */
private fun formatStorage(bytes: Long): String = if (bytes <= 0L) "None" else formatBytes(bytes)
