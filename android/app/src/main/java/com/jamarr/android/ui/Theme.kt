package com.jamarr.android.ui

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

fun darkJamarrColorScheme(): ColorScheme = darkColorScheme(
    primary = Color(0xffff4f9a),
    onPrimary = Color(0xff310018),
    primaryContainer = Color(0xff7a1749),
    onPrimaryContainer = Color(0xffffd8e7),
    secondary = Color(0xffffb1cf),
    onSecondary = Color(0xff3b071f),
    secondaryContainer = Color(0xff4a3440),
    onSecondaryContainer = Color(0xffffd8e7),
    tertiary = Color(0xffd7c2ff),
    onTertiary = Color(0xff241047),
    tertiaryContainer = Color(0xff3a2d4f),
    onTertiaryContainer = Color(0xffede2ff),
    background = Color(0xff121113),
    onBackground = Color(0xffeee7ed),
    surface = Color(0xff18161a),
    onSurface = Color(0xffeee7ed),
    surfaceVariant = Color(0xff2b2730),
    onSurfaceVariant = Color(0xffd2c4ce),
    surfaceContainer = Color(0xff1c1a1f),
    error = Color(0xffffb4ab),
    onError = Color(0xff690005),
)

fun jamarrShapes(): Shapes = Shapes(
    extraSmall = RoundedCornerShape(4.dp),
    small = RoundedCornerShape(6.dp),
    medium = RoundedCornerShape(8.dp),
    large = RoundedCornerShape(8.dp),
    extraLarge = RoundedCornerShape(8.dp),
)
