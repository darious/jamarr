package com.jamarr.android.auth

import org.junit.Assert.assertEquals
import org.junit.Test

class TokenHolderTest {
    @Test
    fun setAndClearUpdatesCurrentToken() {
        val holder = TokenHolder("initial")

        assertEquals("initial", holder.get())

        holder.set("updated")
        assertEquals("updated", holder.get())

        holder.clear()
        assertEquals("", holder.get())
    }
}
