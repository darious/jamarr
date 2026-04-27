package com.jamarr.android.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.jamarr.android.data.PlaylistSummary
import com.jamarr.android.ui.components.PlaylistCover
import com.jamarr.android.ui.components.RefreshIcon
import com.jamarr.android.ui.components.seedColor
import com.jamarr.android.ui.state.LocalJamarrContext
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrShapes
import com.jamarr.android.ui.theme.JamarrType
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.time.temporal.ChronoUnit

@Composable
fun PlaylistsScreen(
    onPlaylistClick: (Long) -> Unit,
    contentPadding: PaddingValues,
) {
    val ctx = LocalJamarrContext.current
    val playlists = remember { mutableStateOf<List<PlaylistSummary>>(emptyList()) }
    val error = remember { mutableStateOf<String?>(null) }
    val refreshTick = remember { mutableStateOf(0) }
    val isRefreshing = remember { mutableStateOf(false) }

    LaunchedEffect(refreshTick.value) {
        if (refreshTick.value > 0) isRefreshing.value = true
        runCatching { ctx.apiClient.playlists(ctx.serverUrl, ctx.accessToken) }
            .onSuccess { playlists.value = it }
            .onFailure { error.value = it.message }
        isRefreshing.value = false
    }

    Box(modifier = Modifier.fillMaxSize().background(JamarrColors.Bg)) {
        PullToRefreshBox(
            isRefreshing = isRefreshing.value,
            onRefresh = { refreshTick.value += 1 },
            modifier = Modifier.fillMaxSize(),
        ) {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(
                    bottom = contentPadding.calculateBottomPadding() + 16.dp,
                ),
            ) {
            item {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .statusBarsPadding()
                        .padding(
                            horizontal = JamarrDims.ScreenPadding,
                            vertical = 16.dp,
                        ),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Text("Playlists", style = JamarrType.ScreenTitle, color = JamarrColors.Text)
                        Text(
                            text = "${playlists.value.size} playlist${if (playlists.value.size == 1) "" else "s"}",
                            style = JamarrType.Caption,
                            color = JamarrColors.Muted,
                        )
                    }
                }
            }
            if (playlists.value.isEmpty() && error.value != null) {
                item {
                    Text(
                        text = error.value.orEmpty(),
                        style = JamarrType.Body,
                        color = JamarrColors.Muted,
                        modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding),
                    )
                }
            }
            items(playlists.value, key = { it.id }) { pl ->
                PlaylistRow(pl) { onPlaylistClick(pl.id) }
            }
        }
    }
    }
}

@Composable
private fun PlaylistRow(pl: PlaylistSummary, onClick: () -> Unit) {
    val ctx = LocalJamarrContext.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = JamarrDims.ScreenPadding, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        PlaylistCover(
            title = pl.name,
            seedName = pl.name,
            thumbnails = pl.thumbnails,
            artworkUrlFor = { sha -> ctx.artworkUrl(sha, 200) },
            modifier = Modifier
                .size(54.dp)
                .clip(JamarrShapes.AlbumArt),
        )
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = pl.name,
                style = JamarrType.CardTitle,
                color = JamarrColors.Text,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = listOf(
                    "${pl.trackCount} track${if (pl.trackCount == 1) "" else "s"}",
                    formatUpdatedAt(pl.updatedAt),
                ).filter { it.isNotBlank() }.joinToString(" · "),
                style = JamarrType.CaptionSmall,
                color = JamarrColors.Muted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.width(8.dp))
        Text(
            text = "›",
            color = JamarrColors.Neutral,
            style = JamarrType.CardTitle,
        )
    }
}

private fun formatUpdatedAt(raw: String?): String {
    if (raw.isNullOrBlank()) return ""
    val date = runCatching { OffsetDateTime.parse(raw).toLocalDate() }
        .recoverCatching { LocalDate.parse(raw) }
        .getOrNull() ?: return ""
    val today = LocalDate.now()
    val days = ChronoUnit.DAYS.between(date, today)
    return when {
        days <= 0L -> "Today"
        days == 1L -> "Yesterday"
        days < 7L -> "$days days ago"
        else -> runCatching {
            date.format(DateTimeFormatter.ofPattern("d MMM"))
        }.getOrDefault("")
    }
}
