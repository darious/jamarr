<script lang="ts">
  import type { Album, Track } from '$api';
  import { setQueue } from '$stores/player';
  import { goto } from '$app/navigation';

  export let data: { artist: string; album: string; tracks: Track[]; albumMeta?: Album };

  const artId = () => {
    if (data.albumMeta?.art_id) return data.albumMeta.art_id;
    const withArt = data.tracks.find((t) => t.art_id);
    return withArt?.art_id;
  };

  const totalDuration = () =>
    Math.round((data.tracks || []).reduce((acc, t) => acc + (t.duration_seconds || 0), 0) / 60);

  const formatDuration = (seconds?: number | null) => {
    if (!seconds) return '—';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60)
      .toString()
      .padStart(2, '0');
    return `${mins}:${secs}`;
  };

  function playAll() {
    if (data.tracks?.length) {
      void setQueue(data.tracks, 0);
    }
  }
</script>

<section class="mx-auto flex w-full max-w-[1500px] flex-col gap-8 px-8 py-10">
  <div class="glass-panel grid gap-6 p-6 md:grid-cols-[260px,1fr]">
    <div class="relative aspect-square w-full max-w-[260px]">
      <img
        class="h-full w-full rounded-2xl object-cover"
        src={artId() ? `/art/${artId()}` : '/assets/logo.png'}
        alt={data.album}
      />
      {#if data.albumMeta?.is_hires}
        <img src="/assets/logo-hires.png" alt="Hi-res" class="absolute right-2 top-2 h-10 w-10" />
      {/if}
    </div>
    <div class="space-y-3">
      <p class="pill w-max bg-white/10 text-white/70">Album</p>
      <h1 class="text-3xl font-semibold">{data.album}</h1>
      <button class="text-primary-200 underline" on:click={() => goto(`/artist/${encodeURIComponent(data.artist)}`)}>
        {data.artist}
      </button>
      <p class="text-sm text-white/60">
        {data.albumMeta?.year ? data.albumMeta.year.substring(0, 4) : '—'} • {data.tracks.length} tracks •
        {totalDuration()} mins
      </p>
      <div class="flex gap-3">
        <button class="btn btn-primary" on:click={playAll}>Play</button>
        <button class="btn btn-ghost" on:click={() => goto(`/artist/${encodeURIComponent(data.artist)}`)}>Artist</button>
      </div>
    </div>
  </div>

  <div class="glass-panel divide-y divide-white/5">
    {#if data.tracks.length === 0}
      <p class="p-6 text-white/60">No tracks found.</p>
    {:else}
      {#each data.tracks as track, idx}
        <div class="flex items-center gap-4 px-4 py-3 hover:bg-white/5">
          <div class="w-6 text-xs text-white/50">{idx + 1}</div>
          <div class="flex-1 min-w-0">
            <p class="truncate text-sm font-semibold">{track.title}</p>
            <p class="text-xs text-white/60">{track.artist}</p>
          </div>
          <div class="hidden items-center gap-2 text-xs text-white/60 md:flex">
            {#if track.codec}<span class="pill bg-white/5 text-white/70">{track.codec}</span>{/if}
            {#if track.sample_rate_hz}<span class="pill bg-white/5 text-white/70">{(track.sample_rate_hz / 1000).toFixed(1)}kHz</span>{/if}
            {#if track.bit_depth}<span class="pill bg-white/5 text-white/70">{track.bit_depth}bit</span>{/if}
          </div>
          <div class="w-14 text-right text-xs text-white/60">{formatDuration(track.duration_seconds)}</div>
          <button class="btn btn-primary btn-xs" on:click={() => setQueue(data.tracks, idx)}>Play</button>
        </div>
      {/each}
    {/if}
  </div>
</section>
