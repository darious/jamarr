package com.jamarr.android.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrType

@Composable
fun PlayShuffleActions(
    onPlay: () -> Unit,
    onShuffle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(
            modifier = Modifier
                .size(48.dp)
                .clip(CircleShape)
                .background(JamarrColors.Primary)
                .clickable(onClick = onPlay),
            contentAlignment = Alignment.Center,
        ) {
            PlayIcon(tint = Color.White, size = 22.dp)
        }
        Box(
            modifier = Modifier
                .height(1.dp)
                .width(24.dp)
                .background(JamarrColors.Border),
        )
        Row(
            modifier = Modifier
                .clip(RoundedCornerShape(24.dp))
                .border(BorderStroke(1.dp, JamarrColors.Border), RoundedCornerShape(24.dp))
                .clickable(onClick = onShuffle)
                .padding(horizontal = 18.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = "Shuffle",
                style = JamarrType.CardTitle,
                color = JamarrColors.Text,
            )
        }
    }
}
