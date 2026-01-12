<script lang="ts">
  import type { ChartAlbum } from "$api";
  import { refreshChart, triggerPearlarrDownload, fetchTracks } from "$api";
  import { goto, invalidateAll } from "$app/navigation";
  import { setQueue, addToQueue } from "$stores/player";
  import IconButton from "$lib/components/IconButton.svelte";

  export let data: { chart: ChartAlbum[] };

  let refreshing = false;
  let downloadingMbids = new Set<string>();

  async function handleRefresh() {
    refreshing = true;
    try {
      await refreshChart();
      setTimeout(() => {
        invalidateAll();
        refreshing = false;
      }, 5000);
    } catch (e) {
      console.error(e);
      refreshing = false;
    }
  }

  async function handleDownload(entry: ChartAlbum) {
    const mbid = entry.release_group_mbid || entry.release_mbid;
    if (!mbid || downloadingMbids.has(mbid)) return;

    downloadingMbids.add(mbid);
    downloadingMbids = downloadingMbids;

    try {
      await triggerPearlarrDownload(mbid);
    } catch (e) {
      console.error(e);
      downloadingMbids.delete(mbid);
      downloadingMbids = downloadingMbids;
    }
  }

  async function playChartAlbum(entry: ChartAlbum) {
    if (!entry.local_album_mbid) return;
    try {
      const tracks = await fetchTracks({ albumMbid: entry.local_album_mbid });
      if (tracks.length) {
        await setQueue(tracks, 0);
      }
    } catch (e) {
      console.error("Failed to play album", e);
    }
  }

  async function queueChartAlbum(entry: ChartAlbum) {
    if (!entry.local_album_mbid) return;
    try {
      const tracks = await fetchTracks({ albumMbid: entry.local_album_mbid });
      if (tracks.length) {
        await addToQueue(tracks);
      }
    } catch (e) {
      console.error("Failed to queue album", e);
    }
  }

  let activeFilter: "all" | "missing" | "new" = "all";

  $: displayedChart = data.chart.filter((entry: ChartAlbum) => {
    if (activeFilter === "missing") return !entry.in_library;
    if (activeFilter === "new")
      return entry.status.toLowerCase() === "new entry";
    return true;
  }) as ChartAlbum[];

  function getStatusColor(status: string) {
    switch (status.toLowerCase()) {
      case "new entry":
        return "text-success-500";
      case "reentry":
        return "text-primary-500";
      case "up":
        return "text-success-500";
      case "down":
        return "text-error-500";
      default:
        return "text-muted";
    }
  }

  function toTitleCase(str: string): string {
    return str.replace(
      /\w\S*/g,
      (txt) => txt.charAt(0).toUpperCase() + txt.substr(1).toLowerCase(),
    );
  }

  function handleCardClick(entry: ChartAlbum) {
    if (entry.in_library && entry.local_album_mbid) {
      goto(`/album/${entry.local_album_mbid}`);
    } else if (
      entry.musicbrainz_url &&
      !downloadingMbids.has(
        entry.release_group_mbid || entry.release_mbid || "",
      )
    ) {
      window.open(entry.musicbrainz_url, "_blank");
    }
  }

  function handleKeyDown(e: KeyboardEvent, entry: ChartAlbum) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleCardClick(entry);
    }
  }

  const filters: { label: string; value: "all" | "missing" | "new" }[] = [
    { label: "All", value: "all" },
    { label: "Missing Only", value: "missing" },
    { label: "New Entries", value: "new" },
  ];
</script>

<section
  class="mx-auto flex w-full max-w-[1700px] flex-col gap-6 px-4 md:px-8 py-10"
>
  <div class="flex items-center justify-between">
    <div>
      <p class="text-sm uppercase tracking-wide text-subtle">Top 100</p>
      <h1 class="text-3xl font-bold text-default">Chart</h1>
    </div>
    <button
      class="btn variant-filled-primary"
      disabled={refreshing}
      on:click={handleRefresh}
    >
      {#if refreshing}
        <span class="loading loading-spinner text-white"></span>
      {:else}
        <svg
          class="h-5 w-5 mr-2"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
          />
        </svg>
      {/if}
      Refresh Chart
    </button>
  </div>

  <!-- Filter Tabs -->
  <div class="flex items-center gap-6 border-b border-subtle/20">
    {#each filters as tab}
      <button
        class={`relative py-3 text-sm font-medium transition-all duration-200 border-b-2 -mb-[1.5px] ${
          activeFilter === tab.value
            ? "text-default border-accent"
            : "text-muted border-transparent hover:text-default hover:border-accent"
        }`}
        on:click={() => (activeFilter = tab.value)}
      >
        {tab.label}
      </button>
    {/each}
  </div>

  <div
    class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-6"
  >
    {#each displayedChart as entry (entry.position)}
      {@const title =
        entry.in_library && entry.local_title
          ? entry.local_title
          : toTitleCase(entry.title)}
      {@const artist =
        entry.in_library && entry.local_artist
          ? entry.local_artist
          : toTitleCase(entry.artist)}

      <div class="group relative flex flex-col gap-3">
        <!-- Artwork Card -->
        <div
          class="relative aspect-square rounded-lg overflow-hidden bg-surface-3 shadow-lg transition-transform duration-300 hover:scale-105 border border-transparent hover:border-subtle/30 cursor-pointer text-left w-full outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
          role="button"
          tabindex="0"
          on:click={() => handleCardClick(entry)}
          on:keydown={(e) => handleKeyDown(e, entry)}
        >
          {#if entry.in_library && entry.art_sha1}
            <img
              src="/api/art/file/{entry.art_sha1}?max_size=300"
              alt={title}
              class="w-full h-full object-cover"
              loading="lazy"
              decoding="async"
            />
            <!-- Overlay with Play/Queue -->
            <div
              class="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-3"
            >
              <IconButton
                variant="primary"
                title="Play Album"
                onClick={() => playChartAlbum(entry)}
                stopPropagation={true}
              >
                <svg class="h-6 w-6" fill="currentColor" viewBox="0 0 24 24"
                  ><path d="M8 5v14l11-7z" /></svg
                >
              </IconButton>
              <IconButton
                variant="primary"
                title="Add to Queue"
                onClick={() => queueChartAlbum(entry)}
                stopPropagation={true}
              >
                <svg class="h-6 w-6" fill="currentColor" viewBox="0 0 24 24"
                  ><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg
                >
              </IconButton>
            </div>
          {:else}
            <div
              class="w-full h-full flex flex-col items-center justify-center bg-surface-2 p-0 text-center relative"
            >
              <img
                src="/assets/default-album-placeholder.svg"
                alt="Placeholder"
                class="absolute inset-0 w-full h-full object-cover opacity-50"
              />
              <div class="relative z-10 p-2">
                <span
                  class="text-xs text-subtle font-medium uppercase tracking-widest"
                  >{artist}</span
                >
              </div>
            </div>

            <!-- Pearlarr Download Overlay -->
            <!-- High z-index to ensure it sits on top of everything -->
            <div
              class="absolute inset-0 bg-transparent flex items-center justify-center z-20 opacity-0 group-hover:opacity-100 transition-opacity"
            >
              {#if !downloadingMbids.has(entry.release_group_mbid || entry.release_mbid || "")}
                <!-- Explicit stopPropagation and button type -->
                <button
                  type="button"
                  class="btn btn-primary shadow-xl flex items-center gap-2 px-4 py-2 transition-transform hover:scale-105"
                  on:click|stopPropagation={(e) => {
                    e.stopPropagation();
                    handleDownload(entry);
                  }}
                  title="Download with Pearlarr"
                >
                  <img
                    src="/assets/icon-pearlarr.svg"
                    class="w-5 h-5"
                    alt="Pearlarr"
                  />
                  <span>Download</span>
                </button>
              {:else}
                <div class="bg-black/40 p-3 rounded-full backdrop-blur-sm">
                  <span class="loading loading-spinner text-secondary-500"
                  ></span>
                </div>
              {/if}
            </div>
          {/if}

          <!-- Position Badge (Top Left) -->
          <div
            class="absolute top-2 left-2 flex items-center gap-1.5 pointer-events-none z-10"
          >
            <div
              class="flex items-center justify-center w-8 h-8 rounded-full bg-black text-white font-bold text-sm shadow-lg border border-white/20"
            >
              {entry.position}
            </div>
            {#if downloadingMbids.has(entry.release_group_mbid || entry.release_mbid || "")}
              <div class="badge variant-filled-success shadow-lg text-[10px]">
                Queued
              </div>
            {/if}
          </div>

          <!-- Status (Top Right) -->
          <div class="absolute top-2 right-2 pointer-events-none z-10">
            {#if entry.status !== "steady"}
              <div
                class="badge {getStatusColor(entry.status).replace(
                  'text-',
                  'bg-',
                )}/90 text-surface-900 text-[10px] font-bold shadow-lg backdrop-blur"
              >
                {#if entry.status === "up"}
                  <svg
                    class="w-3 h-3"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    stroke-width="3"><path d="M5 15l7-7 7 7" /></svg
                  >
                {:else if entry.status === "down"}
                  <svg
                    class="w-3 h-3"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    stroke-width="3"><path d="M19 9l-7 7-7-7" /></svg
                  >
                {:else if entry.status === "new entry"}
                  NEW
                {:else if entry.status === "reentry"}
                  RE
                {/if}
              </div>
            {/if}
          </div>
        </div>

        <!-- Metadata -->
        <div class="flex flex-col gap-0.5">
          <a
            class="text-base font-bold text-default truncate hover:underline"
            href={entry.in_library && entry.local_album_mbid
              ? `/album/${entry.local_album_mbid}`
              : "#"}
            {title}
          >
            {title}
          </a>
          <a
            class="text-sm text-muted truncate hover:underline"
            href={entry.artist_mbid
              ? `/artist/${entry.artist_mbid}`
              : `/artist/${encodeURIComponent(artist)}`}
            title={artist}
          >
            {artist}
          </a>

          <div
            class="flex items-center gap-2 mt-1 text-[10px] text-subtle font-medium uppercase tracking-wider opacity-60"
          >
            {#if entry.last_week}
              <span>LW: {entry.last_week}</span>
              <span class="w-0.5 h-0.5 bg-current rounded-full"></span>
            {/if}
            <span>{entry.weeks} Wks</span>
          </div>
        </div>
      </div>
    {/each}

    {#if data.chart.length === 0}
      <div
        class="col-span-full flex flex-col items-center justify-center py-32 text-muted"
      >
        <svg
          class="w-16 h-16 mb-4 opacity-50"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"
          />
        </svg>
        <p class="text-xl font-medium">No chart data loaded</p>
        <p class="text-sm">Click "Refresh Chart" to fetch the latest data</p>
      </div>
    {/if}
  </div>
</section>
