package com.jamarr.android.ui.components

import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrType

/** A yes/no question in the app's dialog styling. */
@Composable
fun ConfirmDialog(
    title: String,
    text: String,
    confirmLabel: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = JamarrColors.Surface,
        titleContentColor = JamarrColors.Text,
        textContentColor = JamarrColors.Muted,
        title = { Text(title, style = JamarrType.SectionHeader, color = JamarrColors.Text) },
        text = { Text(text, style = JamarrType.Body, color = JamarrColors.Muted) },
        confirmButton = {
            TextButton(
                onClick = onConfirm,
                colors = ButtonDefaults.textButtonColors(contentColor = JamarrColors.Primary),
            ) { Text(confirmLabel) }
        },
        dismissButton = {
            TextButton(
                onClick = onDismiss,
                colors = ButtonDefaults.textButtonColors(contentColor = JamarrColors.Muted),
            ) { Text("Cancel") }
        },
    )
}
