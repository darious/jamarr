<script lang="ts">
  import type { Artist } from '$api';
  import { triggerScan } from '$api';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  export let data: { artists: Artist[] };

  let isScanning = false;
  let scanMessage = '';
  let artists: Artist[] = data.artists;

  onMount(() => {
    artists = data.artists || [];
  });

  const grouped = () => {
    const buckets: Record<string, Artist[]> = {};
    artists.forEach((artist) => {
      const char = (artist.sort_name || artist.name || '#').charAt(0).toUpperCase();
      const key = /[A-Z]/.test(char) ? char : '#';
      buckets[key] = buckets[key] || [];
      buckets[key].push(artist);
    });
    return Object.entries(buckets).sort((a, b) => a[0].localeCompare(b[0]));
  };

  async function scanLibrary() {
    isScanning = true;
    scanMessage = 'Starting scan...';
    try {
      await triggerScan();
      scanMessage = 'Scan kicked off. Reload in a few seconds to see updates.';
    } catch (e) {
      scanMessage = 'Scan failed to start.';
    } finally {
      isScanning = false;
    }
  }
</script>

<section class="mx-auto flex w-full max-w-[1700px] flex-col gap-10 px-8 py-10">
  <div class="hero-gradient rounded-2xl border border-white/5 p-7 shadow-glow">
    <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
      <div class="max-w-2xl space-y-3">
        <p class="pill w-max bg-primary-500/10 text-primary-100">UPnP controller</p>
        <h1 class="text-3xl font-semibold leading-tight md:text-4xl">Browse, play, and cast instantly.</h1>
        <p class="text-base text-white/70">
          Jump through artists and albums, stream locally or to a UPnP renderer. Fast UI, no fluff.
        </p>
        <div class="flex flex-wrap gap-3">
          <button class="btn btn-primary" on:click={scanLibrary} disabled={isScanning}>
            {isScanning ? 'Scanning…' : 'Scan library'}
          </button>
          {#if scanMessage}
            <span class="text-sm text-white/70">{scanMessage}</span>
          {/if}
        </div>
      </div>
    </div>
  </div>

  <div class="section-head">
    <div>
      <p class="text-sm uppercase tracking-wide text-white/60">Browse</p>
      <h2 class="text-2xl font-semibold">Artists A–Z</h2>
    </div>
    <div class="flex flex-wrap gap-2">
      {#each grouped() as [letter]}
        <a href={`#group-${letter}`} class="pill hover:bg-white/10">{letter}</a>
      {/each}
    </div>
  </div>

  <div class="flex flex-col gap-10">
    {#each grouped() as [letter, list]}
      <div id={`group-${letter}`} class="space-y-4">
        <div class="flex items-center gap-3">
          <div class="h-10 w-10 rounded-xl border border-white/10 bg-white/5 text-center text-xl font-semibold leading-10">
            {letter}
          </div>
          <div class="text-sm text-white/60">{list.length} artists</div>
        </div>

        <div class="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(260px,1fr))]">
          {#each list as artist}
            <a class="grid-card block cursor-pointer focus:outline-none focus:ring-2 focus:ring-primary-400" href={`/artist/${encodeURIComponent(artist.name)}`}>
              <div class="flex items-center gap-3">
                <img
                  class="h-14 w-14 rounded-xl border border-white/10 object-cover"
                  src={artist.image_url || '/assets/default-artist.svg'}
                  alt={artist.name}
                />
                <div>
                  <p class="text-lg font-semibold">{artist.name}</p>
                  <p class="text-xs text-white/60 line-clamp-2">{artist.bio || 'No bio yet.'}</p>
                </div>
              </div>
              {#if artist.top_tracks && artist.top_tracks.length}
                <div class="mt-4 space-y-1 text-xs text-white/70">
                  <p class="font-semibold text-white/80">Top tracks</p>
                  <div class="grid grid-cols-2 gap-2">
                    {#each artist.top_tracks.slice(0, 4) as track}
                      <div class="truncate rounded-lg bg-white/5 px-2 py-1">{track.name}</div>
                    {/each}
                  </div>
                </div>
              {/if}
            </a>
          {/each}
        </div>
      </div>
    {/each}
  </div>
</section>
