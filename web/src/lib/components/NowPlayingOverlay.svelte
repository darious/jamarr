<script lang="ts">
  import {
    playerState,
    nowPlayingVisible,
    pause,
    resume,
    previous,
    next,
    seek,
    playFromQueue,
    toggleNowPlaying,
  } from "$stores/player";
  import VolumeControl from "$components/VolumeControl.svelte";
  import { onMount, onDestroy } from "svelte";

  onMount(() => {
    // Safety cleanup: Ensure body scroll is never locked by stale state
    if (typeof document !== "undefined") {
      document.body.style.overflow = "";
    }
  });

  let progress = 0;
  let duration = 0;

  // Sync with store
  $: if ($playerState.queue[$playerState.current_index]) {
    duration = $playerState.queue[$playerState.current_index].duration_seconds;
  }

  // Sync progress from store
  $: progress = $playerState.position_seconds || 0;

  onDestroy(() => {
    if (typeof document !== "undefined") {
      document.body.style.overflow = "";
    }
  });

  const formatTime = (seconds?: number | null) => {
    if (!seconds || isNaN(seconds)) return "0:00";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60)
      .toString()
      .padStart(2, "0");
    return `${m}:${s}`;
  };

  /* 
    getArt helper
    Uses art_sha1 exclusively. 
  */
  const getArt = (track: any, size: number = 0) => {
    if (!track) return "/assets/logo.png";
    if (track.art_sha1) {
      return size > 0
        ? `/api/art/file/${track.art_sha1}?max_size=${size}`
        : `/api/art/file/${track.art_sha1}`;
    }
    // Fallback if sha1 missing (shouldn't happen with backfill)
    if (track.art_id) return `/art/${track.art_id}`;
    return "/assets/logo.png";
  };

  function handleSeek(e: MouseEvent & { currentTarget: HTMLDivElement }) {
    if (!$playerState.queue.length && !$playerState.renderer) return;

    const rect = e.currentTarget.getBoundingClientRect();
    const percent = Math.max(
      0,
      Math.min(1, (e.clientX - rect.left) / rect.width),
    );

    const time = percent * (duration || 0);

    // Optimistic update
    progress = time;
    seek(time);
  }

  let queueContainer: HTMLElement;
  let scrollTimeout: any;
  let lastScrollIndex = -1;

  // Auto-scroll to active track ONLY when index changes
  $: if (
    $nowPlayingVisible &&
    $playerState.current_index >= 0 &&
    queueContainer &&
    $playerState.current_index !== lastScrollIndex
  ) {
    lastScrollIndex = $playerState.current_index;
    // Small delay to ensure render
    clearTimeout(scrollTimeout);
    scrollTimeout = setTimeout(() => {
      scrollToActive();
    }, 100);
  }

  // Initial scroll on open
  $: if (
    $nowPlayingVisible &&
    queueContainer &&
    $playerState.current_index >= 0
  ) {
    if (lastScrollIndex === -1) {
      // First open
      lastScrollIndex = $playerState.current_index;
      setTimeout(() => scrollToActive(), 100);
    }
  }

  function scrollToActive() {
    if (!queueContainer) return;
    const el = document.getElementById(
      `queue-item-${$playerState.current_index}`,
    );
    if (el) {
      // Calculate scroll position manually to prevent body scrolling
      // scrollIntoView() bubbles up and scrolls the body if not locked
      const containerRect = queueContainer.getBoundingClientRect();
      const elRect = el.getBoundingClientRect();
      const relativeTop = elRect.top - containerRect.top;
      const targetScroll =
        queueContainer.scrollTop +
        relativeTop -
        queueContainer.clientHeight / 2 +
        elRect.height / 2;

      queueContainer.scrollTo({ top: targetScroll, behavior: "smooth" });
    }
  }

  // Reset scroll index when overlay closes so it scrolls again on next open
  $: if (!$nowPlayingVisible) {
    lastScrollIndex = -1;
  }

  let wasPlaying = false;
  $: {
    if (wasPlaying && !$playerState.is_playing) {
      if (
        $playerState.queue.length &&
        $playerState.current_index === $playerState.queue.length - 1
      ) {
        // Auto-close if last track finished (progress near duration)
        // Using 2s threshold to be safe
        if (duration > 0 && Math.abs(duration - progress) < 2) {
          if ($nowPlayingVisible) toggleNowPlaying();
        }
      }
    }
    wasPlaying = $playerState.is_playing;
  }
</script>

{#if $nowPlayingVisible}
  <div class="fixed inset-0 z-[60] overflow-hidden bg-black text-white/90">
    <!-- Global Blurred Background -->
    <img
      src={getArt($playerState.queue[$playerState.current_index], 100)}
      alt=""
      class="absolute inset-0 w-full h-full object-cover blur-3xl opacity-50 scale-110"
    />
    <div class="absolute inset-0 bg-black/40"></div>

    <!-- Close Button Area (Exact PlayerBar Replica) -->
    <div
      class="absolute bottom-0 w-full p-4 z-50 pointer-events-none text-white"
    >
      <div class="flex items-center justify-between max-w-[1700px] mx-auto">
        <!-- Left 1/3 Spacer (Forces height to match PlayerBar h-14 art) -->
        <div class="w-1/3 h-14"></div>

        <!-- Center 1/3 Spacer -->
        <div class="w-1/3"></div>

        <!-- Right 1/3: Actual Content -->
        <div
          class="w-1/3 flex justify-end items-center gap-4 pointer-events-auto"
        >
          <!-- Close Button (Replaces Now Playing Toggle) -->
          <!-- Using EXACT classes from PlayerBar NowPlaying button -->
          <button
            class="btn btn-circle btn-sm bg-white/5 hover:bg-white/20 text-white border-none hover:scale-110 transition-transform"
            title="Close"
            on:click={toggleNowPlaying}
          >
            <svg
              class="h-5 w-5"
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

          <!-- Spacer for Queue Button (Invisible EXACT Clone) -->
          <!-- Using EXACT classes from PlayerBar Queue button + invisible -->
          <button
            class="btn btn-circle btn-sm bg-white/5 text-white border-none invisible pointer-events-none"
          >
            <svg
              class="h-5 w-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              ><path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M4 6h16M4 12h16M4 18h16"
              ></path></svg
            >
          </button>
        </div>
      </div>
    </div>

    <div
      class="relative z-10 w-full max-w-[95%] mx-auto px-4 lg:px-12 pt-20 pb-24 h-full flex flex-col gap-8"
    >
      <div class="flex items-center justify-between flex-shrink-0">
        <div class="flex items-center gap-3 text-white/70">
          <span class="text-xs uppercase tracking-[0.2em]">Now Playing</span>
          {#if $playerState.queue.length}
            <span class="text-xs text-white/50"
              >{$playerState.current_index + 1} / {$playerState.queue
                .length}</span
            >
          {/if}
        </div>
      </div>

      <div
        class="flex flex-col lg:flex-row gap-8 lg:gap-16 items-center lg:items-center justify-center flex-1 min-h-0 pb-4"
      >
        <!-- Left: Square Art -->
        <div
          class="relative w-full max-w-md lg:w-auto lg:max-w-[50vw] h-auto lg:h-[80vh] aspect-square rounded-3xl overflow-hidden shadow-2xl bg-surface-900/50 border border-white/5 order-2 lg:order-1 flex-shrink-0"
        >
          <img
            class="absolute inset-0 w-full h-full object-cover"
            src={getArt($playerState.queue[$playerState.current_index], 600)}
            alt={$playerState.queue[$playerState.current_index]?.title || "Art"}
          />
          <!-- Inner shadow for depth -->
          <div
            class="absolute inset-0 shadow-[inset_0_0_100px_rgba(0,0,0,0.5)]"
          ></div>
        </div>

        <!-- Right: Info, Controls, Queue -->
        <div
          class="flex flex-col gap-6 order-1 lg:order-2 min-w-0 w-full max-w-2xl lg:h-[80vh]"
        >
          <!-- Centered Info & Controls -->
          <div class="flex flex-col justify-center gap-6 flex-shrink-0 py-2">
            <!-- Top: Info -->
            <div class="text-center space-y-1 mt-2">
              <div
                class="text-4xl font-bold leading-tight truncate text-white px-8 drop-shadow-lg"
              >
                {$playerState.queue[$playerState.current_index]?.title ||
                  "No track playing"}
              </div>
              <div class="text-2xl text-white/80 truncate px-8 drop-shadow-md">
                <a
                  href={$playerState.queue[$playerState.current_index]
                    ?.artist_mbid
                    ? `/artist/${$playerState.queue[$playerState.current_index]?.artist_mbid}`
                    : `/artist/${encodeURIComponent($playerState.queue[$playerState.current_index]?.artist || "")}`}
                  class="hover:text-white hover:underline pointer-events-auto cursor-pointer"
                  on:click|stopPropagation={() => nowPlayingVisible.set(false)}
                >
                  {$playerState.queue[$playerState.current_index]?.artist ||
                    "—"}
                </a>
              </div>
              <div class="text-lg text-white/60 truncate px-8 drop-shadow-md">
                <a
                  href={$playerState.queue[$playerState.current_index]
                    ?.album_mbid
                    ? `/album/${$playerState.queue[$playerState.current_index]?.album_mbid}`
                    : `/album/${encodeURIComponent($playerState.queue[$playerState.current_index]?.artist || "")}/${encodeURIComponent($playerState.queue[$playerState.current_index]?.album || "")}`}
                  class="hover:text-white hover:underline pointer-events-auto cursor-pointer"
                  on:click|stopPropagation={() => nowPlayingVisible.set(false)}
                >
                  {$playerState.queue[$playerState.current_index]?.album ||
                    "Unknown Album"}
                </a>
              </div>
              <div
                class="flex items-center justify-center gap-3 text-xs text-white/50 pt-2"
              >
                {#if $playerState.queue[$playerState.current_index]?.codec}
                  <span class="uppercase">
                    {$playerState.queue[$playerState.current_index]?.codec}
                  </span>
                {/if}
                {#if $playerState.queue[$playerState.current_index]?.bit_depth}
                  <span>•</span>
                  <span
                    >{$playerState.queue[$playerState.current_index]
                      ?.bit_depth}bit /
                    {$playerState.queue[$playerState.current_index]
                      ?.sample_rate_hz / 1000}kHz</span
                  >
                {/if}
              </div>
            </div>

            <!-- Middle: Controls -->
            <div
              class="flex flex-col items-center gap-6 w-full max-w-xl mx-auto px-4"
            >
              <!-- Progress -->
              <div class="space-y-2 w-full">
                <div
                  class="relative h-4 w-full flex items-center cursor-pointer group/slider"
                  on:click={handleSeek}
                  on:keydown={(e) => {
                    if (e.key === "ArrowRight")
                      seek(Math.min(duration, progress + 5));
                    if (e.key === "ArrowLeft") seek(Math.max(0, progress - 5));
                  }}
                  role="slider"
                  aria-valuenow={progress}
                  aria-valuemin={0}
                  aria-valuemax={duration || 100}
                  tabindex="0"
                >
                  <!-- Background Track -->
                  <div
                    class="absolute w-full h-1 bg-white/20 rounded-full overflow-hidden backdrop-blur-sm"
                  >
                    <!-- Filled Track -->
                    <div
                      class="h-full bg-white transition-all duration-100 ease-linear shadow-[0_0_10px_rgba(255,255,255,0.5)]"
                      style="width: {(progress / (duration || 1)) * 100}%"
                    ></div>
                  </div>
                  <!-- Thumb -->
                  <div
                    class="absolute h-3 w-3 bg-white rounded-full shadow-lg opacity-0 group-hover/slider:opacity-100 transition-opacity pointer-events-none"
                    style="left: {(progress / (duration || 1)) * 100}%"
                  ></div>
                </div>
                <div
                  class="flex items-center justify-between text-xs text-white/60 font-mono drop-shadow-md"
                >
                  <span>{formatTime(progress)}</span>
                  <span>{formatTime(duration)}</span>
                </div>
              </div>

              <!-- Buttons -->
              <div class="flex items-center justify-center gap-10">
                <button
                  class="btn btn-circle btn-lg bg-white/5 hover:bg-white/20 text-white border-none hover:scale-110 transition-transform backdrop-blur-sm"
                  on:click={previous}
                >
                  <svg class="h-8 w-8" fill="currentColor" viewBox="0 0 24 24"
                    ><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" /></svg
                  >
                </button>
                <button
                  class="btn btn-circle btn-2xl bg-white text-black border-none hover:scale-105 transition-transform p-4 shadow-lg shadow-white/20 scale-125"
                  on:click={() =>
                    $playerState.is_playing ? pause() : resume()}
                >
                  {#if $playerState.is_playing}
                    <svg
                      class="h-10 w-10"
                      fill="currentColor"
                      viewBox="0 0 24 24"
                      ><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" /></svg
                    >
                  {:else}
                    <svg
                      class="h-10 w-10"
                      fill="currentColor"
                      viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg
                    >
                  {/if}
                </button>
                <button
                  class="btn btn-circle btn-lg bg-white/5 hover:bg-white/20 text-white border-none hover:scale-110 transition-transform backdrop-blur-sm"
                  on:click={next}
                >
                  <svg class="h-8 w-8" fill="currentColor" viewBox="0 0 24 24"
                    ><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" /></svg
                  >
                </button>
              </div>

              <!-- Volume Control -->
              <div class="w-full max-w-xs mx-auto flex justify-center">
                <VolumeControl
                  showIcon={true}
                  sliderClass="range range-xs range-primary w-full"
                  containerClass="flex items-center gap-4 w-full px-8 opacity-80 hover:opacity-100 transition-opacity"
                  iconClass="h-5 w-5 text-white/60"
                />
              </div>
            </div>
          </div>

          <!-- Bottom: Max height queue (Glass Box) -->
          <div
            class="flex-1 min-h-0 bg-black/30 backdrop-blur-xl rounded-2xl border border-white/10 overflow-hidden flex flex-col flex-shrink-0 shadow-2xl"
          >
            <div
              class="px-4 py-3 border-b border-white/10 bg-white/5 text-white/90 font-medium text-sm flex justify-between items-center"
            >
              <span>Queue</span>
              <span class="text-xs text-white/50"
                >{$playerState.queue.length} tracks</span
              >
            </div>
            <div
              class="flex-1 overflow-y-auto pr-1 custom-scrollbar"
              bind:this={queueContainer}
            >
              {#if $playerState.queue.length === 0}
                <div class="p-6 text-white/50 text-center text-sm">
                  Queue is empty.
                </div>
              {:else}
                {#each $playerState.queue as track, idx}
                  <button
                    id={`queue-item-${idx}`}
                    class={`w-full text-left px-3 py-2 hover:bg-white/5 transition border-b border-white/5 last:border-0 ${
                      idx === $playerState.current_index ? "bg-white/10" : ""
                    }`}
                    on:click={() => playFromQueue(idx)}
                  >
                    <div class="flex items-center gap-3">
                      <div
                        class="w-6 text-center text-[10px] text-white/40 font-mono"
                      >
                        {idx + 1}
                      </div>
                      <div class="min-w-0 flex-1">
                        <div class="flex justify-between items-baseline gap-2">
                          <div
                            class={`text-sm truncate ${idx === $playerState.current_index ? "font-bold text-white" : "text-white/80"}`}
                          >
                            {track.title}
                          </div>
                          <div
                            class="text-[10px] text-white/50 whitespace-nowrap"
                          >
                            {formatTime(track.duration_seconds)}
                          </div>
                        </div>
                        <div class="flex items-center gap-2">
                          <div
                            class="text-xs text-white/60 truncate max-w-[60%] flex gap-1 items-center"
                          >
                            <a
                              href={track.artist_mbid
                                ? `/artist/${track.artist_mbid}`
                                : `/artist/${encodeURIComponent(track.artist)}`}
                              class="hover:text-white hover:underline"
                              on:click|stopPropagation={() =>
                                nowPlayingVisible.set(false)}
                            >
                              {track.artist}
                            </a>
                            <span>•</span>
                            <a
                              href={track.album_mbid
                                ? `/album/${track.album_mbid}`
                                : `/album/${encodeURIComponent(track.artist)}/${encodeURIComponent(track.album || "")}`}
                              class="hover:text-white hover:underline"
                              on:click|stopPropagation={() =>
                                nowPlayingVisible.set(false)}
                            >
                              {track.album || "Unknown Album"}
                            </a>
                          </div>
                        </div>
                      </div>
                    </div>
                  </button>
                {/each}
              {/if}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
{/if}
