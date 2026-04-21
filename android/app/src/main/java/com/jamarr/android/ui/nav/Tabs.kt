package com.jamarr.android.ui.nav

enum class JamarrTab(val title: String) {
    Home("Home"),
    Playlists("Playlists"),
    Charts("Charts"),
    History("History");

    companion object {
        fun fromIndex(index: Int): JamarrTab =
            entries.getOrElse(index) { Home }
    }
}
