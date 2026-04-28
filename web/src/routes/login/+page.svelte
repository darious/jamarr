<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { login, setupFirstUser, checkSetupStatus } from "$lib/api";
  import TabButton from "$lib/components/TabButton.svelte";
  import {
    currentUser,
    hydrateUser,
    isAuthChecked,
    setUser,
  } from "$stores/user";
  import { setAccessToken, setupTokenRefresh } from "$lib/stores/auth";

  let username = "";
  let password = "";
  let email = "";
  let displayName = "";
  let error = "";
  let loading = false;
  let setupMode = false;
  let setupChecked = false;
  let user = null;
  let authReady = false;
  let unsubUser: (() => void) | undefined;
  let unsubAuth: (() => void) | undefined;

  onMount(async () => {
    unsubUser = currentUser.subscribe((value) => {
      user = value;
      if (authReady && user) goto("/");
    });
    unsubAuth = isAuthChecked.subscribe((value) => {
      authReady = value;
      if (authReady && user) goto("/");
    });
    hydrateUser().catch(() => {});

    try {
      const status = await checkSetupStatus();
      setupMode = status.setup_required;
    } catch {
      // If setup-status fails, assume it's already configured — show login
    }
    setupChecked = true;
  });

  onDestroy(() => {
    if (unsubUser) unsubUser();
    if (unsubAuth) unsubAuth();
  });

  async function handleLogin() {
    loading = true;
    error = "";
    try {
      const response = await login({ username, password });
      setAccessToken(response.access_token);
      setUser(response.user);
      setupTokenRefresh();
      goto("/");
    } catch (e: any) {
      error = e?.message || "Login failed.";
    } finally {
      loading = false;
    }
  }

  async function handleSetup() {
    loading = true;
    error = "";
    try {
      const response = await setupFirstUser({
        username,
        email,
        password,
        display_name: displayName || undefined,
      });
      setAccessToken(response.access_token);
      setUser(response.user);
      setupTokenRefresh();
      goto("/");
    } catch (e: any) {
      error = e?.message || "Setup failed.";
    } finally {
      loading = false;
    }
  }
</script>

<div
  class="min-h-screen bg-gradient-to-br from-black via-surface-50/70 to-black"
>
  <div
    class="mx-auto flex max-w-5xl flex-col items-center justify-center px-6 py-20 gap-8"
  >
    <div class="flex flex-col items-center gap-4">
      <img
        src="/assets/logo.png"
        alt="Jamarr logo"
        class="w-full max-w-2xl drop-shadow-2xl"
      />
    </div>

    {#if !setupChecked}
      <div class="text-white/60">Loading...</div>
    {:else if setupMode}
      <div
        class="w-full max-w-md rounded-2xl border border-white/10 bg-white/5 p-8 backdrop-blur"
      >
        <div class="mb-6 text-center">
          <p class="text-sm text-white/60">Welcome to</p>
          <h1 class="text-2xl font-semibold text-white">Jamarr</h1>
          <p class="text-sm text-white/60">
            Create your admin account to get started.
          </p>
        </div>

        {#if error}
          <div
            class="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100"
          >
            {error}
          </div>
        {/if}

        <form class="space-y-4" on:submit|preventDefault={handleSetup}>
          <div class="space-y-2">
            <label class="block text-sm text-white/70" for="setup-username"
              >Username</label
            >
            <input
              class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
              id="setup-username"
              name="username"
              autocomplete="username"
              bind:value={username}
              required
            />
          </div>

          <div class="space-y-2">
            <label class="block text-sm text-white/70" for="setup-email"
              >Email</label
            >
            <input
              class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
              type="email"
              id="setup-email"
              name="email"
              autocomplete="email"
              bind:value={email}
              required
            />
          </div>

          <div class="space-y-2">
            <label class="block text-sm text-white/70" for="setup-display-name"
              >Display name <span class="text-white/40">(optional)</span></label
            >
            <input
              class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
              id="setup-display-name"
              name="display_name"
              bind:value={displayName}
            />
          </div>

          <div class="space-y-2">
            <label class="block text-sm text-white/70" for="setup-password"
              >Password</label
            >
            <input
              class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
              type="password"
              id="setup-password"
              name="password"
              autocomplete="new-password"
              bind:value={password}
              required
              minlength="8"
            />
          </div>

          <TabButton
            type="submit"
            disabled={loading}
            className="w-full justify-center"
          >
            {loading ? "Setting up..." : "Create Account"}
          </TabButton>
        </form>
      </div>
    {:else}
      <div
        class="w-full max-w-md rounded-2xl border border-white/10 bg-white/5 p-8 backdrop-blur"
      >
        <div class="mb-6 text-center">
          <p class="text-sm text-white/60">Welcome back to</p>
          <h1 class="text-2xl font-semibold text-white">Jamarr</h1>
          <p class="text-sm text-white/60">
            Sign in with your username to continue.
          </p>
        </div>

        {#if error}
          <div
            class="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100"
          >
            {error}
          </div>
        {/if}

        <form class="space-y-4" on:submit|preventDefault={handleLogin}>
          <div class="space-y-2">
            <label class="block text-sm text-white/70" for="login-username"
              >Username</label
            >
            <input
              class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
              id="login-username"
              name="username"
              autocomplete="username"
              bind:value={username}
              required
            />
          </div>

          <div class="space-y-2">
            <label class="block text-sm text-white/70" for="login-password"
              >Password</label
            >
            <input
              class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
              type="password"
              id="login-password"
              name="password"
              autocomplete="current-password"
              bind:value={password}
              required
              minlength="8"
            />
          </div>

          <TabButton
            type="submit"
            disabled={loading}
            className="w-full justify-center"
          >
            {loading ? "Signing in..." : "Sign In"}
          </TabButton>
        </form>
      </div>
    {/if}
  </div>
</div>
