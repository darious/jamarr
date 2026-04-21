package com.jamarr.android.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import coil3.compose.AsyncImage

@Composable
fun PlaylistCover(
    title: String,
    seedName: String,
    thumbnails: List<String>,
    artworkUrlFor: (String) -> String?,
    modifier: Modifier = Modifier,
) {
    val thumbs = thumbnails.filter { it.isNotBlank() }.take(4)
    Box(modifier = modifier.background(gradientFor(seedName))) {
        when {
            thumbs.size >= 4 -> {
                Column(modifier = Modifier.fillMaxSize()) {
                    Row(modifier = Modifier.weight(1f).fillMaxWidth()) {
                        TileImage(thumbs[0], artworkUrlFor, modifier = Modifier.weight(1f).fillMaxHeight())
                        TileImage(thumbs[1], artworkUrlFor, modifier = Modifier.weight(1f).fillMaxHeight())
                    }
                    Row(modifier = Modifier.weight(1f).fillMaxWidth()) {
                        TileImage(thumbs[2], artworkUrlFor, modifier = Modifier.weight(1f).fillMaxHeight())
                        TileImage(thumbs[3], artworkUrlFor, modifier = Modifier.weight(1f).fillMaxHeight())
                    }
                }
            }
            thumbs.isNotEmpty() -> {
                AsyncImage(
                    model = artworkUrlFor(thumbs.first()),
                    contentDescription = title,
                    modifier = Modifier.fillMaxSize(),
                )
            }
            else -> {
                AlbumArt(
                    title = title,
                    seedName = seedName,
                    artworkUrl = null,
                    modifier = Modifier.fillMaxSize(),
                )
            }
        }
    }
}

@Composable
private fun TileImage(
    thumb: String,
    artworkUrlFor: (String) -> String?,
    modifier: Modifier = Modifier,
) {
    AsyncImage(
        model = artworkUrlFor(thumb),
        contentDescription = null,
        modifier = modifier,
    )
}
