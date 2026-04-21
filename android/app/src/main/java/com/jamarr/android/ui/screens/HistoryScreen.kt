package com.jamarr.android.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.jamarr.android.data.HistoryStats
import com.jamarr.android.ui.components.AlbumArt
import com.jamarr.android.ui.state.LocalJamarrContext
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrShapes
import com.jamarr.android.ui.theme.JamarrType
import java.time.LocalDate
import java.time.format.DateTimeFormatter

private enum class HistoryRange(val label: String, val days: Long?) {
    Today("Today", 0),
    Last7("Last 7 days", 7),
    Last30("Last 30 days", 30),
    All("All time", null),
}

private enum class HistoryTab(val label: String) {
    Tracks("Tracks"),
    Albums("Albums"),
    Artists("Artists"),
}

@Composable
fun HistoryScreen(
    onArtistClick: (mbid: String?, name: String) -> Unit,
    onAlbumClick: (albumMbid: String?, title: String, artist: String) -> Unit,
    onTrackClick: (Long) -> Unit,
    contentPadding: PaddingValues,
) {
    val ctx = LocalJamarrContext.current
    val range = remember { mutableStateOf(HistoryRange.Last30) }
    val tab = remember { mutableStateOf(HistoryTab.Tracks) }
    val stats = remember { mutableStateOf(HistoryStats()) }
    val error = remember { mutableStateOf<String?>(null) }

    LaunchedEffect(range.value) {
        val (from, to) = dateRangeBounds(range.value)
        runCatching {
            ctx.apiClient.historyStats(
                serverUrl = ctx.serverUrl,
                accessToken = ctx.accessToken,
                from = from,
                to = to,
                scope = "mine",
            )
        }
            .onSuccess { stats.value = it }
            .onFailure { error.value = it.message }
    }

    Box(modifier = Modifier.fillMaxSize().background(JamarrColors.Bg)) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                bottom = contentPadding.calculateBottomPadding() + 16.dp,
            ),
        ) {
            item {
                Column(
                    modifier = Modifier
                        .statusBarsPadding()
                        .padding(horizontal = JamarrDims.ScreenPadding, vertical = 16.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text("History", style = JamarrType.ScreenTitle, color = JamarrColors.Text)
                    Text(
                        text = "What you've been listening to",
                        style = JamarrType.Caption,
                        color = JamarrColors.Muted,
                    )
                }
            }

            item {
                RangePills(selected = range.value, onSelect = { range.value = it })
            }
            item {
                StatsSummary(stats = stats.value)
            }
            item {
                TabPills(selected = tab.value, onSelect = { tab.value = it })
            }

            when (tab.value) {
                HistoryTab.Tracks -> {
                    val tracks = stats.value.tracks
                    val maxPlays = tracks.maxOfOrNull { it.plays }?.coerceAtLeast(1) ?: 1
                    items(tracks.withIndex().toList(), key = { "t-${it.value.id ?: it.index}" }) { (index, t) ->
                        HistoryRow(
                            rank = index + 1,
                            title = t.displayTitle,
                            subtitle = t.artist,
                            plays = t.plays,
                            playsMax = maxPlays,
                            artworkUrl = ctx.artworkUrl(t.artSha1, 200),
                            seed = t.displayTitle + t.artist.orEmpty(),
                            circleArt = false,
                            onClick = {
                                t.id?.let { onTrackClick(it) }
                            },
                        )
                    }
                }
                HistoryTab.Albums -> {
                    val albums = stats.value.albums
                    val maxPlays = albums.maxOfOrNull { it.plays }?.coerceAtLeast(1) ?: 1
                    items(albums.withIndex().toList(), key = { "a-${it.value.displayTitle}-${it.index}" }) { (index, a) ->
                        HistoryRow(
                            rank = index + 1,
                            title = a.displayTitle,
                            subtitle = a.artist,
                            plays = a.plays,
                            playsMax = maxPlays,
                            artworkUrl = ctx.artworkUrl(a.artSha1, 200),
                            seed = a.displayTitle + a.artist.orEmpty(),
                            circleArt = false,
                            onClick = {
                                onAlbumClick(a.mbReleaseId, a.displayTitle, a.artist.orEmpty())
                            },
                        )
                    }
                }
                HistoryTab.Artists -> {
                    val artists = stats.value.artists
                    val maxPlays = artists.maxOfOrNull { it.plays }?.coerceAtLeast(1) ?: 1
                    items(artists.withIndex().toList(), key = { "ar-${it.value.displayName}-${it.index}" }) { (index, a) ->
                        HistoryRow(
                            rank = index + 1,
                            title = a.displayName,
                            subtitle = null,
                            plays = a.plays,
                            playsMax = maxPlays,
                            artworkUrl = ctx.artworkUrl(a.artSha1, 200),
                            seed = a.displayName,
                            circleArt = true,
                            onClick = {
                                onArtistClick(a.resolvedMbid, a.displayName)
                            },
                        )
                    }
                }
            }

            if (error.value != null) {
                item {
                    Text(
                        text = error.value.orEmpty(),
                        style = JamarrType.Body,
                        color = JamarrColors.Muted,
                        modifier = Modifier.padding(JamarrDims.ScreenPadding),
                    )
                }
            }
        }
    }
}

@Composable
private fun RangePills(selected: HistoryRange, onSelect: (HistoryRange) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = JamarrDims.ScreenPadding),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        HistoryRange.values().forEach { range ->
            Pill(
                label = range.label,
                selected = range == selected,
                onClick = { onSelect(range) },
            )
        }
    }
}

@Composable
private fun TabPills(selected: HistoryTab, onSelect: (HistoryTab) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = JamarrDims.ScreenPadding, vertical = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        HistoryTab.values().forEach { tab ->
            Pill(
                label = tab.label,
                selected = tab == selected,
                onClick = { onSelect(tab) },
            )
        }
    }
}

@Composable
private fun Pill(label: String, selected: Boolean, onClick: () -> Unit) {
    val bg = if (selected) JamarrColors.Primary else Color.Transparent
    val textColor = if (selected) Color.White else JamarrColors.Text
    val borderColor = if (selected) JamarrColors.Primary else JamarrColors.Border
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(20.dp))
            .border(BorderStroke(1.dp, borderColor), RoundedCornerShape(20.dp))
            .background(bg)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 8.dp),
    ) {
        Text(text = label, style = JamarrType.Caption, color = textColor)
    }
}

@Composable
private fun StatsSummary(stats: HistoryStats) {
    val trackPlays = stats.tracks.sumOf { it.plays }
    val albumCount = stats.albums.size
    val artistCount = stats.artists.size
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = JamarrDims.ScreenPadding, vertical = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        StatCard(label = "Plays", value = trackPlays.toString(), modifier = Modifier.weight(1f))
        StatCard(label = "Albums", value = albumCount.toString(), modifier = Modifier.weight(1f))
        StatCard(label = "Artists", value = artistCount.toString(), modifier = Modifier.weight(1f))
    }
}

@Composable
private fun StatCard(label: String, value: String, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .clip(JamarrShapes.Card)
            .background(JamarrColors.Card)
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(text = value, style = JamarrType.StatValue, color = JamarrColors.Text)
        Text(text = label, style = JamarrType.CaptionSmall, color = JamarrColors.Muted)
    }
}

@Composable
private fun HistoryRow(
    rank: Int,
    title: String,
    subtitle: String?,
    plays: Int,
    playsMax: Int,
    artworkUrl: String?,
    seed: String,
    circleArt: Boolean,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = JamarrDims.ScreenPadding, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(modifier = Modifier.width(28.dp), contentAlignment = Alignment.Center) {
            Text(
                text = rank.toString(),
                style = JamarrType.TrackNumber,
                color = JamarrColors.Neutral,
                textAlign = TextAlign.Center,
            )
        }
        Spacer(Modifier.width(8.dp))
        Box(
            modifier = Modifier
                .size(44.dp)
                .clip(if (circleArt) CircleShape else JamarrShapes.AlbumArt),
        ) {
            AlbumArt(
                title = title,
                seedName = seed,
                artworkUrl = artworkUrl,
                modifier = Modifier.fillMaxSize(),
            )
        }
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = title,
                style = JamarrType.CardTitle,
                color = JamarrColors.Text,
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
            Spacer(Modifier.height(4.dp))
            PlaysBar(plays = plays, playsMax = playsMax)
        }
        Spacer(Modifier.width(10.dp))
        Text(
            text = plays.toString(),
            style = JamarrType.CardTitle,
            color = JamarrColors.Primary,
        )
    }
}

@Composable
private fun PlaysBar(plays: Int, playsMax: Int) {
    val fraction = (plays.toFloat() / playsMax.toFloat()).coerceIn(0f, 1f)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(3.dp)
            .clip(RoundedCornerShape(2.dp))
            .background(JamarrColors.Border),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth(fraction)
                .fillMaxHeight()
                .background(JamarrColors.Primary),
        )
    }
}

private fun dateRangeBounds(range: HistoryRange): Pair<String?, String?> {
    val today = LocalDate.now()
    val fmt = DateTimeFormatter.ISO_LOCAL_DATE
    return when (range) {
        HistoryRange.All -> null to null
        HistoryRange.Today -> today.format(fmt) to today.format(fmt)
        HistoryRange.Last7 -> today.minusDays(6).format(fmt) to today.format(fmt)
        HistoryRange.Last30 -> today.minusDays(29).format(fmt) to today.format(fmt)
    }
}
