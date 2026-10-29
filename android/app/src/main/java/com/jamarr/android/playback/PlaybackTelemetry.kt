package com.jamarr.android.playback

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** The local player's last terminal error, as the phone UI and car surfaces should show it. */
data class PlaybackErrorState(
    val kind: PlaybackFailureKind,
    /** Short, user-facing: "Server unreachable". */
    val summary: String,
    val trackTitle: String?,
    /** True while a bounded automatic retry is pending; false once it gave up or skipped. */
    val recovering: Boolean,
    val atMs: Long,
) {
    val canRetry: Boolean get() = !recovering
}

/**
 * Process-wide view of what the local player is doing that is not part of
 * `Player` state: failures and the diagnostic record behind them.
 *
 * A singleton, like the quality labels on [JamarrPlaybackService], because the
 * service and the UI live in one process but share no object graph beyond the
 * `MediaController` link — which carries player state, not ours.
 */
object PlaybackTelemetry {
    val diagnostics = PlaybackDiagnostics()

    private val _errorState = MutableStateFlow<PlaybackErrorState?>(null)
    val errorState: StateFlow<PlaybackErrorState?> = _errorState.asStateFlow()

    fun setError(state: PlaybackErrorState?) {
        _errorState.value = state
    }
}
