<script lang="ts">
  import { goto } from "$app/navigation";
  import { onDestroy, onMount } from "svelte";
  import { changePassword, updateProfile } from "$lib/api";
  import {
    currentUser,
    hydrateUser,
    isAuthChecked,
    setUser,
  } from "$stores/user";

  let user = null;
  let authReady = false;
  let unsubUser: (() => void) | undefined;
  let unsubAuth: (() => void) | undefined;

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
</script>

<div
  class="min-h-screen bg-gradient-to-br from-black via-surface-50/70 to-black text-white"
>
  <div class="mx-auto max-w-5xl px-6 py-10">
    <div class="mb-8 flex flex-col gap-2">
      <p class="text-sm text-white/60">Settings</p>
      <h1 class="text-3xl font-semibold">Account</h1>
      <p class="text-sm text-white/60">
        Manage your email and password. Sessions stay signed in by default.
      </p>
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

          <button
            class="btn w-full normal-case bg-primary text-white hover:bg-primary/90"
            type="submit"
            disabled={updatingProfile}
          >
            {#if updatingProfile}Saving...{:else}Save Changes{/if}
          </button>
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

          <button
            class="btn w-full normal-case bg-primary text-white hover:bg-primary/90"
            type="submit"
            disabled={updatingPassword}
          >
            {#if updatingPassword}Updating...{:else}Update Password{/if}
          </button>
        </form>
      </div>
    </div>
  </div>
</div>
