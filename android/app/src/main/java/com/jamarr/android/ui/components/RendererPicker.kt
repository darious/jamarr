package com.jamarr.android.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.jamarr.android.data.Renderer
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrShapes
import com.jamarr.android.ui.theme.JamarrType

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RendererPicker(
    visible: Boolean,
    renderers: List<Renderer>,
    activeUdn: String,
    onDismiss: () -> Unit,
    onSelect: (String) -> Unit,
    onRefresh: () -> Unit,
) {
    if (!visible) return

    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        containerColor = JamarrColors.Surface,
        shape = RoundedCornerShape(topStart = 20.dp, topEnd = 20.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = 32.dp),
        ) {
            // Header
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "Playback Device",
                    style = JamarrType.SectionHeader,
                    color = JamarrColors.Text,
                )
                Spacer(Modifier.weight(1f))
                Box(
                    modifier = Modifier
                        .size(36.dp)
                        .clip(CircleShape)
                        .clickable(onClick = onRefresh),
                    contentAlignment = Alignment.Center,
                ) {
                    RefreshIcon(tint = JamarrColors.Muted, size = 18.dp)
                }
            }

            Spacer(Modifier.height(8.dp))

            LazyColumn {
                // Local device option
                item(key = "local") {
                    RendererRow(
                        name = "This Device",
                        subtitle = "Play on your phone",
                        isSelected = activeUdn.startsWith("local:"),
                        icon = { PhoneIcon(tint = JamarrColors.Text, size = 22.dp) },
                        onClick = {
                            val localUdn = renderers.firstOrNull { it.isLocal }?.udn
                                ?: activeUdn.ifBlank { "local:default" }
                            onSelect(localUdn)
                        },
                    )
                }

                items(renderers.filter { !it.isLocal }, key = { it.udn }) { r ->
                    RendererRow(
                        name = r.name,
                        subtitle = r.ip ?: r.manufacturer ?: "Network Device",
                        isSelected = r.udn == activeUdn,
                        icon = { SpeakerIcon(tint = JamarrColors.Text, size = 22.dp) },
                        onClick = { onSelect(r.udn) },
                    )
                }

                if (renderers.none { !it.isLocal }) {
                    item(key = "empty") {
                        Text(
                            text = "No network renderers found.\nTap refresh to scan.",
                            style = JamarrType.Caption,
                            color = JamarrColors.Muted,
                            modifier = Modifier.padding(horizontal = 20.dp, vertical = 24.dp),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun RendererRow(
    name: String,
    subtitle: String,
    isSelected: Boolean,
    icon: @Composable () -> Unit,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(44.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(
                    if (isSelected) JamarrColors.PrimaryTint
                    else JamarrColors.Card,
                ),
            contentAlignment = Alignment.Center,
        ) {
            icon()
        }

        Spacer(Modifier.width(12.dp))

        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = name,
                style = JamarrType.CardTitle,
                color = if (isSelected) JamarrColors.Primary else JamarrColors.Text,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = subtitle,
                style = JamarrType.CaptionSmall,
                color = JamarrColors.Muted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }

        if (isSelected) {
            Spacer(Modifier.width(8.dp))
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .clip(CircleShape)
                    .background(JamarrColors.Primary),
            )
        }
    }
}

@Composable
fun SpeakerIcon(tint: Color, size: Dp = 22.dp) {
    Canvas(modifier = Modifier.size(size)) {
        val s = this.size.minDimension
        val stroke = s * 0.09f
        // Speaker body
        val body = Path().apply {
            moveTo(s * 0.25f, s * 0.35f)
            lineTo(s * 0.15f, s * 0.35f)
            lineTo(s * 0.15f, s * 0.65f)
            lineTo(s * 0.25f, s * 0.65f)
            lineTo(s * 0.45f, s * 0.78f)
            lineTo(s * 0.45f, s * 0.22f)
            close()
        }
        drawPath(body, color = tint)
        // Sound waves
        val wave1 = Path().apply {
            moveTo(s * 0.58f, s * 0.28f)
            cubicTo(s * 0.7f, s * 0.38f, s * 0.7f, s * 0.62f, s * 0.58f, s * 0.72f)
        }
        drawPath(wave1, color = tint, style = Stroke(width = stroke))
        val wave2 = Path().apply {
            moveTo(s * 0.7f, s * 0.18f)
            cubicTo(s * 0.88f, s * 0.34f, s * 0.88f, s * 0.66f, s * 0.7f, s * 0.82f)
        }
        drawPath(wave2, color = tint, style = Stroke(width = stroke))
    }
}

@Composable
fun CastIcon(tint: Color, size: Dp = 22.dp) {
    Canvas(modifier = Modifier.size(size)) {
        val s = this.size.minDimension
        val stroke = s * 0.1f
        // Screen rectangle
        drawRect(
            color = tint,
            topLeft = Offset(s * 0.15f, s * 0.12f),
            size = Size(s * 0.7f, s * 0.55f),
            style = Stroke(width = stroke),
        )
        // Cast waves in bottom-right
        val wave1 = Path().apply {
            moveTo(s * 0.52f, s * 0.78f)
            cubicTo(s * 0.62f, s * 0.82f, s * 0.75f, s * 0.82f, s * 0.85f, s * 0.78f)
        }
        drawPath(wave1, color = tint, style = Stroke(width = stroke))
        val wave2 = Path().apply {
            moveTo(s * 0.42f, s * 0.88f)
            cubicTo(s * 0.58f, s * 0.94f, s * 0.82f, s * 0.94f, s * 0.95f, s * 0.88f)
        }
        drawPath(wave2, color = tint, style = Stroke(width = stroke))
    }
}

@Composable
fun PhoneIcon(tint: Color, size: Dp = 22.dp) {
    Canvas(modifier = Modifier.size(size)) {
        val s = this.size.minDimension
        // Phone body
        drawRoundRect(
            color = tint,
            topLeft = Offset(s * 0.28f, s * 0.08f),
            size = Size(s * 0.44f, s * 0.84f),
            cornerRadius = androidx.compose.ui.geometry.CornerRadius(s * 0.08f, s * 0.08f),
            style = Stroke(width = s * 0.08f),
        )
        // Screen
        drawRoundRect(
            color = tint,
            topLeft = Offset(s * 0.33f, s * 0.18f),
            size = Size(s * 0.34f, s * 0.5f),
            cornerRadius = androidx.compose.ui.geometry.CornerRadius(s * 0.02f, s * 0.02f),
            style = Stroke(width = s * 0.04f),
        )
        // Home button
        drawCircle(
            color = tint,
            radius = s * 0.03f,
            center = Offset(s * 0.5f, s * 0.82f),
        )
    }
}
