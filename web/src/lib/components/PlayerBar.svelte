<script lang="ts">
  import {
    playerState,
    next,
    previous,
    playFromQueue,
    updateProgress,
    setVolume,
    pause,
    resume,
    seek,
    getHeaders,
    toggleNowPlaying,
    clearQueue,
    shuffleQueue,
    toggleRepeat,
  } from "$stores/player";
  import NowPlayingOverlay from "$components/NowPlayingOverlay.svelte";
  import VolumeControl from "$components/VolumeControl.svelte";
  import QueueDrawer from "$components/QueueDrawer.svelte";
  import ArtistLinks from "$components/ArtistLinks.svelte";
  import { onMount } from "svelte";

  let audio: HTMLAudioElement;
  let isPlaying = false;
  let currentTrack: any = null;
  let progress = 0;
  let duration = 0;
  let volume = 1;
  let hasLoggedCurrentTrack = false; // Track if we've logged this track to history
  let lastLoggedTrackId: number | null = null; // Track the last logged track ID
  let hasAttemptedAutoResume = false; // Track if we've already tried to auto-resume
  let showQueue = false;
  let activeRenderer: any = null;

  const DEFAULT_RENDERER_ICON = "/assets/icon-renderer.svg";
  const LOCAL_RENDERER_ICON = "/assets/icon-browser.svg";

  function getRendererFallback(renderer: any): string {
    if (!renderer) return DEFAULT_RENDERER_ICON;
    if (renderer.type === "local" || renderer.udn?.startsWith("local")) {
      return LOCAL_RENDERER_ICON;
    }
    return DEFAULT_RENDERER_ICON;
  }

  function getRendererIcon(renderer: any): string {
    if (renderer?.icon_url) return renderer.icon_url;
    return getRendererFallback(renderer);
  }

  // Subscribe to store
  $: currentTrack = $playerState.queue[$playerState.current_index];
  $: isPlaying = $playerState.is_playing;
  $: if (!$playerState.renderer.startsWith("local") && currentTrack) {
    duration = currentTrack.duration_seconds;
  } else if (currentTrack && (!audio || !audio.duration)) {
    // Fallback for local if audio not ready
    duration = currentTrack.duration_seconds;
  }
  $: activeRenderer = $playerState.renderers.find(
    (r) => r.udn === $playerState.renderer,
  );

  // Sync volume from store if provided
  $: if ($playerState.volume !== null && $playerState.volume !== undefined) {
    // Avoid jitter if we are dragging (maybe check drift?)
    // API volume is 0-100, local volume is 0.0-1.0
    const newVol = $playerState.volume / 100;
    if (Math.abs(volume - newVol) > 0.05) {
      volume = newVol;
    }
  }

  // Sync local volume TO store (for initial load / browser restore)
  // We check if we are local renderer, and if store is out of sync
  /* 
  $: if (
    ($playerState.renderer.startsWith("local") || $playerState.renderer === "local") &&
    audio &&
    !isNaN(volume)
  ) {
    const vol100 = Math.round(volume * 100);
    // CRITICAL FIX: Do NOT update store if it is null (waiting for server)
    // Also, do NOT overwrite the store if we are just seeing the default 1.0 and store has a saved value.
    // Ideally we only update store on user interaction. 
    // For now, disabling this automatic sync to prevent overwriting saved volume with default 1.0.
    // VolumeControl component handles setting the store on UI interaction.
    
    // if (
    //  $playerState.volume === null ||
    //  Math.abs($playerState.volume - vol100) > 5
    // ) {
    //    playerState.update(s => ({ ...s, volume: vol100 }));
    // }
  } 
  */

  let lastUpdateTime = 0; // Track last time we sent progress to server

  // Reset logged flag when track ID actually changes
  $: if (currentTrack && currentTrack.id !== lastLoggedTrackId) {
    hasLoggedCurrentTrack = false;
    lastLoggedTrackId = currentTrack.id;
    lastUpdateTime = 0; // Reset progress reporting timer
    console.log(
      "[PlayerBar] Track changed, reset hasLoggedCurrentTrack and lastUpdateTime",
    );
  }

  // Auto-resume playback when queue is loaded (reactive)
  $: if (
    !hasAttemptedAutoResume &&
    $playerState.queue.length > 0 &&
    $playerState.current_index >= 0 &&
    currentTrack
  ) {
    console.log(
      "[PlayerBar] Queue loaded, auto-resuming track:",
      currentTrack.title,
    );
    hasAttemptedAutoResume = true;
    // Trigger the play-local event to resume ONLY if local
    if ($playerState.renderer.startsWith("local")) {
      window.dispatchEvent(
        new CustomEvent("jamarr:play-local", { detail: currentTrack }),
      );
    } else {
      console.log(
        "[PlayerBar] Remote renderer active, skipping local auto-resume event",
      );
    }
  }

  function handleSeek(e: MouseEvent & { currentTarget: HTMLDivElement }) {
    if (!$playerState.queue.length && !$playerState.renderer) return;

    const rect = e.currentTarget.getBoundingClientRect();
    const percent = Math.max(
      0,
      Math.min(1, (e.clientX - rect.left) / rect.width),
    );

    // Use duration from current track
    const duration = currentTrack?.duration_seconds || audio?.duration || 0;
    if (!duration) return;

    const time = percent * duration;

    // Remote Seek
    if (!$playerState.renderer.startsWith("local")) {
      console.log("[PlayerBar] Remote seek to:", time);
      seek(time);
      progress = time; // Optimistic
      return;
    }

    // Local Seek
    if (audio) {
      console.log("[PlayerBar] Local seek to:", time);
      audio.currentTime = time;
      progress = time;
      updateProgress(time, isPlaying);
    }
  }

  function checkPlayThreshold() {
    if (!currentTrack) return;

    // Use 'progress' which handles both local (updated via timeupdate) and remote (updated via polling)
    const playedSeconds = progress;
    const totalSeconds = currentTrack.duration_seconds || audio?.duration || 0;

    if (!totalSeconds || totalSeconds === 0) return;

    // Threshold check is retained for potential future UI actions; history logging is server-side.
    const threshold = Math.min(30, totalSeconds * 0.2);
    const _passed = playedSeconds >= threshold;
  }

  onMount(() => {
    console.log("[PlayerBar] onMount called");

    // Initial Volume Sync: Capture browser-restored volume
    if (audio) {
      // Only update store if it has NOT been initialized yet (null)
      // This prevents overwriting a server-fetched value with a default/local value
      if ($playerState.volume === null) {
        console.log(
          "[PlayerBar] Initializing store volume from local audio:",
          audio.volume,
        );
        // We update the store, and rely on `player.ts` to NOT overwrite this with null.
        playerState.update((s) => ({
          ...s,
          volume: Math.round(audio.volume * 100),
        }));
      }
    }

    window.addEventListener("jamarr:play-local", (e: CustomEvent) => {
      console.log("[PlayerBar] jamarr:play-local event received:", e.detail);
      const track = e.detail;

      // Relaxed check: Accept "local" or "local:..."
      if (!$playerState.renderer.includes("local")) return;

      if (audio) {
        console.log(
          "[PlayerBar] Setting audio src to:",
          `/api/stream/${track.id}`,
        );

        // Check if we're switching to a different track
        const currentSrc = audio.src;
        const newSrc = `/api/stream/${track.id}`;
        const isSameTrack = currentSrc.includes(newSrc);

        audio.src = newSrc;

        // Only resume from saved position if it's the SAME track OR it's a fresh load (empty src)
        // Otherwise start from beginning to avoid race condition with timeupdate events
        const savedPosition = $playerState.position_seconds || 0;
        
        // Fix: audio.src is empty string "" on init, or could be current page url in some browsers if not set
        const isColdStart = !currentSrc || currentSrc === window.location.href; 
        
        if ((isSameTrack || isColdStart) && savedPosition > 0) {
          console.log(
            "[PlayerBar] Resuming track from position:",
            savedPosition,
          );
          audio.currentTime = savedPosition;
        } else {
          console.log("[PlayerBar] Starting new track from beginning");
          audio.currentTime = 0;
          // Reset position in store to prevent race condition
          playerState.update((s) => ({ ...s, position_seconds: 0 }));
        }

        // Force Playback immediately - User action (click) initiated this chain
        audio
          .play()
          .then(() => {
            console.log("[PlayerBar] Audio playback started successfully");
            isPlaying = true;
            playerState.update((s) => ({ ...s, is_playing: true }));
          })
          .catch((e) => {
            console.warn("[PlayerBar] Auto-play blocked or failed:", e.message);
            // Don't revert state to false, let user try again if needed
          });
      } else {
        console.error("[PlayerBar] Audio element not found!");
      }
    });

    window.addEventListener("jamarr:seek", (e: CustomEvent) => {
      console.log("[PlayerBar] jamarr:seek event received:", e.detail);
      if (!$playerState.renderer.startsWith("local") || !audio) return;

      const pos = e.detail.position;
      if (typeof pos === "number" && !isNaN(pos)) {
        audio.currentTime = pos;
        progress = pos; // Update local state immediately
        updateProgress(pos, isPlaying);
      }
    });

    window.addEventListener("jamarr:pause", () => {
      console.log("[PlayerBar] jamarr:pause event received");
      if (!$playerState.renderer.startsWith("local") || !audio) return;
      audio.pause();
      isPlaying = false;
      updateProgress(audio.currentTime, false);
    });

    window.addEventListener("jamarr:resume", () => {
      console.log("[PlayerBar] jamarr:resume event received");
      if (!$playerState.renderer.startsWith("local") || !audio) return;
      audio.play().catch((e) => console.error("[PlayerBar] Resume failed:", e));
      isPlaying = true;
      updateProgress(audio.currentTime, true);
    });

    if (audio) {
      console.log(
        "[PlayerBar] Audio element found, adding timeupdate and ended listeners",
      );
      let timeupdateCount = 0;
      audio.addEventListener("timeupdate", () => {
        timeupdateCount++;
        const oldProgress = progress;
        progress = audio.currentTime;
        duration = audio.duration;
        // Keep shared store in sync for overlays/UI
        playerState.update((s) => ({
          ...s,
          position_seconds: progress,
          is_playing: !audio.paused,
        }));

        // Log every 5 seconds to avoid spam
        if (
          Math.floor(audio.currentTime) % 5 === 0 &&
          Math.floor(audio.currentTime) !== Math.floor(oldProgress)
        ) {
          console.log(
            "[PlayerBar] timeupdate #" + timeupdateCount + ":",
            audio.currentTime.toFixed(2),
            "currentTrack:",
            currentTrack?.title,
          );
        }

        checkPlayThreshold(); // Check if we should log to history

        // Update server with progress every 5 seconds
        if (
          currentTrack &&
          Math.floor(audio.currentTime) - lastUpdateTime >= 5
        ) {
          console.log(
            "[PlayerBar] Calling updateProgress with:",
            audio.currentTime.toFixed(2),
            !audio.paused,
          );
          updateProgress(audio.currentTime, !audio.paused);
          lastUpdateTime = Math.floor(audio.currentTime);
        }
      });
      audio.addEventListener("ended", () => {
        console.log("[PlayerBar] Track ended, calling next()");
        next();
      });
    } else {
      console.error("[PlayerBar] Audio element not found in onMount!");
    }

    // Polling for remote playback
    let lastTransportState = "";

    const interval = setInterval(async () => {
      if (
        !$playerState.renderer.startsWith("local") &&
        $playerState.is_playing
      ) {
        try {
          const res = await fetch("/api/player/state", {
            headers: getHeaders(),
          });
          if (res.ok) {
            const state = await res.json();
            progress = state.position_seconds;

            // Sync Store (Queue, Index, IsPlaying)
            // This ensures if backend auto-advanced, we reflect it
            playerState.update((s) => {
              let newState = { ...s, position_seconds: state.position_seconds };
              let changed = false;

              if (s.position_seconds !== state.position_seconds) {
                changed = true;
              }

              if (s.current_index !== state.current_index) {
                console.log(
                  "[PlayerBar] Remote track index changed:",
                  state.current_index,
                );
                newState.current_index = state.current_index;
                changed = true;
              }

              if (s.is_playing !== state.is_playing) {
                newState.is_playing = state.is_playing;
                changed = true;
              }

              // Optional: Sync queue if needed (e.g. length changed)
              if (s.queue.length !== state.queue.length) {
                newState.queue = state.queue;
                changed = true;
              }

              return changed ? newState : s; // Only trigger update if changed (store might handle equality check but good to be explicit)
            });

            // Check history threshold for remote playback
            checkPlayThreshold();

            // Auto-advance queue if remote playback stopped naturally
            if (
              state.transport_state === "STOPPED" ||
              state.transport_state === "NO_MEDIA_PRESENT"
            ) {
              // Determine if this is a "natural" stop (track ended) vs user paused
              // We assume if we think it should be playing ($playerState.is_playing) but device says STOPPED,
              // it means track finished. User pause sets is_playing=false.

              // Debounce simple glitches: only if we saw something else recently or if position is 0
              // For simplicity: if we expected playing, and it stopped, go next.
              // But safeguard: if we just started, we might read STOPPED briefly.
              // Assuming backend updates transport_state frequently enough.

              if (
                lastTransportState &&
                lastTransportState !== "STOPPED" &&
                lastTransportState !== "TRANSITIONING"
              ) {
                console.log(
                  "[PlayerBar] Remote track finished (STOPPED). Waiting for backend to auto-advance.",
                );
                // next(); // Handled by backend now
              }
            }
            lastTransportState = state.transport_state;
          }
        } catch (e) {
          console.error("Polling error", e);
        }
      }
    }, 1000);

    return () => clearInterval(interval);
  });

  function togglePlay() {
    // Remote / UPnP Logic
    if (!$playerState.renderer.startsWith("local")) {
      if ($playerState.is_playing) {
        console.log("[PlayerBar] Remote: pausing");
        pause();
        isPlaying = false; // Optimistic update
      } else {
        console.log("[PlayerBar] Remote: resuming");
        resume();
        isPlaying = true; // Optimistic update
      }
      return;
    }

    console.log(
      "[PlayerBar] togglePlay called, audio.src:",
      audio?.src,
      "audio.paused:",
      audio?.paused,
    );
    if (!audio) {
      console.error("[PlayerBar] togglePlay: audio element not found");
      return;
    }

    // Check if currentTrack exists first
    if (!currentTrack || !currentTrack.id) {
      console.error(
        "[PlayerBar] togglePlay: no valid currentTrack",
        currentTrack,
      );
      return;
    }

    // If no source is set OR source doesn't match current track, dispatch play-local
    const expectedPath = `/api/stream/${currentTrack.id}`;
    if (!audio.src || !audio.src.includes(expectedPath)) {
      console.log(
        "[PlayerBar] togglePlay: src missing or mismatch, dispatching play-local event",
        { current: audio.src, expected: expectedPath },
      );
      // Force is_playing to true so the event handler actually plays
      playerState.update((s) => ({ ...s, is_playing: true }));
      window.dispatchEvent(
        new CustomEvent("jamarr:play-local", { detail: currentTrack }),
      );
      return;
    }

    // Local Audio Logic
    if (audio.paused) {
      console.log("[PlayerBar] togglePlay: playing");
      audio.play().catch((e) => console.error("[PlayerBar] Play failed:", e));
      isPlaying = true;
      updateProgress(audio.currentTime, true);
    } else {
      console.log("[PlayerBar] togglePlay: pausing");
      audio.pause();
      isPlaying = false;
      updateProgress(audio.currentTime, false);
    }
  }

  function formatTime(seconds: number) {
    if (!seconds || isNaN(seconds)) return "0:00";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  }

  function toggleQueue() {
    showQueue = !showQueue;
  }

  function closeQueue() {
    showQueue = false;
  }

  async function clearAndStopQueue() {
    await clearQueue(true);
  }

  $: if ($playerState.queue.length === 0 && audio) {
    if (!audio.paused) {
      audio.pause();
    }
    audio.currentTime = 0;
  }

  function handleImageError(e: Event) {
    const img = e.currentTarget as HTMLImageElement;
    img.src = "/assets/logo.png";
  }
</script>

<div
  class="fixed bottom-0 w-full surface-glass-panel border-t border-subtle p-4 text-default z-50"
>
  <div class="flex items-center justify-between max-w-[1700px] mx-auto">
    <!-- Track Info -->
    <div class="flex items-center gap-4 w-1/3">
      {#if currentTrack}
        <div
          class="relative h-14 w-14 flex-shrink-0 rounded bg-surface-3 overflow-hidden group"
        >
          <img
            src={currentTrack.art_sha1
              ? `/api/art/file/${currentTrack.art_sha1}?max_size=60`
              : "/assets/logo.png"}
            alt="Art"
            class="h-full w-full object-cover"
            on:error={handleImageError}
          />
          <button
            class="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
            on:click={toggleQueue}
          >
            <!-- Overlay remains dark on artwork -->
            <div
              class="btn btn-outline btn-sm border-white text-white hover:bg-white/20"
            >
              <svg
                class="w-5 h-5"
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
          </button>
        </div>
        <div class="min-w-0">
          <div class="font-medium truncate text-default">
            {currentTrack.title}
          </div>
          <div class="text-sm text-muted truncate">
            <ArtistLinks
              artists={currentTrack.artists}
              artist={{
                name: currentTrack.artist,
                mbid: currentTrack.artist_mbid,
              }}
              linkClass="hover:text-default hover:underline cursor-pointer"
              separatorClass="text-muted"
            />
          </div>
          <div class="flex items-center gap-2 text-xs text-subtle mt-0.5">
            {#if currentTrack.codec}
              <span class="uppercase">{currentTrack.codec}</span>
            {/if}
            {#if currentTrack.bit_depth && currentTrack.sample_rate_hz}
              <span>•</span>
              <span
                >{currentTrack.bit_depth}bit / {currentTrack.sample_rate_hz /
                  1000}kHz</span
              >
            {/if}
            {#if $playerState.queue.length > 0}
              <span>•</span>
              <span
                >{$playerState.current_index + 1} of {$playerState.queue
                  .length}</span
              >
            {/if}
          </div>
        </div>
      {:else}
        <div class="text-muted">No track playing</div>
      {/if}
    </div>

    <!-- Controls -->
    <div class="flex flex-col items-center gap-2 w-1/3">
      <div class="flex items-center gap-4">
        <button
          class="btn btn-outline btn-sm"
          aria-label="Previous track"
          on:click={previous}
        >
          <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24"
            ><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" /></svg
          >
        </button>

        <button class="btn btn-primary" on:click={togglePlay}>
          {#if isPlaying}
            <svg class="h-6 w-6" fill="currentColor" viewBox="0 0 24 24"
              ><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" /></svg
            >
          {:else}
            <svg class="h-6 w-6" fill="currentColor" viewBox="0 0 24 24"
              ><path d="M8 5v14l11-7z" /></svg
            >
          {/if}
        </button>

        <button
          class="btn btn-outline btn-sm"
          aria-label="Next track"
          on:click={next}
        >
          <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24"
            ><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" /></svg
          >
        </button>
      </div>

      <!-- Progress -->
      <div class="flex items-center gap-2 w-full max-w-md text-xs text-muted">
        <span>{formatTime(progress)}</span>
        <!-- svelte-ignore a11y-click-events-have-key-events -->
        <div
          class="relative w-full h-4 flex items-center cursor-pointer group"
          on:click={handleSeek}
          role="slider"
          aria-valuenow={progress}
          aria-valuemin={0}
          aria-valuemax={duration || 100}
          tabindex="0"
        >
          <!-- Background Track -->
          <div
            class="absolute w-full h-1 bg-surface-3 rounded-full overflow-hidden"
          >
            <!-- Filled Track -->
            <div
              class="h-full bg-accent transition-all duration-100 ease-linear"
              style="width: {(progress / (duration || 1)) * 100}%"
            ></div>
          </div>
          <!-- Thumb (visible on hover) -->
          <div
            class="absolute h-3 w-3 bg-white border border-subtle rounded-full shadow-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
            style="left: {(progress / (duration || 1)) * 100}%"
          ></div>
        </div>
        <span>{formatTime(duration)}</span>
      </div>
    </div>

    <!-- Volume / Extra -->
    <div class="w-1/3 flex justify-end items-center gap-4">
      <div class="flex items-center gap-2 mr-6">
        <button
          class="btn btn-outline btn-sm {$playerState.repeatMode !== 'off'
            ? 'border-accent bg-accent/10 text-accent'
            : ''}"
          on:click={toggleRepeat}
          title="Repeat: {$playerState.repeatMode}"
        >
          {#if $playerState.repeatMode === "one"}
            <svg
              class="h-4 w-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              ><path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              /><path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M12 11L12 17"
              /></svg
            >
          {:else}
            <svg
              class="h-4 w-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              ><path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              /></svg
            >
          {/if}
        </button>

        <button
          class="btn btn-outline btn-sm"
          on:click={shuffleQueue}
          title="Shuffle Queue"
        >
          <svg
            class="h-4 w-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            ><path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"
            /></svg
          >
        </button>
      </div>
      <div class="flex items-center gap-3">
        <div class="h-[88px] w-[88px] rounded-lg bg-surface-3/70 p-1.5 shadow-inner">
          <img
            class="h-full w-full rounded object-contain"
            src={getRendererIcon(activeRenderer)}
            alt=""
            loading="lazy"
            on:error={(e) => {
              (e.currentTarget as HTMLImageElement).src =
                getRendererFallback(activeRenderer);
            }}
          />
        </div>
        <div class="flex items-center gap-2 group">
          <VolumeControl
            showIcon={true}
            iconClass="h-5 w-5 text-muted"
            sliderClass="w-24 transition-opacity"
            sliderStyle=""
          />
        </div>
      </div>
      <button
        class="btn btn-outline btn-sm"
        title="Now Playing"
        on:click={toggleNowPlaying}
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
            d="M4 8h16M4 16h10m-6-8v8"
          ></path></svg
        >
      </button>
      <button
        class="btn btn-outline btn-sm"
        title="Queue"
        on:click={toggleQueue}
      >
        <svg
          class="h-5 w-6"
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

  <audio bind:this={audio} bind:volume></audio>
</div>

<QueueDrawer
  visible={showQueue}
  on:close={closeQueue}
  on:clear={clearAndStopQueue}
/>

<NowPlayingOverlay />
