<script lang="ts">
  import '../app.postcss';
  import PlayerBar from '$components/PlayerBar.svelte';
  import { onDestroy, onMount } from 'svelte';
  import { loadQueueFromServer, playerState, refreshRenderers, setRenderer } from '$stores/player';

  let rendererList = [];
  let activeRenderer = 'local';
  let unsub: (() => void) | undefined;

  onMount(async () => {
    await refreshRenderers();
    await loadQueueFromServer();
    unsub = playerState.subscribe((state) => {
      rendererList = state.renderers || [];
      activeRenderer = state.renderer || 'local';
    });
  });

  onDestroy(() => {
    if (unsub) unsub();
  });

  const changeRenderer = async (udn: string) => {
    activeRenderer = udn;
    await setRenderer(udn);
  };
</script>

<svelte:head>
  <title>Jamarr • Music Controller</title>
  <link rel="icon" href="/assets/logo.png" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link
    href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600&display=swap"
    rel="stylesheet"
  />
</svelte:head>

<div class="min-h-screen text-white">
  <header class="sticky top-0 z-30 border-b border-white/5 bg-gradient-to-r from-black/70 via-surface-50/80 to-black/70 backdrop-blur-xl">
    <div class="mx-auto flex w-full max-w-[1700px] items-center justify-between px-6 py-3">
      <a href="/" class="flex items-center gap-2 text-lg font-semibold tracking-tight">
        <div class="flex h-9 w-9 items-center justify-center overflow-hidden rounded-xl border border-white/10 bg-white/5">
          <img src="/assets/logo.png" alt="Jamarr" class="h-full w-full object-contain p-1.5" />
        </div>
        <span class="text-base">Jamarr</span>
      </a>
      <div class="flex items-center gap-3">
        <select
          class="select select-sm border border-white/10 bg-white/5"
          on:change={(e) => changeRenderer(e.currentTarget.value)}
          value={activeRenderer}
          aria-label="Renderer"
        >
          {#each rendererList as renderer}
            <option value={renderer.udn}>{renderer.name}</option>
          {/each}
        </select>
        <nav class="flex items-center gap-2 text-sm text-white/80">
          <a class="btn btn-ghost btn-sm" href="/">Artists</a>
          <a class="btn btn-ghost btn-sm" href="/queue">Queue</a>
        </nav>
      </div>
    </div>
  </header>

  <main class="pb-32">
    <slot />
  </main>

  <PlayerBar />
</div>
