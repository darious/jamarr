package com.jamarr.android.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.jamarr.android.data.OnlineState
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrType

/**
 * Stands in for a tab that only the server can fill (Favourites, Playlists,
 * Charts, History) while offline, instead of a spinner or an error that never
 * resolves. Points at the downloads, which do work.
 */
@Composable
fun OfflinePlaceholder(
    title: String,
    onlineState: OnlineState,
    onGoOnline: () -> Unit,
    onOpenDownloads: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(JamarrColors.Bg)
            .statusBarsPadding()
            .padding(vertical = 12.dp),
    ) {
        Text(
            text = title,
            style = JamarrType.ScreenTitle,
            color = JamarrColors.Text,
            modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding),
        )
        Spacer(Modifier.height(12.dp))
        OfflineBanner(onlineState = onlineState, onGoOnline = onGoOnline)
        Text(
            text = "$title needs the server. Your downloads are still here.",
            style = JamarrType.Body,
            color = JamarrColors.Muted,
            modifier = Modifier.padding(JamarrDims.ScreenPadding),
        )
        Text(
            text = "Open downloads",
            style = JamarrType.CardTitle,
            color = JamarrColors.Primary,
            modifier = Modifier
                .padding(horizontal = JamarrDims.ScreenPadding)
                .clickable(onClick = onOpenDownloads)
                .padding(vertical = 8.dp),
        )
    }
}
