<script lang="ts">
  import { goto } from "$app/navigation";
  import { onMount, onDestroy } from "svelte";
  import { fade, scale } from "svelte/transition";
  import { changePassword, updateProfile } from "$lib/api";
  import TabButton from "$lib/components/TabButton.svelte";
  import {
    themeAccent,
    themeMode,
    setThemeMode,
    type AccentColor,
    type ThemeMode,
  } from "$lib/stores/theme";
  import {
    currentUser,
    hydrateUser,
    isAuthChecked,
    setUser,
  } from "$lib/stores/user";

  let user = null;
  let authReady = false;
  let unsubUser: (() => void) | undefined;
  let unsubAuth: (() => void) | undefined;

  // Subscribe to themeAccent to ensure UI stays in sync
  let selectedAccent: AccentColor;
  let selectedMode: ThemeMode;

  $: selectedAccent = $themeAccent;
  $: selectedMode = $themeMode;

  let saveStatus: "idle" | "success" | "error" = "idle";

  let email = "";
  let displayName = "";
  let profileMessage = "";
  let profileError = "";
  let updatingProfile = false;
  let initializedProfile = false;

  let currentPassword = "";
  let newPassword = "";
  let confirmPassword = "";
  let passwordMessage = "";
  let passwordError = "";
  let updatingPassword = false;

  // Accent color state
  // selectedAccent uses reactive store above
  let accentMessage = "";
  let accentError = "";
  let updatingAccent = false;

  let updatingMode = false;

  async function saveThemeMode(mode: ThemeMode) {
    if (!user) return;
    updatingMode = true;
    try {
      if (mode === "system") return; // Not supporting system persistence yet for this simple toggle

      const response = await fetch("/api/auth/preferences", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          theme_mode: mode,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to update theme mode");
      }

      setThemeMode(mode);
      selectedMode = mode;
    } catch (e: any) {
      console.error("Failed to update theme mode", e);
    } finally {
      updatingMode = false;
    }
  }

  const accentColors: { name: AccentColor; label: string; color: string }[] = [
    { name: "pink", label: "Pink", color: "#ff006e" },
    { name: "cyan", label: "Cyan", color: "#00d9ff" },
    { name: "blue", label: "Blue", color: "#3b82f6" },
    { name: "purple", label: "Purple", color: "#a855f7" },
    { name: "orange", label: "Orange", color: "#f97316" },
    { name: "yellow", label: "Yellow", color: "#eab308" },
  ];

  onMount(() => {
    unsubUser = currentUser.subscribe((value) => {
      user = value;
      if (authReady && !user) goto("/login");
    });
    unsubAuth = isAuthChecked.subscribe((ready) => {
      authReady = ready;
      if (authReady && !user) goto("/login");
    });
    hydrateUser().catch(() => {});
  });

  onDestroy(() => {
    if (unsubUser) unsubUser();
    if (unsubAuth) unsubAuth();
  });

  $: if (user && !initializedProfile) {
    email = user.email || "";
    displayName = user.display_name || "";
    initializedProfile = true;
  }

  async function saveProfile() {
    if (!user) return;
    updatingProfile = true;
    profileMessage = "";
    profileError = "";
    try {
      const updated = await updateProfile({
        email,
        display_name: displayName || undefined,
      });
      initializedProfile = false;
      setUser(updated);
      profileMessage = "Profile updated.";
    } catch (e: any) {
      profileError = e?.message || "Failed to update profile.";
    } finally {
      updatingProfile = false;
    }
  }

  async function savePassword() {
    if (!user) return;
    if (newPassword !== confirmPassword) {
      passwordError = "New passwords do not match.";
      return;
    }
    if (newPassword.length < 8) {
      passwordError = "Password must be at least 8 characters.";
      return;
    }
    updatingPassword = true;
    passwordMessage = "";
    passwordError = "";
    try {
      await changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      passwordMessage = "Password updated.";
      currentPassword = "";
      newPassword = "";
      confirmPassword = "";
    } catch (e: any) {
      passwordError = e?.message || "Failed to update password.";
    } finally {
      updatingPassword = false;
    }
  }

  async function saveAccentColor(accent: AccentColor) {
    if (!user) return;
    updatingAccent = true;
    accentMessage = "";
    accentError = "";
    try {
      const response = await fetch("/api/auth/preferences", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          accent_color: accentColors.find((c) => c.name === accent)?.color,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to update accent color");
      }

      themeAccent.set(accent);
      selectedAccent = accent;
      accentMessage = "Accent color updated.";
      setTimeout(() => (accentMessage = ""), 3000);
    } catch (e: any) {
      accentError = e?.message || "Failed to update accent color.";
    } finally {
      updatingAccent = false;
    }
  }
</script>

<div class="min-h-screen">
  <div class="mx-auto max-w-5xl px-6 py-10">
    <div class="mb-8 flex flex-col gap-2">
      <p class="text-sm text-subtle">Settings</p>
      <h1 class="text-3xl font-semibold">User Settings</h1>
      <p class="text-sm text-muted">
        Manage your profile, appearance, and security settings.
      </p>
    </div>

    <!-- Appearance Section -->
    <div class="mb-6 surface-glass-panel rounded-2xl p-6">
      <div class="mb-4">
        <h2 class="text-lg font-semibold">Appearance</h2>
        <p class="text-sm text-muted">
          Customize the look and feel of your interface.
        </p>
      </div>

      {#if accentMessage}
        <div
          class="mb-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100 dark:text-emerald-100 text-emerald-700"
        >
          {accentMessage}
        </div>
      {/if}
      {#if accentError}
        <div
          class="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100 dark:text-red-100 text-red-700"
        >
          {accentError}
        </div>
      {/if}

      <div class="space-y-3">
        <div class="block text-sm text-muted">Theme Mode</div>
        <p class="text-xs text-subtle">Select your preferred display mode.</p>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <button
            type="button"
            class="group relative flex flex-col items-center gap-2 rounded-xl border-2 p-3 transition-all hover:scale-105 {selectedMode ===
            'dark'
              ? 'border-accent bg-accent/10'
              : 'border-default bg-surface hover:border-subtle'}"
            on:click={() => saveThemeMode("dark")}
            disabled={updatingMode}
          >
            <div
              class="h-8 w-8 flex items-center justify-center rounded-full bg-slate-900 border border-white/20"
            >
              <svg
                class="w-4 h-4 text-white"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                ><path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"
                ></path></svg
              >
            </div>
            <span
              class="text-xs font-medium {selectedMode === 'dark'
                ? 'text-accent'
                : 'text-muted'}">Dark</span
            >
            {#if selectedMode === "dark"}
              <div
                class="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-accent text-white"
              >
                <svg class="h-3 w-3" fill="currentColor" viewBox="0 0 20 20"
                  ><path
                    fill-rule="evenodd"
                    d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                    clip-rule="evenodd"
                  /></svg
                >
              </div>
            {/if}
          </button>

          <button
            type="button"
            class="group relative flex flex-col items-center gap-2 rounded-xl border-2 p-3 transition-all hover:scale-105 {selectedMode ===
            'light'
              ? 'border-accent bg-accent/10'
              : 'border-default bg-surface hover:border-subtle'}"
            on:click={() => saveThemeMode("light")}
            disabled={updatingMode}
          >
            <div
              class="h-8 w-8 flex items-center justify-center rounded-full bg-white border border-slate-200"
            >
              <svg
                class="w-4 h-4 text-yellow-500"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                ><path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"
                ></path></svg
              >
            </div>
            <span
              class="text-xs font-medium {selectedMode === 'light'
                ? 'text-accent'
                : 'text-muted'}">Light</span
            >
            {#if selectedMode === "light"}
              <div
                class="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-accent text-white"
              >
                <svg class="h-3 w-3" fill="currentColor" viewBox="0 0 20 20"
                  ><path
                    fill-rule="evenodd"
                    d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                    clip-rule="evenodd"
                  /></svg
                >
              </div>
            {/if}
          </button>
        </div>
      </div>

      <div class="space-y-3">
        <div class="block text-sm text-muted">Accent Color</div>
        <p class="text-xs text-subtle">
          Choose your preferred accent color for buttons, highlights, and
          interactive elements.
        </p>
        <div class="grid grid-cols-3 gap-3 sm:grid-cols-6">
          {#each accentColors as { name, label, color }}
            <button
              type="button"
              class="group relative flex flex-col items-center gap-2 rounded-xl border-2 p-3 transition-all hover:scale-105 {selectedAccent ===
              name
                ? 'border-accent bg-accent/10'
                : 'border-default bg-surface hover:border-subtle'}"
              on:click={() => saveAccentColor(name)}
              disabled={updatingAccent}
            >
              <div
                class="h-8 w-8 rounded-full border-2 border-white/20 shadow-lg"
                style="background-color: {color}"
              />
              <span
                class="text-xs font-medium {selectedAccent === name
                  ? 'text-accent'
                  : 'text-muted'}"
              >
                {label}
              </span>
              {#if selectedAccent === name}
                <div
                  class="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-accent text-white"
                >
                  <svg class="h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                    <path
                      fill-rule="evenodd"
                      d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                      clip-rule="evenodd"
                    />
                  </svg>
                </div>
              {/if}
            </button>
          {/each}
        </div>
      </div>
    </div>

    <div class="grid gap-6 lg:grid-cols-2">
      <div class="surface-glass-panel rounded-2xl p-6">
        <div class="mb-4">
          <h2 class="text-lg font-semibold">Profile</h2>
          <p class="text-sm text-muted">Update your email or display name.</p>
        </div>

        {#if profileMessage}
          <div
            class="mb-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100 dark:text-emerald-100 text-emerald-700"
          >
            {profileMessage}
          </div>
        {/if}
        {#if profileError}
          <div
            class="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100 dark:text-red-100 text-red-700"
          >
            {profileError}
          </div>
        {/if}

        <form class="space-y-4" on:submit|preventDefault={saveProfile}>
          <div class="space-y-2">
            <label class="block text-sm text-muted" for="username"
              >Username</label
            >
            <input
              id="username"
              class="input w-full"
              value={user?.username || ""}
              disabled
            />
          </div>
          <div class="space-y-2">
            <label class="block text-sm text-muted" for="email">Email</label>
            <input
              id="email"
              class="input w-full"
              type="email"
              bind:value={email}
              required
            />
          </div>
          <div class="space-y-2">
            <label class="block text-sm text-muted" for="display_name"
              >Display name</label
            >
            <input
              id="display_name"
              class="input w-full"
              bind:value={displayName}
              placeholder="How your name appears"
            />
          </div>

          <TabButton
            type="submit"
            disabled={updatingProfile}
            className="w-full"
          >
            {#if updatingProfile}Saving...{:else}Save Changes{/if}
          </TabButton>
        </form>
      </div>

      <div class="surface-glass-panel rounded-2xl p-6">
        <div class="mb-4">
          <h2 class="text-lg font-semibold">Change password</h2>
          <p class="text-sm text-muted">
            Keep your account secure with a new password.
          </p>
        </div>

        {#if passwordMessage}
          <div
            class="mb-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100 dark:text-emerald-100 text-emerald-700"
          >
            {passwordMessage}
          </div>
        {/if}
        {#if passwordError}
          <div
            class="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100 dark:text-red-100 text-red-700"
          >
            {passwordError}
          </div>
        {/if}

        <form class="space-y-4" on:submit|preventDefault={savePassword}>
          <div class="space-y-2">
            <label class="block text-sm text-muted" for="current_password"
              >Current password</label
            >
            <input
              id="current_password"
              class="input w-full"
              type="password"
              autocomplete="current-password"
              bind:value={currentPassword}
              required
            />
          </div>
          <div class="space-y-2">
            <label class="block text-sm text-muted" for="new_password"
              >New password</label
            >
            <input
              id="new_password"
              class="input w-full"
              type="password"
              autocomplete="new-password"
              bind:value={newPassword}
              required
              minlength="8"
            />
          </div>
          <div class="space-y-2">
            <label class="block text-sm text-muted" for="confirm_password"
              >Confirm new password</label
            >
            <input
              id="confirm_password"
              class="input w-full"
              type="password"
              autocomplete="new-password"
              bind:value={confirmPassword}
              required
              minlength="8"
            />
          </div>

          <TabButton
            type="submit"
            disabled={updatingPassword}
            className="w-full"
          >
            {#if updatingPassword}Updating...{:else}Update Password{/if}
          </TabButton>
        </form>
      </div>
    </div>
  </div>
</div>
