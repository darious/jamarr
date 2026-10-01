package com.jamarr.android.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrType

/** One segment of a full-width tab strip (Favourites, Downloads). */
@Composable
fun SubTabButton(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val borderColor = if (selected) JamarrColors.Primary else JamarrColors.Border
    val bg = if (selected) JamarrColors.PrimaryTint else JamarrColors.Card
    val textColor = if (selected) JamarrColors.Primary else JamarrColors.Muted
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(10.dp))
            .border(BorderStroke(1.dp, borderColor), RoundedCornerShape(10.dp))
            .background(bg)
            .clickable(onClick = onClick)
            .padding(vertical = 9.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = label,
            style = JamarrType.Body,
            color = textColor,
            fontWeight = if (selected) FontWeight.W600 else FontWeight.W500,
        )
    }
}
