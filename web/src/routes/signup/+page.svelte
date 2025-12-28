<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { signup } from "$lib/api";
  import {
    currentUser,
    hydrateUser,
    isAuthChecked,
    setUser,
  } from "$stores/user";

  let username = "";
  let email = "";
  let password = "";
  let displayName = "";
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

  async function handleSignup() {
    loading = true;
    error = "";
    try {
      const createdUser = await signup({
        username,
        email,
        password,
        display_name: displayName || undefined,
      });
      setUser(createdUser);
      goto("/");
    } catch (e: any) {
      error = e?.message || "Sign up failed.";
    } finally {
      loading = false;
    }
  }
</script>

<div
  class="min-h-screen bg-gradient-to-br from-black via-surface-50/70 to-black"
>
  <div
    class="mx-auto flex max-w-5xl flex-col items-center justify-center px-6 py-20"
  >
    <div
      class="w-full max-w-md rounded-2xl border border-white/10 bg-white/5 p-8 backdrop-blur"
    >
      <div class="mb-6 text-center">
        <p class="text-sm text-white/60">Create your account</p>
        <h1 class="text-2xl font-semibold text-white">Join Jamarr</h1>
        <p class="text-sm text-white/60">
          Use a username to sign in; email for updates.
        </p>
      </div>

      {#if error}
        <div
          class="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100"
        >
          {error}
        </div>
      {/if}

      <form class="space-y-4" on:submit|preventDefault={handleSignup}>
        <div class="space-y-2">
          <label class="block text-sm text-white/70" for="username"
            >Username</label
          >
          <input
            id="username"
            class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
            name="username"
            autocomplete="username"
            bind:value={username}
            required
          />
        </div>

        <div class="space-y-2">
          <label class="block text-sm text-white/70" for="email">Email</label>
          <input
            id="email"
            class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
            type="email"
            name="email"
            autocomplete="email"
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
            name="display_name"
            autocomplete="nickname"
            bind:value={displayName}
            placeholder="Optional"
          />
        </div>

        <div class="space-y-2">
          <label class="block text-sm text-white/70" for="password"
            >Password</label
          >
          <input
            id="password"
            class="input input-bordered w-full bg-white/5 text-white placeholder:text-white/40"
            type="password"
            name="password"
            autocomplete="new-password"
            bind:value={password}
            required
            minlength="8"
          />
        </div>

        <button
          class="btn w-full normal-case bg-primary text-white hover:bg-primary/90"
          type="submit"
          disabled={loading}
        >
          {#if loading}Creating account...{:else}Create Account{/if}
        </button>
      </form>

      <p class="mt-4 text-center text-sm text-white/60">
        Already have an account?
        <a class="text-primary" href="/login">Log in</a>
      </p>
    </div>
  </div>
</div>
