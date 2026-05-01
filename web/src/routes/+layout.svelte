<script lang="ts">
  import "../app.css";
  import PlayerBar from "$components/PlayerBar.svelte";
  import SearchBar from "$components/SearchBar.svelte";
  import DownloadManager from "$components/DownloadManager.svelte";
  import {
    getSettingsMenuItems,
    shouldShowAdminControls,
  } from "$lib/settings-menu";
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
  import { initializeAuth } from "$lib/stores/auth";
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
  let showMobileMenu = false;
  let showMobileSearch = false;
  let scanMessage = "";
  let isScanning = false;
  let user = data?.user || null;
  let authChecked = false;
  let isAuthPage = false;
  let activeRendererItem: any = null;
  let authLoading = true;  // Add loading state
  let renderersLoading = false;
  let appInitialized = false;
  let appInitializing = false;
  let rendererPollInterval: ReturnType<typeof setInterval> | undefined;

  const navItems = [
    { href: "/artists", label: "Artists", active: (pathname: string) => pathname.startsWith("/artists") || pathname.startsWith("/artist/") },
    { href: "/charts", label: "Chart", active: (pathname: string) => pathname.startsWith("/charts") || pathname.startsWith("/album/") },
    { href: "/discovery", label: "Discovery", active: (pathname: string) => pathname.startsWith("/discovery") },
    { href: "/playlists", label: "Playlists", active: (pathname: string) => pathname.startsWith("/playlists") },
    { href: "/history", label: "History", active: (pathname: string) => pathname.startsWith("/history") },
  ];

  const DEFAULT_RENDERER_ICON = "/assets/icon-renderer.svg";
  const LOCAL_RENDERER_ICON = "/assets/icon-browser.svg";

  function getRendererFallback(renderer: any): string {
    if (!renderer) return DEFAULT_RENDERER_ICON;
    if (renderer.type === "local" || renderer.udn?.startsWith("local")) {
      return LOCAL_RENDERER_ICON;
    }
    return DEFAULT_RENDERER_ICON;
  }

  function getRendererIcon(renderer: any): string {
    if (renderer?.icon_url) return renderer.icon_url;
    return getRendererFallback(renderer);
  }

  function rendererKind(renderer: any): string {
    const raw = renderer?.kind || renderer?.type || renderer?.renderer_id?.split(":")[0] || "";
    if (raw === "cast" || raw === "chromecast") return "cast";
    if (raw === "upnp" || renderer?.udn?.startsWith("uuid:")) return "upnp";
    if (raw === "local" || renderer?.udn?.startsWith("local:")) return "local";
    return raw || "unknown";
  }

  function rendererKindLabel(renderer: any): string {
    const kind = rendererKind(renderer);
    if (kind === "cast") {
      const castType = renderer?.cast_type;
      if (!castType || castType === "cast") return "Cast";
      return `Cast ${castType}`;
    }
    if (kind === "upnp") return "UPnP";
    if (kind === "local") return "Local";
    return kind.toUpperCase();
  }

  function rendererKindClass(renderer: any): string {
    const kind = rendererKind(renderer);
    if (kind === "cast") return "border-sky-400/40 bg-sky-500/15 text-sky-300";
    if (kind === "upnp") return "border-emerald-400/40 bg-emerald-500/15 text-emerald-300";
    if (kind === "local") return "border-zinc-400/30 bg-zinc-500/15 text-zinc-300";
    return "border-subtle bg-surface-3 text-muted";
  }

  // Track whether we're on an auth page
  $: isAuthPage = $page.url.pathname.startsWith("/login");
  $: activeRendererItem = rendererList.find((r) => r.udn === activeRenderer);
  $: isAdmin = shouldShowAdminControls(user);
  $: settingsMenuItems = getSettingsMenuItems(user);
  $: if (isAuthPage) {
    showMobileMenu = false;
    showMobileSearch = false;
  }

  // Don't seed auth state here - wait for client-side initialization

  async function initializeAppShell() {
    if (appInitialized || appInitializing || isAuthPage) return;
    appInitializing = true;
    authLoading = true;

    const initResult = await initializeAuth().catch((e) => {
      console.error("[Layout] initializeAuth error:", e);
      return false;
    });

    const hydratedUser = await hydrateUser().catch((e) => {
      console.error("[Layout] hydrateUser error:", e);
      return null;
    });

    if (!hydratedUser && !isAuthPage) {
      authLoading = false;
      appInitializing = false;
      goto("/login");
      return;
    }

    authLoading = false;

    if (!unsub) {
      unsub = playerState.subscribe((state) => {
        rendererList = state.renderers || [];
        activeRenderer = state.renderer || "";
      });
    }

    try {
      await loadQueueFromServer();
    } catch (e) {
      console.error("[Layout] loadQueueFromServer failed:", e);
    }

    refreshRenderers(false).catch((e) =>
      console.error("[Layout] refreshRenderers failed:", e),
    );

    if (!rendererPollInterval) {
      rendererPollInterval = setInterval(() => {
        refreshRenderers(false).catch((e) =>
          console.error("[Layout] Periodic refreshRenderers failed:", e),
        );
      }, 10000);
    }

    appInitialized = true;
    appInitializing = false;
  }

  onMount(() => {
    unsubUser = currentUser.subscribe((value) => (user = value));
    unsubAuthChecked = isAuthChecked.subscribe((value) => (authChecked = value));

    if (isAuthPage) {
      authLoading = false;
    } else {
      initializeAppShell();
    }
  });

  $: if (!isAuthPage && !appInitialized && !appInitializing) {
    initializeAppShell();
  }

  onDestroy(() => {
    if (unsub) unsub();
    if (unsubUser) unsubUser();
    if (unsubAuthChecked) unsubAuthChecked();
    if (rendererPollInterval) clearInterval(rendererPollInterval);
  });

  const changeRenderer = async (udn: string) => {
    activeRenderer = udn;
    renderersLoading = true;
    try {
      await setRenderer(udn);
    } finally {
      renderersLoading = false;
    }
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

  $: if (typeof document !== "undefined") {
    document.body.dataset.theme = $themeMode;
    document.body.dataset.accent = $themeAccent;
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

<!-- Show loading state while checking auth -->
{#if authLoading && !isAuthPage}
  <div class="min-h-screen flex items-center justify-center bg-gradient-to-br from-black via-surface-50/70 to-black">
    <div class="text-center">
      <div class="animate-spin rounded-full h-16 w-16 border-b-2 border-primary mx-auto mb-4"></div>
      <p class="text-muted">Loading...</p>
    </div>
  </div>
{:else}
<div class="min-h-screen text-default">
  {#if !isAuthPage}
    <header
      class="sticky top-0 z-30 border-b border-white/5 bg-black/10 backdrop-blur-xl"
    >
      <div
        class="mx-auto hidden w-full max-w-[1700px] items-center justify-between px-6 py-3 md:flex"
      >
        <a href="/" class="flex items-center">
          <img
            src="/assets/logo.png"
            alt="Jamarr"
            class="h-16 w-auto object-contain hover:scale-105 transition-transform duration-200"
          />
        </a>

        <div class="flex-1 flex justify-center px-4">
          <SearchBar className="mx-4" />
        </div>

          <div class="flex items-center gap-3">
          {#if isAdmin}
          <div class="relative" bind:this={renderersContainer}>
            <button
              class="px-4 py-2 text-sm font-normal text-muted hover:text-default transition-all border-b-2 border-transparent hover:border-accent min-w-[200px] justify-between flex items-center gap-2 disabled:opacity-50"
              disabled={renderersLoading}
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
              <span class="flex items-center gap-2 min-w-0">
                <img
                  class="h-[30px] w-[30px] rounded-xs object-contain"
                  src={getRendererIcon(activeRendererItem)}
                  alt=""
                  loading="lazy"
                  on:error={(e) => {
                    (e.currentTarget as HTMLImageElement).src =
                      getRendererFallback(activeRendererItem);
                  }}
                />
                <span class="truncate max-w-[170px]">
                  {activeRendererItem?.name || "Select Player"}
                </span>
                {#if activeRendererItem}
                  <span
                    class={`hidden shrink-0 rounded-sm border px-1.5 py-0.5 text-[10px] font-semibold uppercase leading-none tracking-wide sm:inline-flex ${rendererKindClass(activeRendererItem)}`}
                  >
                    {rendererKindLabel(activeRendererItem)}
                  </span>
                {/if}
              </span>
              <svg
                class={`h-4 w-4 opacity-50 ${renderersLoading ? "animate-pulse" : ""}`}
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
                class="absolute right-0 mt-2 w-72 rounded-lg border border-subtle surface-glass-panel shadow-xl z-50 max-h-96 overflow-y-auto"
              >
                <div class="p-2 space-y-1">
                  {#each rendererList as renderer}
                    <button
                      class="w-full px-3 py-2 text-left text-sm text-muted hover:text-default transition-all border-b border-transparent hover:border-accent flex items-center justify-between {activeRenderer ===
                      renderer.udn
                        ? 'text-default border-accent'
                        : ''}"
                      disabled={renderersLoading}
                      on:click={() => {
                        changeRenderer(renderer.udn);
                        showRenderers = false;
                      }}
                    >
                      <span class="flex items-center gap-2 min-w-0">
                        <img
                          class="h-[30px] w-[30px] rounded-xs object-contain"
                          src={getRendererIcon(renderer)}
                          alt=""
                          loading="lazy"
                          on:error={(e) => {
                            (e.currentTarget as HTMLImageElement).src =
                              getRendererFallback(renderer);
                          }}
                        />
                        <span class="min-w-0 flex-1 truncate">{renderer.name}</span>
                        <span
                          class={`shrink-0 rounded-sm border px-1.5 py-0.5 text-[10px] font-semibold uppercase leading-none tracking-wide ${rendererKindClass(renderer)}`}
                        >
                          {rendererKindLabel(renderer)}
                        </span>
                      </span>
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
          {/if}
          <nav class="flex items-center gap-2 text-sm text-muted">
            {#each navItems as item}
              <a
                class={`px-4 py-2 text-sm font-normal transition-all border-b-2 ${
                  item.active($page.url.pathname)
                    ? "text-default border-accent"
                    : "text-muted border-transparent hover:text-default hover:border-accent"
                }`}
                href={item.href}
              >
                {item.label}
              </a>
            {/each}
          </nav>
          {#if !user && authChecked}
            <div class="hidden md:flex items-center gap-2">
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
                  ? "text-default border-accent"
                  : "text-muted border-transparent hover:text-default hover:border-accent"
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
                class="absolute right-0 mt-2 w-56 rounded-lg border border-subtle surface-glass-panel shadow-xl z-50"
              >
                <div class="p-2">
                  {#if user}
                    <div
                      class="rounded-lg border border-subtle bg-surface-2 px-3 py-2 text-xs text-muted mb-1"
                    >
                      <div class="font-semibold text-default">
                        {user.display_name}
                      </div>
                      <div class="text-subtle">{user.email}</div>
                    </div>
                  {/if}
                  {#each settingsMenuItems as item}
                    <a
                      class="menu-item"
                      href={item.href}
                      on:click={() => (showSettings = false)}
                    >
                      {item.label}
                    </a>
                  {/each}
                  {#if user}
                    <button
                      class="menu-item text-red-400 hover:text-red-500"
                      on:click={handleLogout}
                    >
                      Sign Out
                    </button>
                  {/if}
                  {#if scanMessage}
                    <p class="px-3 py-2 text-xs text-muted">{scanMessage}</p>
                  {/if}
                </div>
              </div>
            {/if}
          </div>
        </div>
      </div>

      <div class="mx-auto flex w-full max-w-[1700px] flex-col px-4 py-3 md:hidden">
        <div class="flex items-center justify-between gap-3">
          <a href="/" class="flex min-w-0 items-center">
            <img
              src="/assets/logo.png"
              alt="Jamarr"
              class="h-12 w-auto object-contain"
            />
          </a>

          <div class="flex items-center gap-2">
            <button
              class="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-muted transition-colors hover:text-default"
              aria-label="Search"
              on:click={() => {
                showMobileSearch = true;
                showMobileMenu = false;
              }}
            >
              <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </button>
            {#if isAdmin}
            <button
              class="inline-flex min-w-[120px] items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-muted transition-colors hover:text-default disabled:opacity-50"
              disabled={renderersLoading}
              aria-label="Select Renderer"
              on:click={() => {
                showRenderers = !showRenderers;
                showMobileMenu = false;
                if (showRenderers) {
                  refreshRenderers(false).catch((e) =>
                    console.error("[Layout] refreshRenderers failed:", e),
                  );
                }
              }}
            >
              <img
                class="h-6 w-6 rounded-xs object-contain"
                src={getRendererIcon(activeRendererItem)}
                alt=""
                loading="lazy"
                on:error={(e) => {
                  (e.currentTarget as HTMLImageElement).src =
                    getRendererFallback(activeRendererItem);
                }}
              />
              <span class="max-w-[72px] truncate text-left">
                {activeRendererItem?.name || "Player"}
              </span>
              {#if activeRendererItem}
                <span
                  class={`hidden shrink-0 rounded-sm border px-1.5 py-0.5 text-[10px] font-semibold uppercase leading-none tracking-wide sm:inline-flex ${rendererKindClass(activeRendererItem)}`}
                >
                  {rendererKindLabel(activeRendererItem)}
                </span>
              {/if}
            </button>
            {/if}
            <button
              class="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-muted transition-colors hover:text-default"
              aria-label="Menu"
              on:click={() => {
                showMobileMenu = !showMobileMenu;
                showMobileSearch = false;
                showRenderers = false;
              }}
            >
              <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d={showMobileMenu ? "M6 18L18 6M6 6l12 12" : "M4 6h16M4 12h16M4 18h16"} />
              </svg>
            </button>
          </div>
        </div>

        {#if showRenderers && isAdmin}
          <div class="mt-3 rounded-2xl border border-subtle surface-glass-panel shadow-xl">
            <div class="max-h-80 overflow-y-auto p-2 space-y-1">
              {#each rendererList as renderer}
                <button
                  class="flex w-full items-center justify-between rounded-xl px-3 py-3 text-left text-sm transition-all hover:bg-white/5 {activeRenderer === renderer.udn ? 'text-default border border-accent/40 bg-accent/10' : 'text-muted border border-transparent'}"
                  disabled={renderersLoading}
                  on:click={() => {
                    changeRenderer(renderer.udn);
                    showRenderers = false;
                  }}
                >
                  <span class="flex min-w-0 items-center gap-3">
                    <img
                      class="h-8 w-8 rounded-xs object-contain"
                      src={getRendererIcon(renderer)}
                      alt=""
                      loading="lazy"
                      on:error={(e) => {
                        (e.currentTarget as HTMLImageElement).src =
                          getRendererFallback(renderer);
                      }}
                    />
                    <span class="min-w-0 flex-1 truncate">{renderer.name}</span>
                    <span
                      class={`shrink-0 rounded-sm border px-1.5 py-0.5 text-[10px] font-semibold uppercase leading-none tracking-wide ${rendererKindClass(renderer)}`}
                    >
                      {rendererKindLabel(renderer)}
                    </span>
                  </span>
                  {#if activeRenderer === renderer.udn}
                    <svg class="h-4 w-4 text-primary-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                    </svg>
                  {/if}
                </button>
              {/each}
            </div>
          </div>
        {/if}

        {#if showMobileMenu}
          <div class="mt-3 rounded-2xl border border-subtle surface-glass-panel p-3 shadow-xl">
            <nav class="grid grid-cols-2 gap-2">
              {#each navItems as item}
                <a
                  class={`rounded-xl px-3 py-3 text-sm font-medium transition-colors ${
                    item.active($page.url.pathname)
                      ? "bg-accent/15 text-default border border-accent/40"
                      : "bg-white/5 text-muted border border-transparent hover:text-default"
                  }`}
                  href={item.href}
                  on:click={() => (showMobileMenu = false)}
                >
                  {item.label}
                </a>
              {/each}
            </nav>

            <div class="mt-3 space-y-2">
              {#if user}
                <div class="rounded-xl border border-subtle bg-surface-2 px-3 py-3 text-sm">
                  <div class="font-semibold text-default">{user.display_name}</div>
                  <div class="text-subtle text-xs">{user.email}</div>
                </div>
              {/if}

              {#each settingsMenuItems as item}
                <a class="menu-item" href={item.href} on:click={() => (showMobileMenu = false)}>{item.label}</a>
              {/each}
              {#if user}
                <button class="menu-item text-red-400 hover:text-red-500" on:click={handleLogout}>Sign Out</button>
              {/if}
              {#if scanMessage}
                <p class="px-3 py-2 text-xs text-muted">{scanMessage}</p>
              {/if}
            </div>
          </div>
        {/if}
      </div>
    </header>

    {#if showMobileSearch}
      <div class="fixed inset-0 z-[70] md:hidden">
        <div
          class="absolute inset-0 bg-black/70 backdrop-blur-xs"
          role="button"
          tabindex="0"
          aria-label="Close search"
          on:click={() => (showMobileSearch = false)}
          on:keydown={(e) => {
            if (e.key === "Enter" || e.key === " " || e.key === "Escape") {
              showMobileSearch = false;
            }
          }}
        ></div>
        <div class="absolute inset-x-0 top-0 max-h-full overflow-y-auto border-b border-white/10 bg-[rgb(10_12_18_/_96%)] px-4 pb-6 pt-4 shadow-2xl">
          <SearchBar mobile={true} autoFocus={true} onClose={() => (showMobileSearch = false)} />
        </div>
      </div>
    {/if}
  {/if}

  <main class="pb-32">
    <slot />
  </main>

  {#if !isAuthPage && isAdmin}
    <DownloadManager />
    <PlayerBar />
  {/if}
</div>
{/if}
