<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";

  // A load failure used to render a blank page (no error boundary), which read
  // as "the app is broken". This boundary keeps the app usable: an auth failure
  // sends the user to /login, anything else shows a recoverable error card.
  $: status = $page.status;
  $: isAuthError = status === 401 || status === 403;

  onMount(() => {
    if (isAuthError) goto("/login");
  });

  function reload() {
    location.reload();
  }
</script>

{#if !isAuthError}
  <div
    class="min-h-screen bg-gradient-to-br from-black via-surface-50/70 to-black"
  >
    <div
      class="mx-auto flex max-w-5xl flex-col items-center justify-center px-6 py-20 gap-8"
    >
      <img
        src="/assets/logo.png"
        alt="Jamarr logo"
        class="w-full max-w-md drop-shadow-2xl"
      />
      <div
        class="w-full max-w-md rounded-2xl border border-white/10 bg-white/5 p-8 text-center backdrop-blur-sm"
      >
        <h1 class="text-2xl font-semibold text-white">
          Something went wrong
        </h1>
        <p class="mt-2 text-sm text-white/60">
          {$page.error?.message || "The page failed to load."}
        </p>
        <div class="mt-6 flex items-center justify-center gap-3">
          <button
            class="btn btn-primary"
            on:click={reload}
          >
            Reload
          </button>
          <a class="btn btn-ghost text-white/70" href="/">Home</a>
        </div>
      </div>
    </div>
  </div>
{/if}
