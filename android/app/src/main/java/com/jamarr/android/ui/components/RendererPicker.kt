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
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
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
import com.jamarr.android.upnp.UpnpRendererInfo
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrShapes
import com.jamarr.android.ui.theme.JamarrType

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RendererPicker(
    visible: Boolean,
    serverRenderers: List<Renderer>,
    deviceRenderers: List<UpnpRendererInfo>,
    activeUdn: String,
    useDeviceUpnp: Boolean,
    onDismiss: () -> Unit,
    onSelectServer: (String) -> Unit,
    onSelectDevice: (String) -> Unit,
    onSelectLocal: () -> Unit,
    onRefresh: () -> Unit,
    onToggleDeviceMode: (Boolean) -> Unit,
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

            // Mode toggle row
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "Control from this device",
                        style = JamarrType.CardTitle,
                        color = JamarrColors.Text,
                    )
                    Text(
                        text = if (useDeviceUpnp) "Phone discovers UPnP renderers on Wi-Fi"
                        else "Server discovers and drives renderers",
                        style = JamarrType.CaptionSmall,
                        color = JamarrColors.Muted,
                    )
                }
                Switch(
                    checked = useDeviceUpnp,
                    onCheckedChange = onToggleDeviceMode,
                    colors = SwitchDefaults.colors(
                        checkedTrackColor = JamarrColors.Primary,
                    ),
                )
            }

            Spacer(Modifier.height(8.dp))

            LazyColumn {
                item(key = "local") {
                    RendererRow(
                        name = "This Device",
                        subtitle = "Play on your phone",
                        isSelected = activeUdn.startsWith("local:"),
                        icon = { PhoneIcon(tint = JamarrColors.Text, size = 22.dp) },
                        onClick = onSelectLocal,
                    )
                }

                if (useDeviceUpnp) {
                    items(deviceRenderers, key = { "dev:" + it.udn }) { r ->
                        RendererRow(
                            name = r.name,
                            subtitle = r.ip ?: r.manufacturer ?: "Network Device",
                            isSelected = r.udn == activeUdn,
                            icon = { SpeakerIcon(tint = JamarrColors.Text, size = 22.dp) },
                            onClick = { onSelectDevice(r.udn) },
                        )
                    }
                    if (deviceRenderers.isEmpty()) {
                        item(key = "empty-dev") {
                            Text(
                                text = "Searching for UPnP renderers on Wi-Fi…\nTap refresh to scan again.",
                                style = JamarrType.Caption,
                                color = JamarrColors.Muted,
                                modifier = Modifier.padding(horizontal = 20.dp, vertical = 24.dp),
                            )
                        }
                    }
                } else {
                    items(serverRenderers.filter { !it.isLocal }, key = { "srv:" + it.activeKey }) { r ->
                        RendererRow(
                            name = r.name,
                            subtitle = listOfNotNull(r.rendererKind.uppercase(), r.ip ?: r.manufacturer)
                                .joinToString(" · ")
                                .ifBlank { "Network Device" },
                            isSelected = r.activeKey == activeUdn || r.udn == activeUdn,
                            icon = { SpeakerIcon(tint = JamarrColors.Text, size = 22.dp) },
                            onClick = { onSelectServer(r.activeKey) },
                        )
                    }
                    if (serverRenderers.none { !it.isLocal }) {
                        item(key = "empty-srv") {
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
        drawRect(
            color = tint,
            topLeft = Offset(s * 0.15f, s * 0.12f),
            size = Size(s * 0.7f, s * 0.55f),
            style = Stroke(width = stroke),
        )
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
        drawRoundRect(
            color = tint,
            topLeft = Offset(s * 0.28f, s * 0.08f),
            size = Size(s * 0.44f, s * 0.84f),
            cornerRadius = androidx.compose.ui.geometry.CornerRadius(s * 0.08f, s * 0.08f),
            style = Stroke(width = s * 0.08f),
        )
        drawRoundRect(
            color = tint,
            topLeft = Offset(s * 0.33f, s * 0.18f),
            size = Size(s * 0.34f, s * 0.5f),
            cornerRadius = androidx.compose.ui.geometry.CornerRadius(s * 0.02f, s * 0.02f),
            style = Stroke(width = s * 0.04f),
        )
        drawCircle(
            color = tint,
            radius = s * 0.03f,
            center = Offset(s * 0.5f, s * 0.82f),
        )
    }
}
