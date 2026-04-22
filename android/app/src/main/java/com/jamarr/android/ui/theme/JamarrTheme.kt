package com.jamarr.android.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private fun jamarrColorScheme() = darkColorScheme(
    primary = JamarrColors.Primary,
    onPrimary = JamarrColors.Text,
    secondary = JamarrColors.Primary,
    onSecondary = JamarrColors.Text,
    tertiary = JamarrColors.Tertiary,
    onTertiary = JamarrColors.Text,
    background = JamarrColors.Bg,
    onBackground = JamarrColors.Text,
    surface = JamarrColors.Surface,
    onSurface = JamarrColors.Text,
    surfaceVariant = JamarrColors.Card,
    onSurfaceVariant = JamarrColors.Muted,
    surfaceContainer = JamarrColors.Card,
    outline = JamarrColors.Border,
    outlineVariant = JamarrColors.Border,
    error = JamarrColors.Primary,
    onError = JamarrColors.Text,
)

private fun jamarrTypography() = Typography(
    displayLarge = JamarrType.HeroTitle,
    displayMedium = JamarrType.HeroTitle,
    headlineLarge = JamarrType.AlbumHeroTitle,
    headlineMedium = JamarrType.ScreenTitle,
    headlineSmall = JamarrType.SectionHeader,
    titleLarge = JamarrType.ScreenTitle,
    titleMedium = JamarrType.SectionHeader,
    titleSmall = JamarrType.CardTitle,
    bodyLarge = JamarrType.Body,
    bodyMedium = JamarrType.Body,
    bodySmall = JamarrType.Caption,
    labelLarge = JamarrType.CardTitle,
    labelMedium = JamarrType.Caption,
    labelSmall = JamarrType.CaptionSmall,
)

private fun jamarrShapes() = Shapes(
    extraSmall = JamarrShapes.AlbumArt,
    small = JamarrShapes.AlbumArt,
    medium = JamarrShapes.Card,
    large = JamarrShapes.Card,
    extraLarge = JamarrShapes.AlbumArtLarge,
)

@Composable
fun JamarrTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = jamarrColorScheme(),
        typography = jamarrTypography(),
        shapes = jamarrShapes(),
        content = content,
    )
}
