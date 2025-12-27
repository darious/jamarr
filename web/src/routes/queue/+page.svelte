<script lang="ts">
  import { next, playFromQueue, playerState, previous } from "$stores/player";

  function formatTime(seconds: number) {
    if (!seconds || isNaN(seconds)) return "0:00";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  }
</script>

<section class="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
  <div class="section-head">
    <div>
      <p class="text-sm uppercase tracking-wide text-white/60">Now playing</p>
      <h1 class="text-2xl font-semibold">Queue</h1>
    </div>
    <div class="flex gap-2">
      <button
        class="btn btn-ghost btn-sm"
        on:click={previous}
        disabled={$playerState.current_index <= 0}>Prev</button
      >
      <button
        class="btn btn-ghost btn-sm"
        on:click={next}
        disabled={$playerState.current_index >= $playerState.queue.length - 1}
      >
        Next
      </button>
    </div>
  </div>

  {#if $playerState.queue.length === 0}
    <div class="glass-panel p-8 text-white/60">
      Queue is empty. Play an album or track to start.
    </div>
  {:else}
    <div class="glass-panel divide-y divide-white/5">
      {#each $playerState.queue as track, idx}
        <button
          class={`flex w-full items-center gap-4 px-4 py-3 text-left hover:bg-white/5 ${
            idx === $playerState.current_index ? "bg-white/5" : ""
          }`}
          on:click={() => playFromQueue(idx)}
        >
          <div class="w-8 text-center text-xs text-white/50">{idx + 1}</div>
          <div
            class="h-12 w-12 flex-shrink-0 rounded bg-white/10 overflow-hidden"
          >
            <img
              src={track.art_sha1 ? `/api/art/file/${track.art_sha1}?max_size=50` : "/assets/logo.png"}
              alt="Art"
              class="h-full w-full object-cover"
              on:error={(e) => {
                const target = e.currentTarget;
                if (target instanceof HTMLImageElement)
                  target.src = "/assets/logo.png";
              }}
            />
          </div>
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-semibold">{track.title}</p>
            <div class="text-xs text-white/60 truncate flex items-center gap-1">
              <a
                href={`/artist/${encodeURIComponent(track.artist)}`}
                class="hover:text-white hover:underline"
                on:click|stopPropagation
              >
                {track.artist}
              </a>
              <span>•</span>
              <a
                href={`/album/${encodeURIComponent(track.artist)}/${encodeURIComponent(track.album)}`}
                class="hover:text-white hover:underline"
                on:click|stopPropagation
              >
                {track.album}
              </a>
            </div>
            <div class="flex items-center gap-2 text-xs text-white/40 mt-0.5">
              {#if track.codec}
                <span class="uppercase">{track.codec}</span>
              {/if}
              {#if track.bit_depth && track.sample_rate_hz}
                <span>•</span>
                <span
                  >{track.bit_depth}bit / {track.sample_rate_hz / 1000}kHz</span
                >
              {/if}
            </div>
          </div>
          <div class="text-xs text-white/60 w-20 text-right">
            {formatTime(track.duration_seconds)}
          </div>
        </button>
      {/each}
    </div>
  {/if}
</section>
