<script lang="ts">
  import "../app.postcss";
  import PlayerBar from "$components/PlayerBar.svelte";
  import SearchBar from "$components/SearchBar.svelte";
  import { onDestroy, onMount } from "svelte";
  import { goto } from "$app/navigation";
  import {
    loadQueueFromServer,
    playerState,
    refreshRenderers,
    setRenderer,
  } from "$stores/player";
  import { triggerScan, logout as apiLogout } from "$lib/api";
  import {
    clearUser,
    currentUser,
    hydrateUser,
    isAuthChecked,
    setUser,
  } from "$stores/user";
  import { page } from "$app/stores";
  import { themeAccent, themeMode } from "$stores/theme";

  export let data;

  let rendererList = [];
  let activeRenderer = "local";
  let unsub: (() => void) | undefined;
  let unsubUser: (() => void) | undefined;
  let unsubAuthChecked: (() => void) | undefined;
  let showSettings = false;
  let settingsContainer: HTMLElement;
  let showRenderers = false;
  let renderersContainer: HTMLElement;
  let scanMessage = "";
  let isScanning = false;
  let user = data?.user || null;
  let authChecked = false;
  let isAuthPage = false;

  // Track whether we're on an auth page
  $: isAuthPage =
    $page.url.pathname.startsWith("/login") ||
    $page.url.pathname.startsWith("/signup");

  // Seed auth state from server load to avoid a logged-out flash
  setUser(user);
  isAuthChecked.set(true);

  onMount(async () => {
    console.log("[Layout] onMount called");
    // Subscribe first to get immediate state (including default 'local' renderer)
    console.log("[Layout] About to subscribe to playerState");
    unsub = playerState.subscribe((state) => {
      console.log("[Layout] playerState updated, renderers:", state.renderers);
      rendererList = state.renderers || [];
      activeRenderer = state.renderer || "local";
    });

    unsubUser = currentUser.subscribe((value) => (user = value));
    unsubAuthChecked = isAuthChecked.subscribe(
      (value) => (authChecked = value),
    );
    // If server didn't provide a user, hydrate from the API on the client
    if (!user) {
      hydrateUser().catch((e) => console.error("Failed to hydrate user", e));
    }

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
    if (unsubUser) unsubUser();
    if (unsubAuthChecked) unsubAuthChecked();
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

  async function handleLogout() {
    try {
      await apiLogout();
    } catch (e) {
      console.error("Failed to logout", e);
    } finally {
      clearUser();
      showSettings = false;
      goto("/login");
    }
  }

  function handleWindowClick(e: MouseEvent) {
    if (
      showRenderers &&
      renderersContainer &&
      !renderersContainer.contains(e.target as Node)
    ) {
      showRenderers = false;
    }
    if (
      showSettings &&
      settingsContainer &&
      !settingsContainer.contains(e.target as Node)
    ) {
      showSettings = false;
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

<svelte:window on:click={handleWindowClick} />

<div
  class="min-h-screen text-white"
  data-accent={$themeAccent}
  data-mode={$themeMode}
>
  {#if !isAuthPage}
    <header
      class="sticky top-0 z-30 border-b border-white/5 bg-gradient-to-r from-black/70 via-surface-50/80 to-black/70 backdrop-blur-xl"
    >
      <div
        class="mx-auto flex w-full max-w-[1700px] items-center justify-between px-6 py-3"
      >
        <a href="/" class="flex items-center">
          <img
            src="/assets/logo.png"
            alt="Jamarr"
            class="h-16 w-auto object-contain hover:scale-105 transition-transform duration-200"
          />
        </a>

        <div class="flex-1 flex justify-center">
          <SearchBar />
        </div>

        <div class="flex items-center gap-3">
          <div class="relative" bind:this={renderersContainer}>
            <button
              class="px-4 py-2 text-sm font-normal text-white/80 hover:text-white transition-all border-b-2 border-transparent hover:border-accent min-w-[200px] justify-between flex items-center gap-2"
              on:click={() => {
                showRenderers = !showRenderers;
                if (showRenderers) {
                  refreshRenderers(false).catch((e) =>
                    console.error("[Layout] refreshRenderers failed:", e),
                  );
                }
              }}
              aria-label="Select Renderer"
            >
              <span class="truncate max-w-[180px]">
                {rendererList.find((r) => r.udn === activeRenderer)?.name ||
                  "Select Player"}
              </span>
              <svg
                class="h-4 w-4 opacity-50"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M19 9l-7 7-7-7"
                />
              </svg>
            </button>
            {#if showRenderers}
              <div
                class="absolute right-0 mt-2 w-72 rounded-lg border border-white/10 backdrop-blur-md shadow-xl z-50 max-h-96 overflow-y-auto bg-gradient-to-b from-transparent to-black"
              >
                <div class="p-2 space-y-1">
                  {#each rendererList as renderer}
                    <button
                      class="w-full px-3 py-2 text-left text-sm text-white/80 hover:text-white transition-all border-b border-transparent hover:border-accent flex items-center justify-between {activeRenderer ===
                      renderer.udn
                        ? 'text-white border-accent'
                        : ''}"
                      on:click={() => {
                        changeRenderer(renderer.udn);
                        showRenderers = false;
                      }}
                    >
                      <span class="truncate">{renderer.name}</span>
                      {#if activeRenderer === renderer.udn}
                        <svg
                          class="h-4 w-4 text-primary-400"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            stroke-width="2"
                            d="M5 13l4 4L19 7"
                          />
                        </svg>
                      {/if}
                    </button>
                  {/each}
                </div>
              </div>
            {/if}
          </div>
          <nav class="flex items-center gap-2 text-sm text-white/80">
            <a
              class={`px-4 py-2 text-sm font-normal transition-all border-b-2 ${
                $page.url.pathname.startsWith("/artists") ||
                $page.url.pathname.startsWith("/artist/")
                  ? "text-white border-accent"
                  : "text-white/80 border-transparent hover:text-white hover:border-accent"
              }`}
              href="/artists">Artists</a
            >
            <a
              class={`px-4 py-2 text-sm font-normal transition-all border-b-2 ${
                $page.url.pathname.startsWith("/albums") ||
                $page.url.pathname.startsWith("/album/")
                  ? "text-white border-accent"
                  : "text-white/80 border-transparent hover:text-white hover:border-accent"
              }`}
              href="/albums">Albums</a
            >
            <a
              class={`px-4 py-2 text-sm font-normal transition-all border-b-2 ${
                $page.url.pathname.startsWith("/playlists")
                  ? "text-white border-accent"
                  : "text-white/80 border-transparent hover:text-white hover:border-accent"
              }`}
              href="/playlists">Playlists</a
            >
            <a
              class={`px-4 py-2 text-sm font-normal transition-all border-b-2 ${
                $page.url.pathname.startsWith("/history")
                  ? "text-white border-accent"
                  : "text-white/80 border-transparent hover:text-white hover:border-accent"
              }`}
              href="/history">History</a
            >
          </nav>
          {#if !user && authChecked}
            <div class="hidden md:flex items-center gap-2">
              <a
                class="btn btn-primary btn-sm normal-case font-normal"
                href="/signup">Sign up</a
              >
              <a
                class="btn btn-outline btn-sm normal-case font-normal"
                href="/login">Log in</a
              >
            </div>
          {/if}
          <div class="relative" bind:this={settingsContainer}>
            <button
              class={`p-2 transition-all border-b-2 ${
                $page.url.pathname.startsWith("/settings")
                  ? "text-white border-accent"
                  : "text-white/80 border-transparent hover:text-white hover:border-accent"
              }`}
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
                class="absolute right-0 mt-2 w-56 rounded-lg border border-white/10 bg-black/75 backdrop-blur-md shadow-xl z-50"
              >
                <div class="p-2">
                  {#if user}
                    <div
                      class="rounded-lg border border-white/5 bg-white/5 px-3 py-2 text-xs text-white/80 mb-1"
                    >
                      <div class="font-semibold text-white">
                        {user.display_name}
                      </div>
                      <div class="text-white/60">{user.email}</div>
                    </div>
                    <a
                      class="menu-item"
                      href="/settings/account"
                      on:click={() => (showSettings = false)}
                    >
                      Account Settings
                    </a>
                  {:else}
                    <a
                      class="menu-item"
                      href="/signup"
                      on:click={() => (showSettings = false)}
                    >
                      Create Account
                    </a>
                    <a
                      class="menu-item"
                      href="/login"
                      on:click={() => (showSettings = false)}
                    >
                      Log In
                    </a>
                  {/if}
                  <a
                    class="menu-item"
                    href="/settings/library"
                    on:click={() => (showSettings = false)}
                  >
                    Library Management
                  </a>
                  <a
                    class="menu-item"
                    href="/settings/media-quality"
                    on:click={() => (showSettings = false)}
                  >
                    Media Quality
                  </a>
                  <a
                    class="menu-item"
                    href="/renderers"
                    on:click={() => (showSettings = false)}
                  >
                    Network Renderers
                  </a>
                  {#if user}
                    <button
                      class="menu-item text-red-200"
                      on:click={handleLogout}
                    >
                      Sign Out
                    </button>
                  {/if}
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
  {/if}

  <main class="pb-32">
    <slot />
  </main>

  {#if !isAuthPage}
    <PlayerBar />
  {/if}
</div>
