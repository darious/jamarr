<script lang="ts">
  import { goto } from "$app/navigation";
  import { onDestroy, onMount } from "svelte";
  import { createUser } from "$lib/api";
  import TabButton from "$lib/components/TabButton.svelte";
  import { currentUser, hydrateUser, isAuthChecked } from "$stores/user";

  let user = null;
  let authReady = false;
  let unsubUser: (() => void) | undefined;
  let unsubAuth: (() => void) | undefined;

  let username = "";
  let email = "";
  let displayName = "";
  let password = "";
  let confirmPassword = "";
  let creating = false;
  let message = "";
  let error = "";

  onMount(() => {
    unsubUser = currentUser.subscribe((value) => {
      user = value;
      if (authReady && !user) goto("/login");
      if (authReady && user && !user.is_admin) goto("/");
    });
    unsubAuth = isAuthChecked.subscribe((ready) => {
      authReady = ready;
      if (authReady && !user) goto("/login");
      if (authReady && user && !user.is_admin) goto("/");
    });
    hydrateUser().catch(() => {});
  });

  onDestroy(() => {
    if (unsubUser) unsubUser();
    if (unsubAuth) unsubAuth();
  });

  function resetForm() {
    username = "";
    email = "";
    displayName = "";
    password = "";
    confirmPassword = "";
  }

  async function handleCreateUser() {
    message = "";
    error = "";

    if (password !== confirmPassword) {
      error = "Passwords do not match.";
      return;
    }

    if (password.length < 8) {
      error = "Password must be at least 8 characters.";
      return;
    }

    creating = true;
    try {
      const created = await createUser({
        username,
        email,
        password,
        display_name: displayName || undefined,
      });
      message = `Created ${created.display_name || created.username}.`;
      resetForm();
    } catch (e: any) {
      error = e?.message || "Failed to create user.";
    } finally {
      creating = false;
    }
  }
</script>

<div class="mx-auto max-w-3xl px-4 py-10 md:px-8">
  <div class="mb-8">
    <p class="text-sm text-subtle">Settings</p>
    <h1 class="text-3xl font-semibold">Create User</h1>
  </div>

  <section class="rounded-xl border border-subtle bg-surface-2/70 p-6 shadow-lg">
    {#if message}
      <div
        class="mb-4 rounded-lg border border-green-500/30 bg-green-500/10 px-3 py-2 text-sm text-green-100"
      >
        {message}
      </div>
    {/if}

    {#if error}
      <div
        class="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100"
      >
        {error}
      </div>
    {/if}

    <form class="space-y-5" on:submit|preventDefault={handleCreateUser}>
      <div class="grid gap-5 md:grid-cols-2">
        <div class="space-y-2">
          <label class="block text-sm text-muted" for="new_username"
            >Username</label
          >
          <input
            id="new_username"
            class="input input-bordered w-full"
            name="username"
            autocomplete="off"
            bind:value={username}
            required
          />
        </div>

        <div class="space-y-2">
          <label class="block text-sm text-muted" for="new_email">Email</label>
          <input
            id="new_email"
            class="input input-bordered w-full"
            type="email"
            name="email"
            autocomplete="off"
            bind:value={email}
            required
          />
        </div>
      </div>

      <div class="space-y-2">
        <label class="block text-sm text-muted" for="new_display_name"
          >Display name</label
        >
        <input
          id="new_display_name"
          class="input input-bordered w-full"
          name="display_name"
          autocomplete="off"
          bind:value={displayName}
        />
      </div>

      <div class="grid gap-5 md:grid-cols-2">
        <div class="space-y-2">
          <label class="block text-sm text-muted" for="new_password"
            >Password</label
          >
          <input
            id="new_password"
            class="input input-bordered w-full"
            type="password"
            name="password"
            autocomplete="new-password"
            bind:value={password}
            required
            minlength="8"
          />
        </div>

        <div class="space-y-2">
          <label class="block text-sm text-muted" for="confirm_new_password"
            >Confirm password</label
          >
          <input
            id="confirm_new_password"
            class="input input-bordered w-full"
            type="password"
            name="confirm_password"
            autocomplete="new-password"
            bind:value={confirmPassword}
            required
            minlength="8"
          />
        </div>
      </div>

      <div class="flex justify-end">
        <TabButton type="submit" disabled={creating}>
          {creating ? "Creating..." : "Create User"}
        </TabButton>
      </div>
    </form>
  </section>
</div>
