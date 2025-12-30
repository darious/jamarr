<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import { playerState, playFromQueue } from "$stores/player";

  const dispatch = createEventDispatcher();

  export let visible = false;

  const formatTime = (seconds: number | null | undefined) => {
    if (!seconds || isNaN(seconds)) return "0:00";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  };

  const formatTech = (track: any) => {
    const parts: string[] = [];
    if (track?.codec) parts.push(String(track.codec).toUpperCase());
    if (track?.bit_depth && track?.sample_rate_hz) {
      parts.push(`${track.bit_depth}bit / ${Math.round(track.sample_rate_hz / 1000)}kHz`);
    }
    if (track?.bitrate) {
      parts.push(`${Math.round(track.bitrate / 1000)}kbps`);
    }
    return parts.join(" • ");
  };

  const close = () => dispatch("close");
  const clear = () => dispatch("clear");
</script>

<svelte:window
  on:keydown={(e) => {
    if (!visible) return;
    if (e.key === "Escape") close();
  }}
/>

{#if visible}
  <!-- Click-away overlay -->
  <div
    class="fixed inset-0 z-[55]"
    role="button"
    aria-label="Close queue"
    tabindex="0"
    on:click={close}
    on:keydown={(e) => {
      if (e.key === "Enter" || e.key === " " || e.key === "Escape") close();
    }}
  ></div>

  <aside
    class="fixed right-4 z-[60] w-[440px] max-w-[92vw] rounded-2xl border border-white/10 bg-black/80 backdrop-blur-2xl shadow-2xl shadow-black/50 overflow-hidden flex flex-col"
    style="top: 86px; bottom: 96px;"
    role="dialog"
    aria-modal="true"
    aria-label="Playback queue"
    tabindex="-1"
  >
    <div class="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-white/5">
      <div>
        <p class="text-xs uppercase tracking-wide text-white/50">Queue</p>
        <h2 class="text-lg font-semibold text-white">
          {#if $playerState.queue.length}
            {$playerState.queue.length} tracks
          {:else}
            Empty
          {/if}
        </h2>
      </div>
      <div class="flex items-center gap-2">
        <button
          class="btn btn-circle btn-sm bg-white/5 hover:bg-white/15 text-white border border-white/10"
          title="Clear queue"
          on:click={clear}
        >
          <svg
            class="h-4 w-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M3 7h18M9 7V4a1 1 0 011-1h4a1 1 0 011 1v3"
            />
          </svg>
        </button>
        <button
          class="btn btn-circle btn-sm bg-white/5 hover:bg-white/15 text-white border border-white/10"
          title="Close"
          on:click={close}
        >
          <svg
            class="h-4 w-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      </div>
    </div>

    {#if $playerState.queue.length === 0}
      <div class="flex-1 flex items-center justify-center text-white/60 text-sm bg-gradient-to-b from-white/5 to-transparent">
        Queue is empty. Play something to get started.
      </div>
    {:else}
      <div class="flex-1 overflow-y-auto px-3 py-2 space-y-2">
        {#each $playerState.queue as track, idx}
          {#if track}
            <button
              class={`w-full text-left rounded-xl border border-transparent bg-white/5 hover:bg-white/10 transition-colors px-3 py-2.5 flex gap-3 items-center relative ${
                idx === $playerState.current_index
                  ? "bg-primary/15 border-primary/60 ring-2 ring-primary/60 shadow-[0_12px_35px_-15px_rgba(0,0,0,0.7)]"
                  : ""
              }`}
              aria-current={idx === $playerState.current_index ? "true" : "false"}
              on:click={() => playFromQueue(idx)}
            >
              {#if idx === $playerState.current_index}
                <span class="absolute left-0 top-0 bottom-0 w-1 bg-primary/80 rounded-l-xl"></span>
              {/if}
              <div class="h-12 w-12 flex-shrink-0 rounded-lg bg-white/10 overflow-hidden border border-white/10">
                <img
                  src={track.art_sha1
                    ? `/api/art/file/${track.art_sha1}?max_size=120`
                    : track.art_id
                      ? `/api/art/${track.art_id}`
                      : "/assets/default-album-placeholder.svg"}
                  alt={track.title || "Artwork"}
                  class="h-full w-full object-cover"
                  loading="lazy"
                  on:error={(e) => {
                    const img = e.currentTarget;
                    if (img instanceof HTMLImageElement) {
                      img.src = "/assets/default-album-placeholder.svg";
                    }
                  }}
                />
              </div>
              <div class="min-w-0 flex-1 space-y-0.5">
                <div class="flex items-center justify-between gap-2">
                  <p class="truncate text-sm font-semibold text-white">
                    {track.title || "Untitled"}
                  </p>
                  <span class="text-xs text-white/60 tabular-nums">
                    {formatTime(track.duration_seconds)}
                  </span>
                </div>
                <div class="flex items-center gap-1 text-xs text-white/70 truncate">
                  {#if track.artist}
                    <a
                      class="hover:text-white hover:underline truncate"
                      href={`/artist/${encodeURIComponent(track.artist)}`}
                      on:click|stopPropagation
                    >
                      {track.artist}
                    </a>
                  {/if}
                  {#if track.artist && track.album}
                    <span class="opacity-50">•</span>
                  {/if}
                  {#if track.album}
                    <a
                      class="hover:text-white hover:underline truncate"
                      href={`/album/${encodeURIComponent(track.artist || "")}/${encodeURIComponent(track.album)}`}
                      on:click|stopPropagation
                    >
                      {track.album}
                    </a>
                  {/if}
                </div>
                {#if formatTech(track)}
                  <div class="text-[11px] text-white/50">{formatTech(track)}</div>
                {/if}
              </div>
            </button>
          {/if}
        {/each}
      </div>
    {/if}
  </aside>
{/if}
