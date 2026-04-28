package com.jamarr.android.ui.components

import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalConfiguration

@Composable
fun isWide(): Boolean {
    val cfg = LocalConfiguration.current
    return cfg.smallestScreenWidthDp >= 600 || cfg.screenWidthDp >= 720
}
