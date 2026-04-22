package com.jamarr.android.ui.screens

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.jamarr.android.R
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrType

@Composable
fun LoginScreen(
    serverUrl: String,
    username: String,
    password: String,
    busy: Boolean,
    status: String,
    onServerUrlChange: (String) -> Unit,
    onUsernameChange: (String) -> Unit,
    onPasswordChange: (String) -> Unit,
    onSubmit: () -> Unit,
) {
    val canSubmit = !busy &&
        serverUrl.isNotBlank() &&
        username.isNotBlank() &&
        password.isNotBlank()

    Box(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .navigationBarsPadding()
                .imePadding()
                .padding(JamarrDims.ScreenPadding),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Image(
                painter = painterResource(id = R.drawable.jamarr_logo),
                contentDescription = "Jamarr",
                modifier = Modifier
                    .size(64.dp)
                    .clip(RoundedCornerShape(12.dp)),
            )
            Text(
                text = "Jamarr Music",
                style = JamarrType.ScreenTitle,
                color = JamarrColors.Text,
            )
            Text(
                text = status,
                style = JamarrType.Body,
                color = JamarrColors.Muted,
            )
            LoginField(
                value = serverUrl,
                onValueChange = onServerUrlChange,
                label = "Server URL",
                placeholder = "http://192.168.1.20:8000",
                keyboardType = KeyboardType.Uri,
            )
            LoginField(
                value = username,
                onValueChange = onUsernameChange,
                label = "Username",
            )
            LoginField(
                value = password,
                onValueChange = onPasswordChange,
                label = "Password",
                keyboardType = KeyboardType.Password,
                mask = true,
            )
            Button(
                onClick = onSubmit,
                enabled = canSubmit,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(
                    containerColor = JamarrColors.Primary,
                    contentColor = Color.White,
                    disabledContainerColor = JamarrColors.Card,
                    disabledContentColor = JamarrColors.Muted,
                ),
            ) {
                Text(if (busy) "…" else "Log in")
            }
        }
        if (busy) {
            CircularProgressIndicator(
                color = JamarrColors.Primary,
                modifier = Modifier.align(Alignment.Center),
            )
        }
    }
}

@Composable
private fun LoginField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    placeholder: String? = null,
    keyboardType: KeyboardType = KeyboardType.Text,
    mask: Boolean = false,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text(label) },
        placeholder = placeholder?.let { { Text(it) } },
        singleLine = true,
        keyboardOptions = KeyboardOptions(
            capitalization = KeyboardCapitalization.None,
            keyboardType = keyboardType,
        ),
        visualTransformation = if (mask) PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None,
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = JamarrColors.Primary,
            unfocusedBorderColor = JamarrColors.Border,
            focusedLabelColor = JamarrColors.Primary,
            unfocusedLabelColor = JamarrColors.Muted,
            cursorColor = JamarrColors.Primary,
            focusedTextColor = JamarrColors.Text,
            unfocusedTextColor = JamarrColors.Text,
        ),
    )
}
