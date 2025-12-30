<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import { playerState, playFromQueue, reorderQueue } from "$stores/player";

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
      parts.push(
        `${track.bit_depth}bit / ${Math.round(track.sample_rate_hz / 1000)}kHz`,
      );
    }
    if (track?.bitrate) {
      parts.push(`${Math.round(track.bitrate / 1000)}kbps`);
    }
    return parts.join(" • ");
  };

  const close = () => dispatch("close");
  const clear = () => dispatch("clear");

  // Drag state
  let dragIndex: number | null = null;
  let isDragging = false;
  let dragPos = { x: 0, y: 0 };
  let dropIndex: number | null = null; // Where the item will be dropped (insertion index)
  let dragTrack: any = null;

  // We rely on $playerState.queue directly for rendering.
  // We don't mutate it locally until drop.

  const moveItem = (arr: any[], from: number, to: number) => {
    const updated = [...arr];
    const [item] = updated.splice(from, 1);
    // If we removed an item before the target index, 'to' shifts down by 1
    // BUT 'to' here represents the insertion index in the *original* list logic?
    // Let's standardise: 'to' is the index in the list *before* removal?
    // No, standard array move usually treats 'to' as destination index.

    // Simplest logic for "insert at index":
    // If I drop at index 5, it goes before the item strictly at index 5.
    // However, if I drag item 2 to index 5, I remove 2. Index 3,4,5 shift down.
    // The "index 5" I dropped at corresponds to index 4 in the new array?

    // Let's use standard splice logic on the removed array.
    // If to > from, we need to decrement to by 1 because we removed an item before it.
    const target = to > from ? to - 1 : to;
    updated.splice(target, 0, item);
    return updated;
  };

  // Scroll state
  let scrollContainer: HTMLElement;
  let autoScrollSpeed = 0;
  let animationFrameId: number | null = null;

  const stopAutoScroll = () => {
    if (animationFrameId) {
      cancelAnimationFrame(animationFrameId);
      animationFrameId = null;
    }
    autoScrollSpeed = 0;
  };

  const startAutoScroll = () => {
    if (animationFrameId) return;
    const scroll = () => {
      if (autoScrollSpeed !== 0 && scrollContainer) {
        scrollContainer.scrollTop += autoScrollSpeed;
        animationFrameId = requestAnimationFrame(scroll);
      } else {
        animationFrameId = null;
      }
    };
    animationFrameId = requestAnimationFrame(scroll);
  };

  const checkAutoScroll = (y: number) => {
    if (!scrollContainer) return;
    const rect = scrollContainer.getBoundingClientRect();
    const threshold = 100; // Distance from edge to start scrolling
    const maxSpeed = 15; // Max scroll speed

    // Check boundaries
    if (y < rect.top + threshold) {
      // Scroll up
      // speed increases as we get closer to the top edge
      // normalize ratio 0..1
      const dist = Math.max(0, rect.top + threshold - y);
      const ratio = Math.min(1, dist / threshold);
      autoScrollSpeed = -maxSpeed * ratio;
      startAutoScroll();
    } else if (y > rect.bottom - threshold) {
      // Scroll down
      const dist = Math.max(0, y - (rect.bottom - threshold));
      const ratio = Math.min(1, dist / threshold);
      autoScrollSpeed = maxSpeed * ratio;
      startAutoScroll();
    } else {
      autoScrollSpeed = 0;
    }
  };

  const handleDragStart = (event: DragEvent, idx: number) => {
    dragIndex = idx;
    isDragging = true;
    dragTrack = $playerState.queue[idx];
    dropIndex = idx; // Default to dropping exactly where it is
    dragPos = { x: event.clientX, y: event.clientY };

    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", String(idx));
      // Set invisible drag image so we can use our custom one
      const img = new Image();
      img.src =
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PQbcbwAAAABJRU5ErkJggg==";
      event.dataTransfer.setDragImage(img, 0, 0);
    }
  };

  const handleDragOver = (event: DragEvent, idx: number) => {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";

    // Track pos for visual
    dragPos = { x: event.clientX, y: event.clientY };
    // Check for auto-scroll
    checkAutoScroll(event.clientY);

    if (dragIndex === null) return;

    const target = event.currentTarget as HTMLElement;
    const rect = target?.getBoundingClientRect();
    if (!rect) return;

    const relY = event.clientY - rect.top;
    const mid = rect.height / 2;

    // If above midpoint, insert before this item. If below, insert after (which is same as before next item)
    let dest = relY < mid ? idx : idx + 1;

    dropIndex = dest;
  };

  // Handle drag over the empty space at bottom matching the last index
  const handleDragOverContainer = (event: DragEvent) => {
    event.preventDefault();
    dragPos = { x: event.clientX, y: event.clientY };
    checkAutoScroll(event.clientY);
    // If we are over the container but not a specific item, usually means at the end
    // But we have a specific drop zone at the bottom now.
  };

  const handleDrop = async (event: DragEvent) => {
    event.preventDefault();
    stopAutoScroll();

    if (dragIndex === null || dropIndex === null) {
      resetDrag();
      return;
    }

    // Check for no-op
    // If dropping at same index or index+1 (which puts it right back after itself), do nothing
    if (dropIndex === dragIndex || dropIndex === dragIndex + 1) {
      resetDrag();
      return;
    }

    const newQueue = moveItem($playerState.queue, dragIndex, dropIndex);

    // Immediate optimistic update could be done here if store allows,
    // but reorderQueue handles API + store update.
    await reorderQueue(newQueue);
    resetDrag();
  };

  const handleDragEnd = () => {
    stopAutoScroll();
    resetDrag();
  };

  const resetDrag = () => {
    dragIndex = null;
    isDragging = false;
    dropIndex = null;
    dragTrack = null;
    stopAutoScroll();
  };
</script>

<svelte:window
  on:keydown={(e) => {
    if (!visible) return;
    if (e.key === "Escape") close();
  }}
  on:dragover={(e) => {
    // Keep track of global drag pos for the floating preview
    if (isDragging) {
      dragPos = { x: e.clientX, y: e.clientY };
      // Also check autoScroll here in case we are over non-droppable areas but still in window?
      // Actually, we only care if we are over the container.
    }
  }}
/>

{#if visible}
  {#if isDragging && dragTrack}
    <div
      class="fixed z-[70] pointer-events-none"
      style={`top:${dragPos.y}px; left:${dragPos.x}px; transform: translate(-16px, -16px);`}
    >
      <div
        class="rounded-2xl bg-black/85 border border-white/10 shadow-2xl shadow-black/60 px-4 py-3 flex items-center gap-3 min-w-[220px]"
      >
        <div
          class="h-12 w-12 rounded-lg overflow-hidden bg-white/10 border border-white/10"
        >
          <img
            src={dragTrack.art_sha1
              ? `/api/art/file/${dragTrack.art_sha1}?max_size=120`
              : dragTrack.art_id
                ? `/api/art/${dragTrack.art_id}`
                : "/assets/default-album-placeholder.svg"}
            alt={dragTrack.title || "Artwork"}
            class="h-full w-full object-cover"
          />
        </div>
        <div class="min-w-0">
          <div class="text-sm font-semibold text-white truncate">
            {dragTrack.title || "Untitled"}
          </div>
          <div class="text-xs text-white/70 truncate">
            {dragTrack.artist || ""}
          </div>
        </div>
      </div>
    </div>
  {/if}
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
    <div
      class="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-white/5"
    >
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
      <div
        class="flex-1 flex items-center justify-center text-white/60 text-sm bg-gradient-to-b from-white/5 to-transparent"
      >
        Queue is empty. Play something to get started.
      </div>
    {:else}
      <!-- Drop Handler for entire list area -->
      <div
        class="flex-1 overflow-y-auto px-3 py-2 scrollbar-hide"
        role="list"
        bind:this={scrollContainer}
        on:dragover={handleDragOverContainer}
        on:drop={handleDrop}
      >
        <div class="space-y-1">
          {#each $playerState.queue as track, idx}
            <!-- Drop Indicator before item -->
            {#if isDragging && dropIndex === idx}
              <div
                class="h-[2px] w-full bg-white/60 shadow-[0_0_8px_rgba(255,255,255,0.4)] rounded-full my-1 transition-all"
              ></div>
            {/if}

            <button
              class={`w-full text-left rounded-xl border border-transparent bg-white/5 hover:bg-white/10 transition-all px-3 py-2.5 flex gap-3 items-center relative group
                ${idx === $playerState.current_index ? "bg-primary/10 border-primary/40" : ""}
                ${isDragging && idx === dragIndex ? "opacity-30 grayscale" : ""}
                `}
              aria-current={idx === $playerState.current_index
                ? "true"
                : "false"}
              draggable="true"
              on:dragstart={(e) => handleDragStart(e, idx)}
              on:dragover={(e) => handleDragOver(e, idx)}
              on:dragend={handleDragEnd}
              on:click={() => playFromQueue(idx)}
            >
              {#if idx === $playerState.current_index}
                <div
                  class="absolute left-0 top-3 bottom-3 w-1 bg-primary rounded-r-md shadow-[0_0_10px_rgba(var(--color-primary),0.5)]"
                ></div>
              {/if}

              <!-- Track Art -->
              <div
                class="h-10 w-10 flex-shrink-0 rounded bg-white/10 overflow-hidden relative shadow-lg"
              >
                <img
                  src={track.art_sha1
                    ? `/api/art/file/${track.art_sha1}?max_size=120`
                    : track.art_id
                      ? `/api/art/${track.art_id}`
                      : "/assets/default-album-placeholder.svg"}
                  alt={track.title || "Artwork"}
                  class="h-full w-full object-cover group-hover:scale-105 transition-transform duration-500"
                  loading="lazy"
                  on:error={(e) => {
                    const img = e.currentTarget;
                    if (img instanceof HTMLImageElement) {
                      img.src = "/assets/default-album-placeholder.svg";
                    }
                  }}
                />
                {#if idx === $playerState.current_index && $playerState.is_playing}
                  <div
                    class="absolute inset-0 bg-black/40 flex items-center justify-center"
                  >
                    <div
                      class="loading loading-bars loading-xs text-white"
                    ></div>
                  </div>
                {/if}
              </div>

              <!-- Track Info -->
              <div class="min-w-0 flex-1 space-y-0.5">
                <div class="flex items-center justify-between gap-2">
                  <p
                    class={`truncate text-sm font-medium ${idx === $playerState.current_index ? "text-primary" : "text-white"}`}
                  >
                    {track.title || "Untitled"}
                  </p>
                  <span class="text-xs text-white/50 tabular-nums font-mono">
                    {formatTime(track.duration_seconds)}
                  </span>
                </div>
                <div
                  class="flex items-center gap-1 text-xs text-white/60 truncate"
                >
                  {#if track.artist}
                    <span>{track.artist}</span>
                  {/if}
                </div>
              </div>

              <!-- Drag Handle Icon (visible on hover) -->
              <div
                class="opacity-0 group-hover:opacity-100 transition-opacity absolute right-2 text-white/40 cursor-grab active:cursor-grabbing p-1"
              >
                <svg
                  class="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  ><path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M4 8h16M4 16h16"
                  ></path></svg
                >
              </div>
            </button>
          {/each}

          <!-- Drop Indicator at the very end -->
          {#if isDragging && dropIndex === $playerState.queue.length}
            <div
              class="h-[2px] w-full bg-white/60 shadow-[0_0_8px_rgba(255,255,255,0.4)] rounded-full my-1 transition-all"
            ></div>
          {/if}

          <!-- Bottom drop zone spacer -->
          <div
            role="listitem"
            class="h-12 w-full flex items-center justify-center text-transparent"
            on:dragover={(e) => {
              e.preventDefault();
              dropIndex = $playerState.queue.length;
            }}
          >
            Drop at end
          </div>
        </div>
      </div>
    {/if}
  </aside>
{/if}
