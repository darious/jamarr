package com.jamarr.android.ui.screens

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
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
import com.jamarr.android.data.ChartAlbum
import com.jamarr.android.ui.components.AlbumArt
import com.jamarr.android.ui.state.LocalJamarrContext
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrShapes
import com.jamarr.android.ui.theme.JamarrType

@Composable
fun ChartsScreen(
    onAlbumClick: (ChartAlbum) -> Unit,
    contentPadding: PaddingValues,
) {
    val ctx = LocalJamarrContext.current
    val chart = remember { mutableStateOf<List<ChartAlbum>>(emptyList()) }
    val error = remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        runCatching { ctx.apiClient.chart(ctx.serverUrl, ctx.accessToken) }
            .onSuccess { chart.value = it.sortedBy { a -> a.position } }
            .onFailure { error.value = it.message }
    }

    val entries = chart.value
    val top3 = entries.take(3)
    val rest = entries.drop(3)

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
                    Text("Charts", style = JamarrType.ScreenTitle, color = JamarrColors.Text)
                    Text(
                        text = "Top albums this week",
                        style = JamarrType.Caption,
                        color = JamarrColors.Muted,
                    )
                }
            }

            if (entries.isEmpty() && error.value != null) {
                item {
                    Text(
                        text = error.value.orEmpty(),
                        style = JamarrType.Body,
                        color = JamarrColors.Muted,
                        modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding),
                    )
                }
            }

            if (top3.isNotEmpty()) {
                item {
                    Podium(top3 = top3, onClick = onAlbumClick)
                }
            }

            items(rest, key = { it.position }) { entry ->
                ChartRow(entry = entry, onClick = { onAlbumClick(entry) })
            }
        }
    }
}

@Composable
private fun Podium(top3: List<ChartAlbum>, onClick: (ChartAlbum) -> Unit) {
    val first = top3.getOrNull(0)
    val second = top3.getOrNull(1)
    val third = top3.getOrNull(2)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = JamarrDims.ScreenPadding, vertical = 12.dp),
        verticalAlignment = Alignment.Bottom,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (second != null) {
            PodiumColumn(
                album = second,
                artSize = 64.dp,
                barHeight = 90.dp,
                highlighted = false,
                modifier = Modifier.weight(1f),
                onClick = onClick,
            )
        } else Spacer(Modifier.weight(1f))
        if (first != null) {
            PodiumColumn(
                album = first,
                artSize = 80.dp,
                barHeight = 110.dp,
                highlighted = true,
                modifier = Modifier.weight(1f),
                onClick = onClick,
            )
        } else Spacer(Modifier.weight(1f))
        if (third != null) {
            PodiumColumn(
                album = third,
                artSize = 64.dp,
                barHeight = 75.dp,
                highlighted = false,
                modifier = Modifier.weight(1f),
                onClick = onClick,
            )
        } else Spacer(Modifier.weight(1f))
    }
}

@Composable
private fun PodiumColumn(
    album: ChartAlbum,
    artSize: androidx.compose.ui.unit.Dp,
    barHeight: androidx.compose.ui.unit.Dp,
    highlighted: Boolean,
    modifier: Modifier = Modifier,
    onClick: (ChartAlbum) -> Unit,
) {
    val ctx = LocalJamarrContext.current
    val artUrl = ctx.artworkUrl(album.artSha1, 400)
    val borderModifier = if (highlighted) {
        Modifier.border(
            width = 2.dp,
            color = JamarrColors.Primary,
            shape = JamarrShapes.AlbumArt,
        )
    } else Modifier
    Column(
        modifier = modifier.clickable { onClick(album) },
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            modifier = Modifier
                .size(artSize)
                .clip(JamarrShapes.AlbumArt)
                .then(borderModifier),
        ) {
            AlbumArt(
                title = album.localTitle ?: album.title,
                seedName = (album.localTitle ?: album.title) + (album.localArtist ?: album.artist),
                artworkUrl = artUrl,
                modifier = Modifier.fillMaxSize(),
            )
        }
        Spacer(Modifier.height(6.dp))
        Text(
            text = "#${album.position}",
            style = JamarrType.StatValue,
            color = if (highlighted) JamarrColors.Primary else JamarrColors.Text,
        )
        Text(
            text = album.localTitle ?: album.title,
            style = JamarrType.CardTitle,
            color = JamarrColors.Text,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            textAlign = TextAlign.Center,
        )
        Text(
            text = album.localArtist ?: album.artist,
            style = JamarrType.CaptionSmall,
            color = JamarrColors.Muted,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(8.dp))
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(barHeight)
                .clip(RoundedCornerShape(topStart = 6.dp, topEnd = 6.dp))
                .background(if (highlighted) JamarrColors.Primary else JamarrColors.Card),
        )
    }
}

@Composable
private fun ChartRow(entry: ChartAlbum, onClick: () -> Unit) {
    val ctx = LocalJamarrContext.current
    val artUrl = ctx.artworkUrl(entry.artSha1, 200)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = JamarrDims.ScreenPadding, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(modifier = Modifier.width(32.dp), contentAlignment = Alignment.Center) {
            Text(
                text = entry.position.toString(),
                style = JamarrType.CardTitle,
                color = JamarrColors.Muted,
                textAlign = TextAlign.Center,
            )
        }
        Spacer(Modifier.width(8.dp))
        Box(
            modifier = Modifier
                .size(44.dp)
                .clip(JamarrShapes.AlbumArt),
        ) {
            AlbumArt(
                title = entry.localTitle ?: entry.title,
                seedName = (entry.localTitle ?: entry.title) + (entry.localArtist ?: entry.artist),
                artworkUrl = artUrl,
                modifier = Modifier.fillMaxSize(),
            )
        }
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = entry.localTitle ?: entry.title,
                style = JamarrType.CardTitle,
                color = JamarrColors.Text,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = entry.localArtist ?: entry.artist,
                style = JamarrType.CaptionSmall,
                color = JamarrColors.Muted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.width(8.dp))
        ChartChange(entry)
    }
}

@Composable
private fun ChartChange(entry: ChartAlbum) {
    val (symbol, tint) = changeIndicator(entry)
    Text(
        text = symbol,
        style = JamarrType.Caption,
        color = tint,
    )
}

private fun changeIndicator(entry: ChartAlbum): Pair<String, Color> {
    val lastWeek = entry.lastWeek?.trim()
    if (lastWeek.isNullOrBlank() || lastWeek.equals("NEW", ignoreCase = true) || lastWeek == "-") {
        return "NEW" to JamarrColors.Primary
    }
    val last = lastWeek.toIntOrNull() ?: return "—" to JamarrColors.Neutral
    return when {
        last > entry.position -> "▲ ${last - entry.position}" to JamarrColors.Tertiary
        last < entry.position -> "▼ ${entry.position - last}" to JamarrColors.Muted
        else -> "—" to JamarrColors.Neutral
    }
}
