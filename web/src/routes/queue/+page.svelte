<script lang="ts">
  import { next, playFromQueue, playerState, previous } from '$stores/player';
</script>

<section class="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
  <div class="section-head">
    <div>
      <p class="text-sm uppercase tracking-wide text-white/60">Now playing</p>
      <h1 class="text-2xl font-semibold">Queue</h1>
    </div>
    <div class="flex gap-2">
      <button class="btn btn-ghost btn-sm" on:click={previous} disabled={$playerState.currentIndex <= 0}>Prev</button>
      <button class="btn btn-ghost btn-sm" on:click={next} disabled={$playerState.currentIndex >= $playerState.queue.length - 1}>
        Next
      </button>
    </div>
  </div>

  {#if $playerState.queue.length === 0}
    <div class="glass-panel p-8 text-white/60">Queue is empty. Play an album or track to start.</div>
  {:else}
    <div class="glass-panel divide-y divide-white/5">
      {#each $playerState.queue as track, idx}
        <button
          class={`flex w-full items-center gap-4 px-4 py-3 text-left hover:bg-white/5 ${
            idx === $playerState.currentIndex ? 'bg-white/5' : ''
          }`}
          on:click={() => playFromQueue(idx)}
        >
          <div class="h-10 w-10 rounded-lg bg-white/10 text-center text-xs leading-10">{idx + 1}</div>
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-semibold">{track.title}</p>
            <p class="text-xs text-white/60 truncate">{track.artist} • {track.album}</p>
          </div>
          <div class="text-xs text-white/60 w-20 text-right">
            {track.duration_seconds ? Math.round(track.duration_seconds / 60) + ' min' : ''}
          </div>
        </button>
      {/each}
    </div>
  {/if}
</section>
