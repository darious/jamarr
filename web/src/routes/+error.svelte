<script lang="ts">
  import { page } from "$app/stores";

  // Passive error boundary: a load failure used to render a blank page (no
  // boundary existed), which read as "the app is broken". Show a recoverable
  // card instead. Deliberately does NOT redirect — auth/login redirects are
  // owned by the root layout; adding another here races it into a loop.
  $: status = $page.status;

  function reload() {
    location.reload();
  }
</script>

<div class="min-h-screen bg-gradient-to-br from-black via-surface-50/70 to-black">
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
      <h1 class="text-2xl font-semibold text-white">Something went wrong</h1>
      <p class="mt-2 text-sm text-white/60">
        {$page.error?.message || "The page failed to load."}
        {#if status}<span class="text-white/40"> ({status})</span>{/if}
      </p>
      <div class="mt-6 flex items-center justify-center gap-3">
        <button class="btn btn-primary" on:click={reload}>Reload</button>
        <a class="btn btn-ghost text-white/70" href="/login">Log in</a>
      </div>
    </div>
  </div>
</div>
