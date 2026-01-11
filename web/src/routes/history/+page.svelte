<script lang="ts">
  import { setQueue } from "$stores/player";
  import { goto, invalidateAll } from "$app/navigation";
  import IconButton from "$lib/components/IconButton.svelte";
  import TabButton from "$lib/components/TabButton.svelte";
  let showScopeMenu = false;
  let scopeMenuContainer: HTMLElement | null = null;

  export let data: {
    history: Array<{
      id: number;
      timestamp: string | number;
      client_ip: string;
      client_id: string | null;
      user?: {
        id: number | null;
        username: string | null;
        display_name: string | null;
        email: string | null;
      } | null;
      track: {
        id: number;
        title: string;
        artist: string;
        album: string;
        art_sha1: string | null;
        mb_release_id?: string | null;
        duration_seconds: number;
        codec: string | null;
        bit_depth: number | null;
        sample_rate_hz: number | null;
        date: string | null;
      };
    }>;
    scope: string;
    days: number;
    page: number;
    stats: {
      daily: { day: string; plays: number }[];
      artists: {
        artist: string;
        art_sha1: string | null;
        plays: number;
      }[];
      albums: {
        album: string;
        artist: string;
        art_sha1: string | null;
        mb_release_id?: string | null;
        plays: number;
      }[];
      tracks: {
        id: number;
        title: string;
        artist: string;
        album: string;
        art_sha1: string | null;
        mb_release_id?: string | null;
        plays: number;
      }[];
    };
  };

  let scope = data.scope || "mine";
  let days = data.days || 7;
  $: page = data.page || 1;
  $: hasNextPage = data.history.length === 20; // Assuming limit is 20
  $: dailyMax = Math.max(
    ...(data.stats.daily?.map((d) => Number(d.plays) || 0) || [1]),
    1,
  );

  function formatTime(seconds: number) {
    if (!seconds) return "—";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  }

  function formatTimestamp(timestamp: string | number) {
    const date = new Date(
      typeof timestamp === "number" ? timestamp * 1000 : timestamp,
    );
    return date.toLocaleString();
  }

  function handleImageError(e: Event) {
    const img = e.currentTarget as HTMLImageElement;
    img.src = "/assets/logo.png";
  }

  function handleScopeWindowClick(e: MouseEvent) {
    if (!showScopeMenu) return;
    if (
      scopeMenuContainer &&
      !scopeMenuContainer.contains(e.target as Node)
    ) {
      showScopeMenu = false;
    }
  }

  async function playTrack(entry: (typeof data.history)[0]) {
    // Create a minimal track object for playback
    const track = {
      id: entry.track.id,
      title: entry.track.title,
      artist: entry.track.artist,
      album: entry.track.album,
      art_sha1: entry.track.art_sha1,
      duration_seconds: entry.track.duration_seconds,
      codec: entry.track.codec,
      bit_depth: entry.track.bit_depth,
      sample_rate_hz: entry.track.sample_rate_hz,
      mb_release_id: entry.track.mb_release_id,
      path: "", // Will be fetched by backend
      album_artist: null,
      track_no: null,
      disc_no: null,
      date: entry.track.date,
      bitrate: null,
    };
    await setQueue([track], 0);
  }

  function switchScope(nextScope: string) {
    if (scope === nextScope) return;
    scope = nextScope;
    goto(`/history?scope=${scope}&days=${days}&page=1`, { replaceState: true }); // Reset to page 1
  }

  function updateDays(event: Event) {
    const val = parseInt((event.currentTarget as HTMLInputElement).value, 10);
    if (!Number.isFinite(val)) return;
    days = Math.max(1, Math.min(val, 365));
    goto(`/history?scope=${scope}&days=${days}&page=1`, { replaceState: true }); // Reset to page 1
  }

  function nextPage() {
    if (!hasNextPage) return;
    goto(`/history?scope=${scope}&days=${days}&page=${page + 1}`);
  }

  function prevPage() {
    if (page <= 1) return;
    goto(`/history?scope=${scope}&days=${days}&page=${page - 1}`);
  }
</script>

<svelte:window on:click={handleScopeWindowClick} />

<div class="fixed inset-0 z-0 overflow-hidden pointer-events-none">
  <div class="absolute inset-0 bg-surface-1"></div>
</div>

<section
  class="relative z-10 mx-auto flex w-full max-w-[1700px] flex-col gap-8 px-8 py-10"
>
  <div
    class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between"
  >
    <div class="space-y-2">
      <h1 class="text-4xl md:text-6xl font-bold tracking-tight">History</h1>
    </div>
    <div class="flex items-center gap-4">
      <div class="relative" bind:this={scopeMenuContainer}>
        <button
          class="px-4 py-2 text-sm font-normal text-muted hover:text-default transition-all border-b-2 border-transparent hover:border-accent min-w-[200px] justify-between flex items-center gap-2"
          on:click={() => {
            showScopeMenu = !showScopeMenu;
          }}
          aria-label="Select History Scope"
        >
          <span class="truncate max-w-[170px]">
            {scope === "mine" ? "My History" : "All History"}
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
        {#if showScopeMenu}
          <div
            class="absolute right-0 mt-2 w-56 rounded-lg border border-subtle surface-glass-panel shadow-xl z-50"
          >
            <div class="p-2 space-y-1">
              <button
                class="w-full px-3 py-2 text-left text-sm text-muted hover:text-default transition-all border-b border-transparent hover:border-accent flex items-center justify-between {scope ===
                'mine'
                  ? 'text-default border-accent'
                  : ''}"
                on:click={() => {
                  switchScope("mine");
                  showScopeMenu = false;
                }}
              >
                <span>My History</span>
                {#if scope === "mine"}
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
              <button
                class="w-full px-3 py-2 text-left text-sm text-muted hover:text-default transition-all border-b border-transparent hover:border-accent flex items-center justify-between {scope ===
                'all'
                  ? 'text-default border-accent'
                  : ''}"
                on:click={() => {
                  switchScope("all");
                  showScopeMenu = false;
                }}
              >
                <span>All History</span>
                {#if scope === "all"}
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
            </div>
          </div>
        {/if}
      </div>

      <div class="h-6 w-px bg-white/10 mx-2"></div>

      <TabButton onClick={() => invalidateAll()} title="Refresh History">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          stroke-width="1.5"
          stroke="currentColor"
          class="w-5 h-5"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99"
          />
        </svg>
      </TabButton>
      <div class="flex items-center gap-2 text-sm text-subtle">
        <label for="days" class="hidden md:inline font-medium">Days</label>
        <div class="relative">
          <input
            id="days"
            type="number"
            min="1"
            max="365"
            class="w-16 bg-transparent text-default border-b border-subtle focus:border-accent focus:outline-none text-center pb-1 transition-colors"
            bind:value={days}
            on:change={updateDays}
          />
        </div>
      </div>
    </div>
  </div>

  <!-- Stats -->
  <div class="glass-panel space-y-8 p-6">
    <div class="flex flex-col gap-3">
      <div class="flex items-center justify-between">
        <div>
          <p class="text-sm text-subtle">Playback trend</p>
          <h2 class="text-xl font-semibold text-default">
            Plays per day (last {days} days)
          </h2>
        </div>
      </div>
      {#if data.stats.daily.length === 0}
        <p class="text-muted text-sm">No data.</p>
      {:else}
        {#key `${scope}-${days}-daily`}
          <div class="space-y-2">
            {#each data.stats.daily as dayStat (dayStat.day)}
              <div class="flex items-center gap-3 text-sm text-default/80">
                <span class="w-28 text-muted font-mono">{dayStat.day}</span>
                <div
                  class="flex-1 h-2.5 rounded-full bg-surface-3 overflow-hidden border border-subtle"
                >
                  <div
                    class="h-full rounded-full bg-gradient-to-r from-primary/70 via-primary to-default/80 transition-[width] duration-500"
                    style:width="{(dayStat.plays / dailyMax) * 100}%"
                  ></div>
                </div>
                <span class="w-12 text-right tabular-nums text-muted">
                  {dayStat.plays}
                </span>
              </div>
            {/each}
          </div>
        {/key}
      {/if}
    </div>

    <div class="grid md:grid-cols-3 gap-6">
      <div
        class="rounded-2xl border border-subtle bg-surface-2 p-4 backdrop-blur"
      >
        <h3 class="text-md font-semibold mb-3 text-default">Top Artists</h3>
        {#if data.stats.artists.length === 0}
          <p class="text-muted text-sm">No data.</p>
        {:else}
          <div class="space-y-2 text-sm">
            {#each data.stats.artists as artist (artist.artist)}
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-3 min-w-0">
                  <div
                    class="h-10 w-10 rounded bg-surface-3 overflow-hidden flex-shrink-0"
                  >
                    <img
                      src={artist.art_sha1
                        ? `/api/art/file/${artist.art_sha1}?max_size=50`
                        : "/assets/logo.png"}
                      alt={artist.artist}
                      class="h-full w-full object-cover"
                    />
                  </div>
                  <a
                    class="hover:text-default hover:underline truncate text-default"
                    href={`/artist/${encodeURIComponent(artist.artist)}`}
                  >
                    {artist.artist}
                  </a>
                </div>
                <span class="text-muted tabular-nums">{artist.plays}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
      <div
        class="rounded-2xl border border-subtle bg-surface-2 p-4 backdrop-blur"
      >
        <h3 class="text-md font-semibold mb-3 text-default">Top Albums</h3>
        {#if data.stats.albums.length === 0}
          <p class="text-muted text-sm">No data.</p>
        {:else}
          <div class="space-y-2 text-sm">
            {#each data.stats.albums as album (album.album + album.artist)}
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-3 min-w-0">
                  <div
                    class="h-10 w-10 rounded bg-surface-3 overflow-hidden flex-shrink-0"
                  >
                    <img
                      src={album.art_sha1
                        ? `/api/art/file/${album.art_sha1}?max_size=50`
                        : "/assets/logo.png"}
                      alt={album.album}
                      class="h-full w-full object-cover"
                    />
                  </div>
                  <div class="min-w-0">
                    <a
                      class="hover:text-default text-default hover:underline block truncate"
                      href={album.mb_release_id
                        ? `/album/${album.mb_release_id}`
                        : "#"}
                    >
                      {album.album}
                    </a>
                    <a
                      class="text-muted hover:text-default hover:underline text-xs"
                      href={`/artist/${encodeURIComponent(album.artist)}`}
                    >
                      {album.artist}
                    </a>
                  </div>
                </div>
                <span class="text-muted tabular-nums">{album.plays}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
      <div
        class="rounded-2xl border border-subtle bg-surface-2 p-4 backdrop-blur"
      >
        <h3 class="text-md font-semibold mb-3 text-default">Top Tracks</h3>
        {#if data.stats.tracks.length === 0}
          <p class="text-muted text-sm">No data.</p>
        {:else}
          <div class="space-y-2 text-sm">
            {#each data.stats.tracks as track (track.id)}
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-3 min-w-0">
                  <div
                    class="h-10 w-10 rounded bg-surface-3 overflow-hidden flex-shrink-0"
                  >
                    <img
                      src={track.art_sha1
                        ? `/api/art/file/${track.art_sha1}?max_size=50`
                        : "/assets/logo.png"}
                      alt={track.title}
                      class="h-full w-full object-cover"
                    />
                  </div>
                  <div class="min-w-0">
                    <a
                      class="hover:text-default text-default hover:underline block truncate"
                      href={track.mb_release_id
                        ? `/album/${track.mb_release_id}`
                        : "#"}
                    >
                      {track.title}
                    </a>
                    <a
                      class="text-muted hover:text-default hover:underline text-xs"
                      href={`/artist/${encodeURIComponent(track.artist)}`}
                    >
                      {track.artist}
                    </a>
                  </div>
                </div>
                <span class="text-muted tabular-nums">{track.plays}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    </div>
  </div>

  <div class="glass-panel divide-y divide-subtle">
    {#if data.history.length === 0}
      <div class="p-6 text-muted">No playback history yet.</div>
    {:else}
      {#each data.history as entry}
        <div
          class="group flex items-center gap-4 px-4 py-3 hover:bg-surface-2 transition-colors"
        >
          <!-- Artwork -->
          <div
            class="h-14 w-14 flex-shrink-0 rounded bg-surface-3 overflow-hidden relative"
          >
            <img
              src={entry.track.art_sha1
                ? `/api/art/file/${entry.track.art_sha1}?max_size=60`
                : "/assets/logo.png"}
              alt="Art"
              class="h-full w-full object-cover"
              on:error={handleImageError}
            />
            <div
              class="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <div class="opacity-0 group-hover:opacity-100 transition-opacity">
                <IconButton
                  variant="ghost"
                  onClick={() => playTrack(entry)}
                  title="Play"
                >
                  <svg
                    class="h-6 w-6 ml-0.5 text-white"
                    fill="currentColor"
                    viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg
                  >
                </IconButton>
              </div>
            </div>
          </div>

          <!-- Track Info -->
          <div class="flex-1 min-w-0">
            <p
              class="truncate text-sm font-semibold text-default group-hover:text-default"
            >
              {entry.track.title}
            </p>
            <div
              class="flex items-center gap-2 text-xs text-muted mt-0.5 flex-wrap"
            >
              <a
                href={`/artist/${encodeURIComponent(entry.track.artist)}`}
                class="hover:text-default hover:underline"
                on:click|stopPropagation
              >
                {entry.track.artist}
              </a>
              {#if entry.track.album}
                <span class="text-subtle">•</span>
                <a
                  href={entry.track.mb_release_id
                    ? `/album/${entry.track.mb_release_id}`
                    : "#"}
                  class="hover:text-default hover:underline"
                  on:click|stopPropagation
                >
                  {entry.track.album}
                </a>
              {/if}
              {#if entry.track.codec}
                <span class="text-subtle">•</span>
                <span class="uppercase">{entry.track.codec}</span>
              {/if}
              {#if entry.track.bit_depth && entry.track.sample_rate_hz}
                <span class="text-subtle">•</span>
                <span>
                  {entry.track.bit_depth}bit / {(
                    entry.track.sample_rate_hz / 1000
                  ).toFixed(1)}kHz
                </span>
              {/if}
            </div>
          </div>

          <!-- Timestamp & Client Info -->
          <div class="flex items-center gap-4">
            <div class="flex flex-col items-end gap-1 text-xs text-muted">
              <span class="font-medium">{formatTimestamp(entry.timestamp)}</span
              >
              <div class="flex flex-col items-end text-[11px] text-subtle">
                {#if entry.user}
                  <span>{entry.user.display_name || entry.user.username}</span>
                {:else}
                  <span>Unknown user</span>
                {/if}
                <span>{entry.client_ip}</span>
                <span class="text-[10px] text-muted/60">
                  {entry.client_id || "Unknown Client"}
                </span>
              </div>
            </div>

            <!-- Duration -->
            <div
              class="w-14 text-right text-xs text-muted font-medium tabular-nums"
            >
              {formatTime(entry.track.duration_seconds)}
            </div>
          </div>
        </div>
      {/each}
    {/if}
  </div>

  <!-- Pagination -->
  <div class="flex items-center justify-between p-4 glass-panel">
    <button
      class="px-4 py-2 text-sm font-medium rounded-lg hover:bg-surface-3 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      disabled={page <= 1}
      on:click={prevPage}
    >
      Previous
    </button>
    <span class="text-sm text-subtle">Page {page}</span>
    <button
      class="px-4 py-2 text-sm font-medium rounded-lg hover:bg-surface-3 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      disabled={!hasNextPage}
      on:click={nextPage}
    >
      Next
    </button>
  </div>
</section>
