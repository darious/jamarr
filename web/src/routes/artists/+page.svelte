<script lang="ts">
  import type { Artist } from "$lib/api";
  import { getArtUrl } from "$lib/api";
  import { goto } from "$app/navigation";
  import TabButton from "$lib/components/TabButton.svelte";

  export let data: { artists: Artist[]; start: string; index: string[] };

  let artists: Artist[] = data.artists;

  let showAllArtists = false;
  let visibleArtists: Artist[] = artists;
  let activeFilter = data.start;

  // Filters from backend. Ensure '#' is at the start if present.
  let filters: string[] = [];
  $: {
    artists = data.artists;
    activeFilter = data.start;

    const idx = data.index || [];
    const hasHash = idx.includes("#");
    const letters = idx.filter((c) => c !== "#").sort();
    filters = hasHash ? ["#", ...letters] : letters;
  }

  const isPrimaryArtist = (artist: Artist) => {
    if (
      artist.primary_album_count === undefined ||
      artist.primary_album_count === null
    ) {
      return true;
    }
    return artist.primary_album_count > 0;
  };

  $: visibleArtists = showAllArtists
    ? artists
    : artists.filter(isPrimaryArtist);

  function handleFilterClick(filter: string) {
    goto(`?start=${filter}`, { keepFocus: true });
  }
</script>

<section class="mx-auto flex w-full flex-col gap-10 px-8 py-10">
  <div
    class="section-head sticky top-0 z-20 rounded-b-2xl border-b border-subtle bg-surface-50/80 py-4 shadow-lg backdrop-blur-xl"
  >
    <!-- Left title, centre letters fill remaining width, right toggle -->
    <div class="hidden w-full items-center gap-6 md:flex">
      <!-- LEFT: Title -->
      <div class="flex flex-col whitespace-nowrap">
        <p class="text-sm uppercase tracking-wide text-muted">Browse</p>
        <h2 class="text-2xl font-semibold text-default">Artists A–Z</h2>
      </div>

      <!-- CENTRE: Letter filters (no scroll, single line, fills space) -->
      <div class="flex-1">
        <div class="flex w-full items-center justify-between">
          {#each filters as filter}
            <TabButton
              active={activeFilter === filter}
              onClick={() => handleFilterClick(filter)}
              className="w-8 h-8 !px-0 flex items-center justify-center font-mono text-xs"
            >
              {filter}
            </TabButton>
          {/each}
        </div>
      </div>

      <!-- RIGHT: Primary / All -->
      <div class="flex justify-end whitespace-nowrap">
        <div class="flex bg-surface-2 rounded-lg p-1 gap-1">
          <TabButton
            active={!showAllArtists}
            onClick={() => {
              showAllArtists = false;
            }}
            size="sm"
          >
            Primary
          </TabButton>
          <TabButton
            active={showAllArtists}
            onClick={() => {
              showAllArtists = true;
            }}
            size="sm"
          >
            All Artists
          </TabButton>
        </div>
      </div>
    </div>

    <div class="space-y-4 md:hidden">
      <div class="flex flex-col gap-1">
        <p class="text-xs uppercase tracking-wide text-muted">Browse</p>
        <h2 class="text-xl font-semibold text-default">Artists A–Z</h2>
      </div>

      <div class="grid grid-cols-[minmax(0,1fr)_auto] gap-3">
        <label class="min-w-0">
          <span class="mb-1 block text-[11px] uppercase tracking-widest text-subtle">
            Letter
          </span>
          <select
            class="w-full rounded-xl border border-subtle bg-surface-2 px-3 py-3 text-sm text-default"
            bind:value={activeFilter}
            on:change={(e) =>
              handleFilterClick((e.currentTarget as HTMLSelectElement).value)}
          >
            {#each filters as filter}
              <option value={filter}>{filter}</option>
            {/each}
          </select>
        </label>

        <div class="min-w-[128px]">
          <span class="mb-1 block text-[11px] uppercase tracking-widest text-subtle">
            View
          </span>
          <div class="flex rounded-xl bg-surface-2 p-1 gap-1">
            <TabButton
              active={!showAllArtists}
              onClick={() => {
                showAllArtists = false;
              }}
              size="sm"
              className="flex-1 justify-center"
            >
              Primary
            </TabButton>
            <TabButton
              active={showAllArtists}
              onClick={() => {
                showAllArtists = true;
              }}
              size="sm"
              className="flex-1 justify-center"
            >
              All
            </TabButton>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div class="flex flex-col gap-10">
    {#if visibleArtists.length === 0}
      <div class="text-muted text-lg italic py-10 text-center">
        No artists found starting with "{activeFilter}"
        {#if !showAllArtists}
          <br />
          <span class="text-sm"
            >Try switching to "All Artists" to see if there are non-primary
            artists.</span
          >
        {/if}
      </div>
    {:else}
      <div
        class="grid grid-cols-2 gap-4 sm:grid-cols-[repeat(auto-fit,minmax(220px,1fr))] sm:gap-4 lg:[grid-template-columns:repeat(auto-fit,minmax(300px,1fr))]"
      >
        {#each visibleArtists as artist}
          <a
            class="group block cursor-pointer space-y-2 rounded-2xl transition-transform hover:-translate-y-1 focus:outline-none focus:ring-2 focus:ring-primary-400"
            href={`/artist/${artist.mbid}`}
          >
            <div class="flex justify-center">
                <div class="aspect-square w-full max-w-[300px] overflow-hidden rounded-xl">
                <img
                  src={artist.art_sha1
                    ? getArtUrl(artist.art_sha1, 300)
                    : "/assets/default-artist-placeholder.svg"}
                  alt={artist.name}
                  class="h-full w-full rounded-2xl object-cover transition-transform duration-200 group-hover:scale-[1.03]"
                  loading="lazy"
                  decoding="async"
                />
              </div>
            </div>
            <div class="mt-3 space-y-1">
              <p class="line-clamp-1 text-sm font-semibold text-default sm:text-base">
                {artist.name}
              </p>
              <p class="line-clamp-2 text-[11px] text-muted sm:text-xs">
                {artist.bio || "No bio yet."}
              </p>
            </div>
          </a>
        {/each}
      </div>
    {/if}
  </div>
</section>
