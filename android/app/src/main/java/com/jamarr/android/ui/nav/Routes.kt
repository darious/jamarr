package com.jamarr.android.ui.nav

import android.net.Uri

object Routes {
    const val HOME = "home"
    const val PLAYLISTS = "playlists"
    const val CHARTS = "charts"
    const val HISTORY = "history"

    const val ARTIST = "artist?mbid={mbid}&name={name}&artSha1={artSha1}"
    const val ALBUM = "album?mbid={mbid}&album={album}&artist={artist}&artistMbid={artistMbid}&artSha1={artSha1}"
    const val PLAYLIST = "playlist/{id}"

    fun artist(mbid: String?, name: String?, artSha1: String? = null): String =
        "artist?mbid=${encode(mbid)}&name=${encode(name)}&artSha1=${encode(artSha1)}"

    fun album(
        albumMbid: String? = null,
        album: String? = null,
        artist: String? = null,
        artistMbid: String? = null,
        artSha1: String? = null,
    ): String = "album?mbid=${encode(albumMbid)}&album=${encode(album)}&artist=${encode(artist)}&artistMbid=${encode(artistMbid)}&artSha1=${encode(artSha1)}"

    fun playlist(id: Long): String = "playlist/$id"

    private fun encode(value: String?): String =
        if (value.isNullOrBlank()) "" else Uri.encode(value)
}

fun JamarrTab.route(): String = when (this) {
    JamarrTab.Home -> Routes.HOME
    JamarrTab.Playlists -> Routes.PLAYLISTS
    JamarrTab.Charts -> Routes.CHARTS
    JamarrTab.History -> Routes.HISTORY
}

fun routeToTab(route: String?): JamarrTab? {
    if (route == null) return null
    return when {
        route.startsWith(Routes.HOME) -> JamarrTab.Home
        route.startsWith(Routes.PLAYLISTS) -> JamarrTab.Playlists
        route.startsWith(Routes.CHARTS) -> JamarrTab.Charts
        route.startsWith(Routes.HISTORY) -> JamarrTab.History
        else -> null
    }
}

fun isRootRoute(route: String?): Boolean = routeToTab(route) != null
