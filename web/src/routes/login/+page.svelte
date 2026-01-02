<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { login } from "$lib/api";
  import TabButton from "$lib/components/TabButton.svelte";
  import {
    currentUser,
    hydrateUser,
    isAuthChecked,
    setUser,
  } from "$stores/user";

  let username = "";
  let password = "";
  let error = "";
  let loading = false;
  let user = null;
  let authReady = false;
  let unsubUser: (() => void) | undefined;
  let unsubAuth: (() => void) | undefined;

  onMount(() => {
    unsubUser = currentUser.subscribe((value) => {
      user = value;
      if (authReady && user) goto("/");
    });
    unsubAuth = isAuthChecked.subscribe((value) => {
      authReady = value;
      if (authReady && user) goto("/");
    });
    hydrateUser().catch(() => {});
  });

  onDestroy(() => {
    if (unsubUser) unsubUser();
    if (unsubAuth) unsubAuth();
  });

  async function handleLogin() {
    loading = true;
    error = "";
    try {
      const nextUser = await login({ username, password });
      setUser(nextUser);
      goto("/");
    } catch (e: any) {
      error = e?.message || "Login failed.";
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
          <label class="block text-sm text-white/70" for="username-input"
            >Username</label
          >
          <input
            class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
            id="username-input"
            name="username"
            autocomplete="username"
            bind:value={username}
            required
          />
        </div>

        <div class="space-y-2">
          <label class="block text-sm text-white/70" for="password-input"
            >Password</label
          >
          <input
            class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
            type="password"
            id="password-input"
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

      <p class="mt-4 text-center text-sm text-white/60">
        Need an account?
        <a class="text-primary" href="/signup">Sign up</a>
      </p>
    </div>
  </div>
</div>
