<script lang="ts">
  import type { Album, Track } from "$api";
  import { setQueue, addToQueue } from "$stores/player";
  import { goto } from "$app/navigation";

  export let data: {
    artist: string;
    album: string;
    tracks: Track[];
    albumMeta?: Album;
  };

  const artId = () => {
    if (data.albumMeta?.art_id) return data.albumMeta.art_id;
    const withArt = data.tracks.find((t) => t.art_id);
    return withArt?.art_id;
  };

  const totalDuration = () =>
    Math.round(
      (data.tracks || []).reduce(
        (acc, t) => acc + (t.duration_seconds || 0),
        0,
      ) / 60,
    );

  const formatDuration = (seconds?: number | null) => {
    if (!seconds) return "—";
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60)
      .toString()
      .padStart(2, "0");
    return `${mins}:${secs}`;
  };

  function playAll() {
    if (data.tracks?.length) {
      void setQueue(data.tracks, 0);
    }
  }

  function addAllToQueue() {
    if (data.tracks?.length) {
      addToQueue(data.tracks);
    }
  }
</script>

<div class="fixed inset-0 z-0 overflow-hidden pointer-events-none">
  <div
    class="absolute inset-0 bg-cover bg-center blur-3xl opacity-30 scale-110"
    style={`background-image: url('${artId() ? `/art/${artId()}` : "/assets/logo.png"}')`}
  ></div>
  <div
    class="absolute inset-0 bg-gradient-to-b from-surface-900/50 via-surface-900/80 to-surface-900"
  ></div>
</div>

<section
  class="relative z-10 mx-auto flex w-full max-w-[1500px] flex-col gap-8 px-8 py-10"
>
  <div class="grid gap-8 md:grid-cols-[300px,1fr] items-end">
    <div
      class="relative aspect-square w-full max-w-[300px] group rounded-2xl overflow-hidden shadow-2xl"
    >
      <img
        class="h-full w-full object-cover"
        src={artId() ? `/art/${artId()}` : "/assets/logo.png"}
        alt={data.album}
      />

      <!-- Overlay Controls -->
      <div
        class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-4 backdrop-blur-sm"
      >
        <button
          class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-lg scale-90 hover:scale-100 transition-transform"
          title="Play Album"
          on:click={playAll}
        >
          <svg class="h-8 w-8" fill="currentColor" viewBox="0 0 24 24"
            ><path d="M8 5v14l11-7z" /></svg
          >
        </button>
        <button
          class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-lg scale-90 hover:scale-100 transition-transform"
          title="Add to Queue"
          on:click={addAllToQueue}
        >
          <svg class="h-8 w-8" fill="currentColor" viewBox="0 0 24 24"
            ><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg
          >
        </button>
      </div>

      {#if data.albumMeta?.is_hires}
        <img
          src="/assets/logo-hires.png"
          alt="Hi-res"
          class="absolute left-3 bottom-3 h-8 w-8 opacity-90"
        />
      {/if}
    </div>

    <div class="space-y-4 pb-2">
      <p class="pill w-max bg-white/10 text-white/70 backdrop-blur-md">Album</p>
      <h1 class="text-4xl md:text-6xl font-bold tracking-tight">
        {data.album}
      </h1>
      <div class="flex items-center gap-2 text-xl">
        <button
          class="font-medium hover:underline"
          on:click={() => goto(`/artist/${encodeURIComponent(data.artist)}`)}
        >
          {data.artist}
        </button>
        <span class="text-white/40">•</span>
        <span class="text-white/60"
          >{data.albumMeta?.year
            ? data.albumMeta.year.substring(0, 4)
            : "—"}</span
        >
        <span class="text-white/40">•</span>
        <span class="text-white/60"
          >{data.tracks.length} tracks, {totalDuration()} min</span
        >
      </div>
    </div>
  </div>

  <div class="glass-panel divide-y divide-white/5 mt-4">
    {#if data.tracks.length === 0}
      <p class="p-6 text-white/60">No tracks found.</p>
    {:else}
      {#each data.tracks as track, idx}
        <div
          class="group flex items-center gap-4 px-4 py-3 hover:bg-white/5 transition-colors"
        >
          <div class="w-8 text-center text-xs text-white/50">{idx + 1}</div>

          <div
            class="h-12 w-12 flex-shrink-0 rounded bg-white/10 overflow-hidden relative"
          >
            <img
              src={track.art_id ? `/art/${track.art_id}` : "/assets/logo.png"}
              alt="Art"
              class="h-full w-full object-cover"
              on:error={(e) => {
                e.currentTarget.src = "/assets/logo.png";
              }}
            />
            <div
              class="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <button
                class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-sm hover:scale-110 transition-transform"
                on:click|stopPropagation={() => setQueue([track], 0)}
              >
                <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24"
                  ><path d="M8 5v14l11-7z" /></svg
                >
              </button>
            </div>
          </div>

          <div class="flex-1 min-w-0">
            <p
              class="truncate text-sm font-semibold text-white/90 group-hover:text-white"
            >
              {track.title}
            </p>
            <div class="flex items-center gap-2 text-xs text-white/50 mt-0.5">
              <span>{track.artist}</span>
              {#if track.codec}
                <span class="text-white/30">•</span>
                <span class="uppercase">{track.codec}</span>
              {/if}
              {#if track.bit_depth && track.sample_rate_hz}
                <span class="text-white/30">•</span>
                <span
                  >{track.bit_depth}bit / {track.sample_rate_hz / 1000}kHz</span
                >
              {/if}
            </div>
          </div>

          <div class="flex items-center gap-4">
            <button
              class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-xs opacity-0 group-hover:opacity-100 transition-opacity"
              title="Add to Queue"
              on:click|stopPropagation={() => addToQueue([track])}
            >
              <svg class="h-4 w-4" fill="currentColor" viewBox="0 0 24 24"
                ><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg
              >
            </button>
            <div
              class="w-14 text-right text-xs text-white/60 font-medium tabular-nums"
            >
              {formatDuration(track.duration_seconds)}
            </div>
          </div>
        </div>
      {/each}
    {/if}
  </div>
</section>
