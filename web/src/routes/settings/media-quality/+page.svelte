<script lang="ts">
  import { onMount } from "svelte";
  import type { MediaQualitySummary, EntityItem } from "$lib/api";
  import { fetchMediaQualitySummary, fetchMediaQualityItems } from "$lib/api";

  let summary: MediaQualitySummary | null = null;
  let loading = true;
  let error = "";

  // Modal State
  let showModal = false;
  let modalTitle = "";
  let modalItems: EntityItem[] = [];
  let modalLoading = false;

  async function load() {
    loading = true;
    error = "";
    try {
      summary = await fetchMediaQualitySummary();
    } catch (e: any) {
      error = e?.message || "Failed to load statistics.";
    } finally {
      loading = false;
    }
  }

  async function drillDown(
    category: string,
    filterType: string,
    filterValue?: string,
  ) {
    showModal = true;
    modalLoading = true;
    modalItems = [];

    // Construct title
    const catStr = category === "all" ? "All Artists" : "Primary Artists";
    if (filterType === "total") {
      modalTitle = `${catStr} (Total)`;
    } else if (filterType === "background") {
      modalTitle = `${catStr} with Background Art`;
    } else if (filterType === "source") {
      modalTitle = `${catStr} - Source: ${filterValue}`;
    }

    try {
      modalItems = await fetchMediaQualityItems(
        category,
        filterType,
        filterValue,
      );
    } catch (e) {
      console.error(e);
      modalTitle += " (Error loading items)";
    } finally {
      modalLoading = false;
    }
  }

  function closeModal() {
    showModal = false;
  }

  onMount(load);
</script>

<div
  class="min-h-screen bg-gradient-to-br from-black via-surface-50/70 to-black text-white relative"
>
  <div class="mx-auto max-w-6xl px-6 py-10 space-y-6">
    <div
      class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between"
    >
      <div>
        <p class="text-sm text-white/60">Settings</p>
        <h1 class="text-3xl font-semibold">Library Statistics</h1>
        <p class="text-sm text-white/60">
          Overview of your library metadata and media sources.
        </p>
      </div>
      <div class="flex flex-col items-start gap-3 md:flex-row md:items-center">
        <button
          class="btn btn-sm border border-white/10 bg-white/10 text-white hover:bg-white/20 normal-case"
          on:click={load}
          disabled={loading}
        >
          {#if loading}Refreshing...{:else}Refresh{/if}
        </button>
      </div>
    </div>

    {#if error}
      <div
        class="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-100"
      >
        {error}
      </div>
    {/if}

    {#if summary}
      <div class="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        <!-- Artists Stats -->
        <div
          class="md:col-span-2 lg:col-span-2 rounded-2xl border border-white/10 bg-white/5 p-6 backdrop-blur"
        >
          <div class="flex items-center justify-between mb-6">
            <h2 class="text-lg font-semibold">Artist Statistics</h2>
          </div>

          <div class="grid grid-cols-2 gap-8">
            <!-- All Artists Column -->
            <div class="space-y-4">
              <h3
                class="text-sm font-medium text-white/60 uppercase tracking-wider"
              >
                All Artists
              </h3>

              <div class="flex items-baseline gap-2">
                <button
                  class="text-3xl font-bold text-primary hover:underline"
                  on:click={() => drillDown("all", "total")}
                >
                  {summary.artist_stats.all.total}
                </button>
                <span class="text-sm text-white/50">total</span>
              </div>

              <div class="space-y-2">
                <div
                  class="flex items-center justify-between text-sm text-white/70"
                >
                  <span>With background art</span>
                  <button
                    class="font-medium text-white hover:text-primary hover:underline"
                    on:click={() => drillDown("all", "background")}
                  >
                    {summary.artist_stats.all.with_background}
                  </button>
                </div>
              </div>

              <div class="pt-4 border-t border-white/5">
                <p class="text-xs font-medium text-white/40 mb-3 uppercase">
                  Artwork Source
                </p>
                <div class="space-y-2">
                  {#each Object.entries(summary.artist_stats.all.sources) as [source, count]}
                    <div class="flex items-center justify-between text-sm">
                      <span class="text-white/60 capitalize">{source}</span>
                      <button
                        class="font-medium bg-white/10 px-2 py-0.5 rounded text-white/90 hover:bg-primary/20 hover:text-primary transition-colors"
                        on:click={() => drillDown("all", "source", source)}
                      >
                        {count}
                      </button>
                    </div>
                  {/each}
                </div>
              </div>
            </div>

            <!-- Primary Artists Column -->
            <div class="space-y-4 border-l border-white/10 pl-8">
              <h3
                class="text-sm font-medium text-white/60 uppercase tracking-wider"
              >
                Primary Artists
              </h3>

              <div class="flex items-baseline gap-2">
                <button
                  class="text-3xl font-bold text-primary hover:underline"
                  on:click={() => drillDown("primary", "total")}
                >
                  {summary.artist_stats.primary.total}
                </button>
                <span class="text-sm text-white/50">total</span>
              </div>

              <div class="space-y-2">
                <div
                  class="flex items-center justify-between text-sm text-white/70"
                >
                  <span>With background art</span>
                  <button
                    class="font-medium text-white hover:text-primary hover:underline"
                    on:click={() => drillDown("primary", "background")}
                  >
                    {summary.artist_stats.primary.with_background}
                  </button>
                </div>
              </div>

              <div class="pt-4 border-t border-white/5">
                <p class="text-xs font-medium text-white/40 mb-3 uppercase">
                  Artwork Source
                </p>
                <div class="space-y-2">
                  {#each Object.entries(summary.artist_stats.primary.sources) as [source, count]}
                    <div class="flex items-center justify-between text-sm">
                      <span class="text-white/60 capitalize">{source}</span>
                      <button
                        class="font-medium bg-white/10 px-2 py-0.5 rounded text-white/90 hover:bg-primary/20 hover:text-primary transition-colors"
                        on:click={() => drillDown("primary", "source", source)}
                      >
                        {count}
                      </button>
                    </div>
                  {/each}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    {:else if !loading}
      <div class="py-12 text-center text-white/40">
        <p>No statistics available.</p>
      </div>
    {/if}
  </div>

  <!-- Drill Down Modal -->
  {#if showModal}
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
      on:click={closeModal}
    >
      <div
        class="w-full max-w-lg max-h-[80vh] flex flex-col rounded-2xl border border-white/10 bg-[#16161e] shadow-2xl"
        on:click|stopPropagation
      >
        <div
          class="flex items-center justify-between p-4 border-b border-white/10"
        >
          <h3 class="text-lg font-semibold text-white">{modalTitle}</h3>
          <button
            class="btn btn-sm btn-circle btn-ghost text-white/60"
            on:click={closeModal}>✕</button
          >
        </div>

        <div class="flex-1 overflow-y-auto p-2">
          {#if modalLoading}
            <div class="p-8 text-center text-white/40">Loading items...</div>
          {:else if modalItems.length === 0}
            <div class="p-8 text-center text-white/40">No items found.</div>
          {:else}
            <div class="divide-y divide-white/5">
              {#each modalItems as item}
                <a
                  href={`/artist/${encodeURIComponent(item.name)}`}
                  class="flex items-center gap-3 p-2 hover:bg-white/5 rounded-lg transition-colors group"
                >
                  {#if item.image_url}
                    <img
                      src={item.image_url}
                      alt=""
                      class="w-10 h-10 rounded-full object-cover bg-white/5"
                    />
                  {:else}
                    <div
                      class="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center text-xm text-white/30"
                    >
                      ?
                    </div>
                  {/if}
                  <span
                    class="font-medium text-white/90 group-hover:text-primary transition-colors"
                    >{item.name}</span
                  >
                </a>
              {/each}
            </div>
          {/if}
        </div>
        <div
          class="p-2 border-t border-white/10 text-center text-xs text-white/30"
        >
          Showing {modalItems.length} items
        </div>
      </div>
    </div>
  {/if}
</div>
