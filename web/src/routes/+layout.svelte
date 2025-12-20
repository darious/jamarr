<script lang="ts">
  import "../app.postcss";
  import PlayerBar from "$components/PlayerBar.svelte";
  import SearchBar from "$components/SearchBar.svelte";
  import { onDestroy, onMount } from "svelte";
  import {
    loadQueueFromServer,
    playerState,
    refreshRenderers,
    setRenderer,
  } from "$stores/player";
  import { triggerScan } from "$lib/api";

  let rendererList = [];
  let activeRenderer = "local";
  let unsub: (() => void) | undefined;
  let showSettings = false;
  let scanMessage = "";
  let isScanning = false;

  onMount(async () => {
    console.log("[Layout] onMount called");

    // Subscribe first to get immediate state (including default 'local' renderer)
    console.log("[Layout] About to subscribe to playerState");
    unsub = playerState.subscribe((state) => {
      console.log("[Layout] playerState updated, renderers:", state.renderers);
      rendererList = state.renderers || [];
      activeRenderer = state.renderer || "local";
    });

    console.log("[Layout] About to call loadQueueFromServer");
    try {
      await loadQueueFromServer();
    } catch (e) {
      console.error("[Layout] loadQueueFromServer failed:", e);
    }
    console.log("[Layout] loadQueueFromServer completed");

    // Trigger refresh without awaiting the full 5s discovery if we don't want to block anything else
    // But since subscription is active, store updates will just propagate.
    // Use force=false to get immediate cached results (background scan runs on backend)
    refreshRenderers(false).catch((e) =>
      console.error("[Layout] refreshRenderers failed:", e),
    );
  });

  onDestroy(() => {
    if (unsub) unsub();
  });

  const changeRenderer = async (udn: string) => {
    activeRenderer = udn;
    await setRenderer(udn);
  };

  async function scanLibrary() {
    isScanning = true;
    scanMessage = "Scanning...";
    try {
      await triggerScan();
      scanMessage = "Scan started. Reload in a few seconds.";
    } catch (e) {
      scanMessage = "Scan failed.";
    } finally {
      isScanning = false;
      setTimeout(() => {
        scanMessage = "";
        showSettings = false;
      }, 2000);
    }
  }
</script>

<svelte:head>
  <title>Jamarr • Music Controller</title>
  <link rel="icon" href="/assets/logo.png" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link
    rel="preconnect"
    href="https://fonts.gstatic.com"
    crossorigin="anonymous"
  />
  <link
    href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600&display=swap"
    rel="stylesheet"
  />
</svelte:head>

<div class="min-h-screen text-white">
  <header
    class="sticky top-0 z-30 border-b border-white/5 bg-gradient-to-r from-black/70 via-surface-50/80 to-black/70 backdrop-blur-xl"
  >
    <div
      class="mx-auto flex w-full max-w-[1700px] items-center justify-between px-6 py-3"
    >
      <a href="/" class="flex items-center">
        <div
          class="flex h-12 w-12 items-center justify-center overflow-hidden rounded-xl border border-white/10 bg-white/5"
        >
          <img
            src="/assets/logo.png"
            alt="Jamarr"
            class="h-full w-full object-contain p-2"
          />
        </div>
      </a>

      <div class="flex-1 flex justify-center">
        <SearchBar />
      </div>

      <div class="flex items-center gap-3">
        <select
          class="select select-sm border border-white/10 bg-white/5 text-white"
          on:change={(e) => changeRenderer(e.currentTarget.value)}
          value={activeRenderer}
          aria-label="Renderer"
        >
          {#each rendererList as renderer}
            <option
              value={renderer.udn}
              style="background-color: #1f2937; color: white;"
            >
              {renderer.name}
            </option>
          {/each}
        </select>
        <nav class="flex items-center gap-2 text-sm text-white/80">
          <a class="btn btn-ghost btn-sm" href="/artists">Artists</a>
          <a class="btn btn-ghost btn-sm" href="/queue">Queue</a>
          <a class="btn btn-ghost btn-sm" href="/history">History</a>
        </nav>
        <div class="relative">
          <button
            class="btn btn-ghost btn-sm"
            on:click={() => (showSettings = !showSettings)}
            aria-label="Settings"
          >
            <svg
              class="h-5 w-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
              />
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
              />
            </svg>
          </button>
          {#if showSettings}
            <div
              class="absolute right-0 mt-2 w-56 rounded-lg border border-white/10 bg-surface-900 shadow-xl"
            >
              <div class="p-2">
                <button
                  class="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-white/5"
                  on:click={scanLibrary}
                  disabled={isScanning}
                >
                  {isScanning ? "Scanning..." : "Scan Library"}
                </button>
                <button
                  class="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-white/5"
                  on:click={() => window.location.reload()}
                >
                  Refresh Metadata
                </button>
                {#if scanMessage}
                  <p class="px-3 py-2 text-xs text-white/60">{scanMessage}</p>
                {/if}
              </div>
            </div>
          {/if}
        </div>
      </div>
    </div>
  </header>

  <main class="pb-32">
    <slot />
  </main>

  <PlayerBar />
</div>
