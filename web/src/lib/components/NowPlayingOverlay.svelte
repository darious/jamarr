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
    reorderQueue,
  } from "$stores/player";
  import VolumeControl from "$components/VolumeControl.svelte";
  import TrackCard from "$components/TrackCard.svelte";
  import ArtistLinks from "$components/ArtistLinks.svelte";
  import AddToPlaylistModal from "$components/AddToPlaylistModal.svelte";
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

  // Drag and drop state
  let dragIndex: number | null = null;
  let isDragging = false;
  let dropIndex: number | null = null;

  const handleDragStart = (event: DragEvent, idx: number) => {
    dragIndex = idx;
    isDragging = true;
    dropIndex = idx;
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      const img = new Image();
      img.src =
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchPQAAAABJRU5ErkJggg==";
      event.dataTransfer.setDragImage(img, 0, 0);
    }
  };

  const handleDragOver = (event: DragEvent, idx: number) => {
    event.preventDefault();
    if (dragIndex === null) return;
    const target = event.currentTarget as HTMLElement;
    const rect = target?.getBoundingClientRect();
    if (!rect) return;
    const relY = event.clientY - rect.top;
    const mid = rect.height / 2;
    dropIndex = relY < mid ? idx : idx + 1;
  };

  const handleDragEnd = async () => {
    if (dragIndex === null || dropIndex === null) {
      resetDrag();
      return;
    }
    if (dropIndex === dragIndex || dropIndex === dragIndex + 1) {
      resetDrag();
      return;
    }
    await reorderQueue(dragIndex, dropIndex);
    resetDrag();
  };

  const resetDrag = () => {
    dragIndex = null;
    isDragging = false;
    dropIndex = null;
  };

  // Playlist modal
  let showPlaylistModal = false;
  let selectedTrackIds: number[] = [];

  const openPlaylistModal = (trackId: number) => {
    selectedTrackIds = [trackId];
    showPlaylistModal = true;
  };
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
            class="btn btn-outline btn-sm"
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
          <div
            class="btn btn-circle btn-sm bg-white/5 text-white border-none invisible pointer-events-none"
            aria-hidden="true"
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
          </div>
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
                <ArtistLinks
                  artists={$playerState.queue[$playerState.current_index]
                    ?.artists}
                  artist={{
                    name:
                      $playerState.queue[$playerState.current_index]?.artist ||
                      "—",
                    mbid: $playerState.queue[$playerState.current_index]
                      ?.artist_mbid,
                  }}
                  linkClass="hover:text-white hover:underline pointer-events-auto cursor-pointer"
                  separatorClass="text-white/80"
                  stopPropagation={true}
                />
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
                      class="h-full bg-accent transition-all duration-100 ease-linear shadow-[0_0_10px_rgba(255,255,255,0.5)]"
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
                  class="btn btn-outline"
                  aria-label="Previous track"
                  on:click={previous}
                >
                  <svg class="h-8 w-8" fill="currentColor" viewBox="0 0 24 24"
                    ><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" /></svg
                  >
                </button>
                <button
                  class="btn btn-primary"
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
                  class="btn btn-outline"
                  aria-label="Next track"
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
                <div class="space-y-1 p-2">
                  {#each $playerState.queue as track, idx}
                    {#if isDragging && dropIndex === idx}
                      <div
                        class="h-[2px] w-full bg-white/60 shadow-[0_0_8px_rgba(255,255,255,0.4)] rounded-full my-1 transition-all"
                      ></div>
                    {/if}

                    <div id={`queue-item-${idx}`}>
                      <TrackCard
                        track={{
                          id: track.id,
                          title: track.title || "Untitled",
                          duration_seconds: track.duration_seconds,
                          codec: track.codec,
                          bit_depth: track.bit_depth,
                          sample_rate_hz: track.sample_rate_hz,
                          bitrate: track.bitrate,
                          art_sha1: track.art_sha1,
                          art_id: track.art_id,
                        }}
                        artists={track.artists}
                        artist={{
                          name: track.artist || "",
                          mbid: track.artist_mbid,
                        }}
                        album={{
                          name: track.album || "",
                          mbid: track.album_mbid,
                        }}
                        artwork={{
                          sha1: track.art_sha1,
                          id: track.art_id,
                        }}
                        showIndex={false}
                        showArtwork={true}
                        showAlbum={true}
                        showArtist={true}
                        showYear={false}
                        showTechDetails={true}
                        showPopularity={false}
                        showBitrate={false}
                        draggable={true}
                        onDragStart={(e) => handleDragStart(e, idx)}
                        onDragOver={(e) => handleDragOver(e, idx)}
                        onDragEnd={handleDragEnd}
                        isDragging={isDragging && idx === dragIndex}
                        isCurrentlyPlaying={idx === $playerState.current_index}
                        isPlaying={$playerState.is_playing}
                        onClick={() => playFromQueue(idx)}
                        onAddToPlaylist={() => openPlaylistModal(track.id)}
                      />
                    </div>
                  {/each}

                  {#if isDragging && dropIndex === $playerState.queue.length}
                    <div
                      class="h-[2px] w-full bg-white/60 shadow-[0_0_8px_rgba(255,255,255,0.4)] rounded-full my-1 transition-all"
                    ></div>
                  {/if}
                </div>
              {/if}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
{/if}

<AddToPlaylistModal
  bind:visible={showPlaylistModal}
  trackIds={selectedTrackIds}
/>
