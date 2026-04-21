package com.jamarr.android.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

object JamarrColors {
    val Bg = Color(0xFF150808)
    val Surface = Color(0xFF1E0E0E)
    val Card = Color(0xFF261212)
    val Primary = Color(0xFFFF2D55)
    val PrimaryTint = Color(0x11FF2D55)
    val PrimaryGlow = Color(0x55FF2D55)
    val Tertiary = Color(0xFF00996E)
    val Text = Color(0xFFFFCDD2)
    val Muted = Color(0xFFA1A1A2)
    val Neutral = Color(0xFF8B7171)
    val Border = Color(0xFF2E1818)
    val ScrimBottom = Color(0x88000000)
    val ScrimMini = Color(0x55000000)
}

object JamarrDims {
    val ScreenPadding = 16.dp
    val SectionGap = 24.dp
    val CardRadius = 10.dp
    val AlbumArtRadius = 6.dp
    val AlbumArtRadiusLarge = 10.dp
    val ListItemVPadding = 10.dp
    val BottomNavHeight = 64.dp
    val MiniPlayerHeight = 72.dp
}

object JamarrShapes {
    val Card = RoundedCornerShape(JamarrDims.CardRadius)
    val AlbumArt = RoundedCornerShape(JamarrDims.AlbumArtRadius)
    val AlbumArtLarge = RoundedCornerShape(JamarrDims.AlbumArtRadiusLarge)
}

private val JamarrFontFamily = FontFamily.SansSerif

object JamarrType {
    val ScreenTitle = TextStyle(
        fontFamily = JamarrFontFamily,
        fontWeight = FontWeight.W700,
        fontSize = 20.sp,
    )
    val SectionHeader = TextStyle(
        fontFamily = JamarrFontFamily,
        fontWeight = FontWeight.W600,
        fontSize = 15.sp,
    )
    val CardTitleSmall = TextStyle(
        fontFamily = JamarrFontFamily,
        fontWeight = FontWeight.W600,
        fontSize = 12.sp,
    )
    val CardTitle = TextStyle(
        fontFamily = JamarrFontFamily,
        fontWeight = FontWeight.W600,
        fontSize = 14.sp,
    )
    val Body = TextStyle(
        fontFamily = JamarrFontFamily,
        fontWeight = FontWeight.W400,
        fontSize = 13.sp,
    )
    val CaptionSmall = TextStyle(
        fontFamily = JamarrFontFamily,
        fontWeight = FontWeight.W400,
        fontSize = 10.sp,
    )
    val Caption = TextStyle(
        fontFamily = JamarrFontFamily,
        fontWeight = FontWeight.W400,
        fontSize = 11.sp,
    )
    val TrackNumber = TextStyle(
        fontFamily = JamarrFontFamily,
        fontWeight = FontWeight.W400,
        fontSize = 12.sp,
    )
    val StatValue = TextStyle(
        fontFamily = JamarrFontFamily,
        fontWeight = FontWeight.W700,
        fontSize = 18.sp,
    )
    val HeroTitle = TextStyle(
        fontFamily = JamarrFontFamily,
        fontWeight = FontWeight.W700,
        fontSize = 26.sp,
    )
    val AlbumHeroTitle = TextStyle(
        fontFamily = JamarrFontFamily,
        fontWeight = FontWeight.W700,
        fontSize = 22.sp,
    )
    val ArtistLink = TextStyle(
        fontFamily = JamarrFontFamily,
        fontWeight = FontWeight.W500,
        fontSize = 14.sp,
    )
}
