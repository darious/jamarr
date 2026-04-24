package com.jamarr.android.ui.nav

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.jamarr.android.ui.components.ChartsIcon
import com.jamarr.android.ui.components.HeartIcon
import com.jamarr.android.ui.components.HistoryIcon
import com.jamarr.android.ui.components.HomeIcon
import com.jamarr.android.ui.components.PlaylistIcon
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrType

@Composable
fun BottomNavBar(
    selected: JamarrTab,
    onSelect: (JamarrTab) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(JamarrColors.Surface)
            .navigationBarsPadding()
            .height(64.dp),
        horizontalArrangement = Arrangement.SpaceAround,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        JamarrTab.entries.forEach { tab ->
            NavItem(
                tab = tab,
                active = tab == selected,
                onClick = { onSelect(tab) },
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun NavItem(
    tab: JamarrTab,
    active: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val tint = if (active) JamarrColors.Primary else JamarrColors.Muted
    Column(
        modifier = modifier
            .clickable(onClick = onClick)
            .padding(vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Box(modifier = Modifier.size(24.dp), contentAlignment = Alignment.Center) {
            when (tab) {
                JamarrTab.Home -> HomeIcon(tint = tint)
                JamarrTab.Favourites -> HeartIcon(tint = tint, filled = active, size = 22.dp)
                JamarrTab.Playlists -> PlaylistIcon(tint = tint)
                JamarrTab.Charts -> ChartsIcon(tint = tint)
                JamarrTab.History -> HistoryIcon(tint = tint)
            }
        }
        Text(
            text = tab.title,
            style = JamarrType.CaptionSmall,
            color = tint,
        )
    }
}
