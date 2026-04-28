package com.jamarr.android.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.media3.common.Player
import com.jamarr.android.data.SearchTrack
import com.jamarr.android.playback.ResolvedTrack
import com.jamarr.android.ui.components.AlbumArt
import com.jamarr.android.ui.components.CastIcon
import com.jamarr.android.ui.components.ChevronDownIcon
import com.jamarr.android.ui.components.PauseIcon
import com.jamarr.android.ui.components.PlayIcon
import com.jamarr.android.ui.components.QueueIcon
import com.jamarr.android.ui.components.RepeatIcon
import com.jamarr.android.ui.components.RepeatOneIcon
import com.jamarr.android.ui.components.ShuffleIcon
import com.jamarr.android.ui.components.SkipNextIcon
import com.jamarr.android.ui.components.SkipPreviousIcon
import com.jamarr.android.ui.components.isWide
import com.jamarr.android.ui.components.seedColor
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrShapes
import com.jamarr.android.ui.theme.JamarrType
import com.jamarr.android.util.formatMs

@Composable
fun NowPlayingSheet(
    visible: Boolean,
    track: SearchTrack,
    artworkUrl: String?,
    isPlaying: Boolean,
    progressMs: Long,
    durationMs: Long,
    shuffleEnabled: Boolean,
    repeatMode: Int,
    queue: List<ResolvedTrack>,
    onDismiss: () -> Unit,
    onToggle: () -> Unit,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
    onSeek: (Long) -> Unit,
    onShuffle: () -> Unit,
    onRepeat: () -> Unit,
    onQueueItemClick: (Int) -> Unit,
    onArtistClick: (String) -> Unit,
    rendererName: String = "This Device",
    onRendererClick: () -> Unit = {},
) {
    AnimatedVisibility(
        visible = visible,
        enter = slideInVertically(
            initialOffsetY = { it },
            animationSpec = tween(350),
        ),
        exit = slideOutVertically(
            targetOffsetY = { it },
            animationSpec = tween(300),
        ),
    ) {
        var showQueue by remember { mutableStateOf(false) }

        val bgColor = seedColor(track.album ?: track.title)

        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        listOf(bgColor, JamarrColors.Bg, JamarrColors.Bg),
                    ),
                ),
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .statusBarsPadding()
                    .navigationBarsPadding(),
            ) {
                // Top bar: chevron + queue toggle
                TopBar(
                    showQueue = showQueue,
                    rendererName = rendererName,
                    onDismiss = onDismiss,
                    onToggleQueue = { showQueue = !showQueue },
                    onRendererClick = onRendererClick,
                )

                if (isWide() && !showQueue) {
                    Row(
                        modifier = Modifier.weight(1f).fillMaxWidth().padding(horizontal = 48.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(48.dp, Alignment.CenterHorizontally),
                    ) {
                        ArtworkPane(
                            track = track,
                            artworkUrl = artworkUrl,
                            isPlaying = isPlaying,
                            modifier = Modifier.fillMaxHeight().aspectRatio(1f),
                        )
                        Column(
                            modifier = Modifier
                                .widthIn(max = 672.dp)
                                .weight(1f)
                                .fillMaxHeight(),
                            verticalArrangement = Arrangement.Center,
                            horizontalAlignment = Alignment.CenterHorizontally,
                        ) {
                            TrackInfo(track = track, onArtistClick = onArtistClick)
                            Spacer(Modifier.height(28.dp))
                            ScrubBar(
                                progressMs = progressMs,
                                durationMs = durationMs,
                                onSeek = onSeek,
                                horizontalPadding = 0.dp,
                            )
                            TransportControls(
                                isPlaying = isPlaying,
                                shuffleEnabled = shuffleEnabled,
                                repeatMode = repeatMode,
                                onToggle = onToggle,
                                onPrevious = onPrevious,
                                onNext = onNext,
                                onShuffle = onShuffle,
                                onRepeat = onRepeat,
                                horizontalPadding = 0.dp,
                            )
                        }
                    }
                    Spacer(Modifier.height(24.dp))
                } else {
                    if (showQueue) {
                        QueueView(
                            queue = queue,
                            currentTrackId = track.id,
                            onItemClick = onQueueItemClick,
                            modifier = Modifier.weight(1f),
                        )
                    } else {
                        ArtworkView(
                            track = track,
                            artworkUrl = artworkUrl,
                            isPlaying = isPlaying,
                            onArtistClick = onArtistClick,
                            modifier = Modifier.weight(1f),
                        )
                    }

                    // Progress bar
                    ScrubBar(
                        progressMs = progressMs,
                        durationMs = durationMs,
                        onSeek = onSeek,
                    )

                    // Transport controls
                    TransportControls(
                        isPlaying = isPlaying,
                        shuffleEnabled = shuffleEnabled,
                        repeatMode = repeatMode,
                        onToggle = onToggle,
                        onPrevious = onPrevious,
                        onNext = onNext,
                        onShuffle = onShuffle,
                        onRepeat = onRepeat,
                    )

                    Spacer(Modifier.height(24.dp))
                }
            }
        }
    }
}

@Composable
private fun TopBar(
    showQueue: Boolean,
    rendererName: String,
    onDismiss: () -> Unit,
    onToggleQueue: () -> Unit,
    onRendererClick: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 8.dp, vertical = 4.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .clip(CircleShape)
                    .clickable(onClick = onDismiss),
                contentAlignment = Alignment.Center,
            ) {
                ChevronDownIcon(tint = JamarrColors.Text, size = 24.dp)
            }
            Spacer(Modifier.weight(1f))
            Text(
                text = if (showQueue) "Queue" else "Now Playing",
                style = JamarrType.SectionHeader,
                color = JamarrColors.Text,
            )
            Spacer(Modifier.weight(1f))
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .clip(CircleShape)
                    .clickable(onClick = onRendererClick),
                contentAlignment = Alignment.Center,
            ) {
                CastIcon(
                    tint = JamarrColors.Muted,
                    size = 20.dp,
                )
            }
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .clip(CircleShape)
                    .clickable(onClick = onToggleQueue),
                contentAlignment = Alignment.Center,
            ) {
                QueueIcon(
                    tint = if (showQueue) JamarrColors.Primary else JamarrColors.Text,
                    size = 22.dp,
                )
            }
        }
        Text(
            text = rendererName,
            style = JamarrType.CaptionSmall,
            color = JamarrColors.Muted,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 56.dp, bottom = 4.dp),
        )
    }
}

@Composable
private fun ArtworkView(
    track: SearchTrack,
    artworkUrl: String?,
    isPlaying: Boolean,
    onArtistClick: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val artScale by animateFloatAsState(
        targetValue = if (isPlaying) 1f else 0.88f,
        animationSpec = tween(400),
        label = "art-scale",
    )

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        // Album art (capped so controls always have room)
        Box(
            modifier = Modifier
                .widthIn(max = 360.dp)
                .fillMaxWidth()
                .aspectRatio(1f)
                .scale(artScale)
                .clip(JamarrShapes.AlbumArtLarge)
                .background(JamarrColors.Card),
        ) {
            AlbumArt(
                title = track.title,
                seedName = track.album ?: track.title,
                artworkUrl = artworkUrl,
                modifier = Modifier.fillMaxSize(),
            )
        }

        Spacer(Modifier.height(28.dp))

        // Track title
        Text(
            text = track.title,
            style = JamarrType.AlbumHeroTitle,
            color = JamarrColors.Text,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.fillMaxWidth(),
        )

        Spacer(Modifier.height(4.dp))

        // Artist name (tappable)
        val artist = track.artist
        if (!artist.isNullOrBlank()) {
            Text(
                text = artist,
                style = JamarrType.ArtistLink,
                color = JamarrColors.Primary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onArtistClick(artist) },
            )
        }

        // Album name
        val album = track.album
        if (!album.isNullOrBlank()) {
            Spacer(Modifier.height(2.dp))
            Text(
                text = album,
                style = JamarrType.Caption,
                color = JamarrColors.Muted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun ArtworkPane(
    track: SearchTrack,
    artworkUrl: String?,
    isPlaying: Boolean,
    modifier: Modifier = Modifier,
) {
    val artScale by animateFloatAsState(
        targetValue = if (isPlaying) 1f else 0.88f,
        animationSpec = tween(400),
        label = "art-scale-wide",
    )
    Box(
        modifier = modifier
            .scale(artScale)
            .clip(JamarrShapes.AlbumArtLarge)
            .background(JamarrColors.Card),
    ) {
        AlbumArt(
            title = track.title,
            seedName = track.album ?: track.title,
            artworkUrl = artworkUrl,
            modifier = Modifier.fillMaxSize(),
        )
    }
}

@Composable
private fun TrackInfo(
    track: SearchTrack,
    onArtistClick: (String) -> Unit,
) {
    Text(
        text = track.title,
        style = JamarrType.AlbumHeroTitle,
        color = JamarrColors.Text,
        maxLines = 2,
        overflow = TextOverflow.Ellipsis,
        modifier = Modifier.fillMaxWidth(),
    )
    Spacer(Modifier.height(4.dp))
    val artist = track.artist
    if (!artist.isNullOrBlank()) {
        Text(
            text = artist,
            style = JamarrType.ArtistLink,
            color = JamarrColors.Primary,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier
                .fillMaxWidth()
                .clickable { onArtistClick(artist) },
        )
    }
    val album = track.album
    if (!album.isNullOrBlank()) {
        Spacer(Modifier.height(2.dp))
        Text(
            text = album,
            style = JamarrType.Caption,
            color = JamarrColors.Muted,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun ScrubBar(
    progressMs: Long,
    durationMs: Long,
    onSeek: (Long) -> Unit,
    horizontalPadding: androidx.compose.ui.unit.Dp = 32.dp,
) {
    val fraction = if (durationMs > 0) {
        (progressMs.toFloat() / durationMs).coerceIn(0f, 1f)
    } else 0f

    var scrubbing by remember { mutableStateOf(false) }
    var scrubFraction by remember { mutableStateOf(0f) }
    val displayFraction = if (scrubbing) scrubFraction else fraction

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = horizontalPadding),
    ) {
        // Scrub track
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(32.dp)
                .pointerInput(durationMs) {
                    detectTapGestures { offset ->
                        if (durationMs > 0) {
                            val f = (offset.x / size.width.toFloat()).coerceIn(0f, 1f)
                            onSeek((f * durationMs).toLong())
                        }
                    }
                }
                .pointerInput(durationMs) {
                    detectHorizontalDragGestures(
                        onDragStart = { offset ->
                            scrubbing = true
                            scrubFraction = (offset.x / size.width.toFloat()).coerceIn(0f, 1f)
                        },
                        onDragEnd = {
                            if (durationMs > 0) onSeek((scrubFraction * durationMs).toLong())
                            scrubbing = false
                        },
                        onDragCancel = { scrubbing = false },
                        onHorizontalDrag = { _, dragAmount ->
                            scrubFraction = (scrubFraction + dragAmount / size.width.toFloat()).coerceIn(0f, 1f)
                        },
                    )
                },
            contentAlignment = Alignment.CenterStart,
        ) {
            // Track bg
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(4.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(JamarrColors.Border),
            )
            // Filled
            if (displayFraction > 0f) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth(displayFraction)
                        .height(4.dp)
                        .clip(RoundedCornerShape(2.dp))
                        .background(JamarrColors.Primary),
                )
            }
            // Thumb
            Box(
                modifier = Modifier
                    .fillMaxWidth(displayFraction)
                    .padding(start = 0.dp),
            ) {
                Box(
                    modifier = Modifier
                        .size(12.dp)
                        .clip(CircleShape)
                        .background(JamarrColors.Primary)
                        .align(Alignment.CenterEnd),
                )
            }
        }

        // Time labels
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            val displayMs = if (scrubbing) (scrubFraction * durationMs).toLong() else progressMs
            Text(
                text = formatMs(displayMs),
                style = JamarrType.CaptionSmall,
                color = JamarrColors.Muted,
            )
            Text(
                text = "-${formatMs((durationMs - displayMs).coerceAtLeast(0))}",
                style = JamarrType.CaptionSmall,
                color = JamarrColors.Muted,
            )
        }
    }
}

@Composable
private fun TransportControls(
    isPlaying: Boolean,
    shuffleEnabled: Boolean,
    repeatMode: Int,
    onToggle: () -> Unit,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
    onShuffle: () -> Unit,
    onRepeat: () -> Unit,
    horizontalPadding: androidx.compose.ui.unit.Dp = 32.dp,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = horizontalPadding, vertical = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceEvenly,
    ) {
        // Shuffle
        Box(
            modifier = Modifier
                .size(44.dp)
                .clip(CircleShape)
                .clickable(onClick = onShuffle),
            contentAlignment = Alignment.Center,
        ) {
            ShuffleIcon(
                tint = if (shuffleEnabled) JamarrColors.Primary else JamarrColors.Muted,
                size = 22.dp,
            )
        }

        // Previous
        Box(
            modifier = Modifier
                .size(52.dp)
                .clip(CircleShape)
                .clickable(onClick = onPrevious),
            contentAlignment = Alignment.Center,
        ) {
            SkipPreviousIcon(tint = JamarrColors.Text, size = 26.dp)
        }

        // Play/Pause (primary, 64px)
        Box(
            modifier = Modifier
                .size(64.dp)
                .clip(CircleShape)
                .background(JamarrColors.Primary)
                .clickable(onClick = onToggle),
            contentAlignment = Alignment.Center,
        ) {
            if (isPlaying) {
                PauseIcon(tint = Color.White, size = 28.dp)
            } else {
                PlayIcon(tint = Color.White, size = 28.dp)
            }
        }

        // Next
        Box(
            modifier = Modifier
                .size(52.dp)
                .clip(CircleShape)
                .clickable(onClick = onNext),
            contentAlignment = Alignment.Center,
        ) {
            SkipNextIcon(tint = JamarrColors.Text, size = 26.dp)
        }

        // Repeat
        Box(
            modifier = Modifier
                .size(44.dp)
                .clip(CircleShape)
                .clickable(onClick = onRepeat),
            contentAlignment = Alignment.Center,
        ) {
            when (repeatMode) {
                Player.REPEAT_MODE_ALL -> RepeatIcon(
                    tint = JamarrColors.Primary,
                    size = 22.dp,
                )
                Player.REPEAT_MODE_ONE -> RepeatOneIcon(
                    tint = JamarrColors.Primary,
                    size = 22.dp,
                )
                else -> RepeatIcon(tint = JamarrColors.Muted, size = 22.dp)
            }
        }
    }
}

@Composable
private fun QueueView(
    queue: List<ResolvedTrack>,
    currentTrackId: Long,
    onItemClick: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    val currentIndex = queue.indexOfFirst { it.track.id == currentTrackId }.coerceAtLeast(0)
    val listState = rememberLazyListState()

    LaunchedEffect(currentIndex) {
        if (currentIndex > 0) {
            listState.animateScrollToItem((currentIndex - 1).coerceAtLeast(0))
        }
    }

    LazyColumn(
        modifier = modifier.fillMaxWidth(),
        state = listState,
        contentPadding = PaddingValues(vertical = 8.dp),
    ) {
        itemsIndexed(queue, key = { i, rt -> "q-$i-${rt.track.id}" }) { index, rt ->
            val isCurrent = rt.track.id == currentTrackId
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(if (isCurrent) JamarrColors.PrimaryTint else Color.Transparent)
                    .clickable { onItemClick(index) }
                    .padding(horizontal = JamarrDims.ScreenPadding, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    modifier = Modifier
                        .size(40.dp)
                        .clip(JamarrShapes.AlbumArt)
                        .background(JamarrColors.Card),
                ) {
                    AlbumArt(
                        title = rt.track.title,
                        seedName = rt.track.album ?: rt.track.title,
                        artworkUrl = rt.artworkUrl,
                        modifier = Modifier.fillMaxSize(),
                    )
                }
                Spacer(Modifier.width(12.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = rt.track.title,
                        style = JamarrType.CardTitle,
                        color = if (isCurrent) JamarrColors.Primary else JamarrColors.Text,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    val artist = rt.track.artist
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
            }
        }
    }
}

