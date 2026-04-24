package com.jamarr.android.auth

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class TokenHolder(initial: String = "") {
    private val _token = MutableStateFlow(initial)
    val token: StateFlow<String> = _token.asStateFlow()

    fun get(): String = _token.value

    fun set(value: String) {
        _token.value = value
    }

    fun clear() {
        _token.value = ""
    }
}
