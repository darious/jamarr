package com.jamarr.android.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrType

@Composable
fun PlaceholderScreen(title: String, subtitle: String) {
    Box(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .padding(JamarrDims.ScreenPadding),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(text = title, style = JamarrType.ScreenTitle, color = JamarrColors.Text)
            Text(text = subtitle, style = JamarrType.Body, color = JamarrColors.Muted)
        }
        Text(
            text = "Coming soon",
            style = JamarrType.Body,
            color = JamarrColors.Muted,
            modifier = Modifier.align(Alignment.Center),
        )
    }
}
