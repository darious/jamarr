<script lang="ts">
  import { goto } from "$app/navigation";
  import { onMount, onDestroy } from "svelte";
  import { fade, scale } from "svelte/transition";
  import { changePassword, updateProfile } from "$lib/api";
  import TabButton from "$lib/components/TabButton.svelte";
  import { themeAccent, type AccentColor } from "$lib/stores/theme";
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
  $: selectedAccent = $themeAccent;

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
  // selectedAccent is declared above and reactive to store
  let accentMessage = "";
  let accentError = "";
  let updatingAccent = false;

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

<div
  class="min-h-screen bg-gradient-to-br from-black via-surface-50/70 to-black text-white"
>
  <div class="mx-auto max-w-5xl px-6 py-10">
    <div class="mb-8 flex flex-col gap-2">
      <p class="text-sm text-white/60">Settings</p>
      <h1 class="text-3xl font-semibold">User Settings</h1>
      <p class="text-sm text-white/60">
        Manage your profile, appearance, and security settings.
      </p>
    </div>

    <!-- Appearance Section -->
    <div
      class="mb-6 rounded-2xl border border-white/10 bg-white/5 p-6 backdrop-blur"
    >
      <div class="mb-4">
        <h2 class="text-lg font-semibold">Appearance</h2>
        <p class="text-sm text-white/60">
          Customize the look and feel of your interface.
        </p>
      </div>

      {#if accentMessage}
        <div
          class="mb-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100"
        >
          {accentMessage}
        </div>
      {/if}
      {#if accentError}
        <div
          class="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100"
        >
          {accentError}
        </div>
      {/if}

      <div class="space-y-3">
        <div class="block text-sm text-white/70">Accent Color</div>
        <p class="text-xs text-white/50">
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
                : 'border-white/10 bg-white/5 hover:border-white/20'}"
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
                  : 'text-white/70'}"
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
      <div
        class="rounded-2xl border border-white/10 bg-white/5 p-6 backdrop-blur"
      >
        <div class="mb-4">
          <h2 class="text-lg font-semibold">Profile</h2>
          <p class="text-sm text-white/60">
            Update your email or display name.
          </p>
        </div>

        {#if profileMessage}
          <div
            class="mb-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100"
          >
            {profileMessage}
          </div>
        {/if}
        {#if profileError}
          <div
            class="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100"
          >
            {profileError}
          </div>
        {/if}

        <form class="space-y-4" on:submit|preventDefault={saveProfile}>
          <div class="space-y-2">
            <label class="block text-sm text-white/70" for="username"
              >Username</label
            >
            <input
              id="username"
              class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
              value={user?.username || ""}
              disabled
            />
          </div>
          <div class="space-y-2">
            <label class="block text-sm text-white/70" for="email">Email</label>
            <input
              id="email"
              class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
              type="email"
              bind:value={email}
              required
            />
          </div>
          <div class="space-y-2">
            <label class="block text-sm text-white/70" for="display_name"
              >Display name</label
            >
            <input
              id="display_name"
              class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
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

      <div
        class="rounded-2xl border border-white/10 bg-white/5 p-6 backdrop-blur"
      >
        <div class="mb-4">
          <h2 class="text-lg font-semibold">Change password</h2>
          <p class="text-sm text-white/60">
            Keep your account secure with a new password.
          </p>
        </div>

        {#if passwordMessage}
          <div
            class="mb-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100"
          >
            {passwordMessage}
          </div>
        {/if}
        {#if passwordError}
          <div
            class="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100"
          >
            {passwordError}
          </div>
        {/if}

        <form class="space-y-4" on:submit|preventDefault={savePassword}>
          <div class="space-y-2">
            <label class="block text-sm text-white/70" for="current_password"
              >Current password</label
            >
            <input
              id="current_password"
              class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
              type="password"
              autocomplete="current-password"
              bind:value={currentPassword}
              required
            />
          </div>
          <div class="space-y-2">
            <label class="block text-sm text-white/70" for="new_password"
              >New password</label
            >
            <input
              id="new_password"
              class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
              type="password"
              autocomplete="new-password"
              bind:value={newPassword}
              required
              minlength="8"
            />
          </div>
          <div class="space-y-2">
            <label class="block text-sm text-white/70" for="confirm_password"
              >Confirm new password</label
            >
            <input
              id="confirm_password"
              class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
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
