package com.jamarr.android.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

@Composable
fun HomeIcon(tint: Color, size: Dp = 22.dp) {
    Canvas(modifier = Modifier.size(size)) {
        val s = this.size.minDimension
        val stroke = s * 0.09f
        val path = Path().apply {
            moveTo(s * 0.5f, s * 0.1f)
            lineTo(s * 0.1f, s * 0.45f)
            lineTo(s * 0.1f, s * 0.9f)
            lineTo(s * 0.38f, s * 0.9f)
            lineTo(s * 0.38f, s * 0.6f)
            lineTo(s * 0.62f, s * 0.6f)
            lineTo(s * 0.62f, s * 0.9f)
            lineTo(s * 0.9f, s * 0.9f)
            lineTo(s * 0.9f, s * 0.45f)
            close()
        }
        drawPath(path, color = tint, style = Stroke(width = stroke))
    }
}

@Composable
fun PlaylistIcon(tint: Color, size: Dp = 22.dp) {
    Canvas(modifier = Modifier.size(size)) {
        val s = this.size.minDimension
        val stroke = s * 0.08f
        val lineX = s * 0.35f
        val dotR = s * 0.07f
        val rowYs = listOf(s * 0.25f, s * 0.5f, s * 0.75f)
        rowYs.forEach { y ->
            drawCircle(tint, dotR, Offset(s * 0.18f, y))
            drawLine(
                color = tint,
                start = Offset(lineX, y),
                end = Offset(s * 0.9f, y),
                strokeWidth = stroke,
            )
        }
    }
}

@Composable
fun ChartsIcon(tint: Color, size: Dp = 22.dp) {
    Canvas(modifier = Modifier.size(size)) {
        val s = this.size.minDimension
        val stroke = s * 0.12f
        val bars = listOf(0.25f, 0.55f, 0.4f, 0.75f, 0.35f)
        val spacing = s / (bars.size + 1)
        bars.forEachIndexed { i, h ->
            val x = spacing * (i + 1)
            val top = s * (1f - h)
            drawLine(
                color = tint,
                start = Offset(x, top),
                end = Offset(x, s * 0.95f),
                strokeWidth = stroke,
            )
        }
    }
}

@Composable
fun HistoryIcon(tint: Color, size: Dp = 22.dp) {
    Canvas(modifier = Modifier.size(size)) {
        val s = this.size.minDimension
        val stroke = s * 0.09f
        val center = Offset(s * 0.5f, s * 0.55f)
        val radius = s * 0.38f
        drawCircle(tint, radius, center, style = Stroke(width = stroke))
        drawLine(
            tint,
            start = center,
            end = Offset(center.x, center.y - radius * 0.55f),
            strokeWidth = stroke,
        )
        drawLine(
            tint,
            start = center,
            end = Offset(center.x + radius * 0.55f, center.y),
            strokeWidth = stroke,
        )
    }
}

@Composable
fun SearchIcon(tint: Color, size: Dp = 16.dp) {
    Canvas(modifier = Modifier.size(size)) {
        val s = this.size.minDimension
        val stroke = s * 0.12f
        val center = Offset(s * 0.42f, s * 0.42f)
        val radius = s * 0.3f
        drawCircle(tint, radius, center, style = Stroke(width = stroke))
        drawLine(
            tint,
            start = Offset(center.x + radius * 0.7f, center.y + radius * 0.7f),
            end = Offset(s * 0.9f, s * 0.9f),
            strokeWidth = stroke,
        )
    }
}

@Composable
fun CloseIcon(tint: Color, size: Dp = 14.dp) {
    Canvas(modifier = Modifier.size(size)) {
        val s = this.size.minDimension
        val stroke = s * 0.14f
        val pad = s * 0.2f
        drawLine(
            tint,
            Offset(pad, pad),
            Offset(s - pad, s - pad),
            strokeWidth = stroke,
        )
        drawLine(
            tint,
            Offset(s - pad, pad),
            Offset(pad, s - pad),
            strokeWidth = stroke,
        )
    }
}

@Composable
fun PlayIcon(tint: Color, size: Dp = 18.dp) {
    Canvas(modifier = Modifier.size(size)) {
        val s = this.size.minDimension
        val path = Path().apply {
            moveTo(s * 0.28f, s * 0.2f)
            lineTo(s * 0.8f, s * 0.5f)
            lineTo(s * 0.28f, s * 0.8f)
            close()
        }
        drawPath(path, color = tint)
    }
}

@Composable
fun SkipPreviousIcon(tint: Color, size: Dp = 18.dp) {
    Canvas(modifier = Modifier.size(size)) {
        val s = this.size.minDimension
        val barW = s * 0.12f
        val tri = Path().apply {
            moveTo(s * 0.85f, s * 0.2f)
            lineTo(s * 0.35f, s * 0.5f)
            lineTo(s * 0.85f, s * 0.8f)
            close()
        }
        drawPath(tri, color = tint)
        drawRect(
            color = tint,
            topLeft = Offset(s * 0.2f, s * 0.2f),
            size = Size(barW, s * 0.6f),
        )
    }
}

@Composable
fun SkipNextIcon(tint: Color, size: Dp = 18.dp) {
    Canvas(modifier = Modifier.size(size)) {
        val s = this.size.minDimension
        val barW = s * 0.12f
        val tri = Path().apply {
            moveTo(s * 0.15f, s * 0.2f)
            lineTo(s * 0.65f, s * 0.5f)
            lineTo(s * 0.15f, s * 0.8f)
            close()
        }
        drawPath(tri, color = tint)
        drawRect(
            color = tint,
            topLeft = Offset(s * 0.68f, s * 0.2f),
            size = Size(barW, s * 0.6f),
        )
    }
}

@Composable
fun StopIcon(tint: Color, size: Dp = 18.dp) {
    Canvas(modifier = Modifier.size(size)) {
        val s = this.size.minDimension
        val pad = s * 0.24f
        drawRect(
            color = tint,
            topLeft = Offset(pad, pad),
            size = Size(s - pad * 2, s - pad * 2),
        )
    }
}

@Composable
fun PauseIcon(tint: Color, size: Dp = 18.dp) {
    Canvas(modifier = Modifier.size(size)) {
        val s = this.size.minDimension
        val barW = s * 0.18f
        val gap = s * 0.14f
        val leftX = s * 0.5f - gap / 2f - barW
        val rightX = s * 0.5f + gap / 2f
        val top = s * 0.22f
        val bottom = s * 0.78f
        drawRect(
            color = tint,
            topLeft = Offset(leftX, top),
            size = Size(barW, bottom - top),
        )
        drawRect(
            color = tint,
            topLeft = Offset(rightX, top),
            size = Size(barW, bottom - top),
        )
    }
}
