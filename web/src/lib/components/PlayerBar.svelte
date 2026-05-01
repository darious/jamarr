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
    advanceIndexLocal,
    computeNextTrackToArm,
  } from "$stores/player";
  import { fetchWithAuth, getStreamUrl, getArtUrl } from "$lib/api";
  import NowPlayingOverlay from "$components/NowPlayingOverlay.svelte";
  import VolumeControl from "$components/VolumeControl.svelte";
  import QueueDrawer from "$components/QueueDrawer.svelte";
  import ArtistLinks from "$components/ArtistLinks.svelte";
  import {
    registerActionHandlers,
    clearAll as clearMediaSession,
    setMetadata as setMediaSessionMetadata,
    setPlaybackState as setMediaSessionPlaybackState,
    setPositionState as setMediaSessionPositionState,
  } from "$lib/media-session";
  import { onMount, onDestroy } from "svelte";

  // Two audio elements so we can pre-arm the next track while the current
  // one is playing. On `ended`, we synchronously call .play() on the
  // already-loaded standby element — this preserves the user-activation
  // context Chrome Android requires to start new audio while the screen
  // is locked. A single element forces a new src + play() call after
  // activation has expired, which silently rejects.
  let audioA: HTMLAudioElement;
  let audioB: HTMLAudioElement;
  let activeIsA = true;
  // `audio` always points to the currently playing element. All legacy
  // code below continues to act on `audio`, unchanged.
  $: audio = activeIsA ? audioA : audioB;
  $: standbyAudio = activeIsA ? audioB : audioA;
  let armedTrackId: number | null = null;
  let armingInFlight = false;
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
  // Pre-emptive swap guard: ensure we only swap once per track. Reset
  // on every track change.
  let preEmptiveSwapDone = false;
  // Set briefly while a fresh src is being loaded; suppresses
  // timeupdate driving the store with the old element's stale position.
  let isRestoringPosition = false;
  // How close to the natural end of the active track we trigger the
  // pre-emptive swap. Must be large enough to cover one timeupdate
  // tick (~250ms in Chrome) plus small clock jitter.
  const PRE_EMPTIVE_SWAP_LEAD_SECONDS = 0.5;

  // Reset logged flag when track ID actually changes
  $: if (currentTrack && currentTrack.id !== lastLoggedTrackId) {
    hasLoggedCurrentTrack = false;
    lastLoggedTrackId = currentTrack.id;
    lastUpdateTime = 0; // Reset progress reporting timer
    preEmptiveSwapDone = false;
  }

  // Register OS media session action handlers eagerly, BEFORE the
  // reactive metadata block below runs. Android Chrome uses the set
  // of registered handlers to decide which lock-screen controls to
  // expose; if handlers are registered after metadata, the lock
  // screen may only show play/pause.
  if (typeof window !== "undefined") {
    registerActionHandlers({
      onPlay: () => {
        if ($playerState.renderer.startsWith("local")) {
          if (audio && audio.paused) {
            audio
              .play()
              .catch((e) => console.error("[PlayerBar] MS play failed:", e));
          }
        } else {
          resume();
        }
      },
      onPause: () => {
        if ($playerState.renderer.startsWith("local")) {
          if (audio && !audio.paused) {
            audio.pause();
          }
        } else {
          pause();
        }
      },
      onNext: () => void next(),
      onPrevious: () => void previous(),
      onSeekTo: (seconds: number) => {
        if ($playerState.renderer.startsWith("local") && audio) {
          audio.currentTime = seconds;
          progress = seconds;
          updateProgress(seconds, !audio.paused);
        } else {
          seek(seconds);
        }
      },
      onStop: () => {
        if ($playerState.renderer.startsWith("local") && audio) {
          audio.pause();
          audio.currentTime = 0;
        } else {
          pause();
        }
      },
    });
  }

  // Keep OS media session in sync with current track.
  // On Android/iOS this is what prevents background throttling from killing
  // the "ended -> next track" handler when the screen locks.
  $: setMediaSessionMetadata(currentTrack);
  $: setMediaSessionPlaybackState(isPlaying, !!currentTrack);

  let lastPositionReportAt = 0;

  // Keep volume in lockstep on both audio elements (bind:volume only
  // fires on audioA). Without this the pre-armed track plays at default
  // volume after a swap.
  $: if (audioB && typeof volume === "number" && !isNaN(volume)) {
    try {
      audioB.volume = volume;
    } catch {
      /* ignore */
    }
  }

  // Pre-arm: load the next track's stream URL into the standby audio
  // element so that when the current track ends, we only need to call
  // .play() (no async fetch, no src change) which preserves the user
  // activation context Chrome Android requires for background playback.
  async function armNextTrack() {
    if (armingInFlight) return;
    if (!standbyAudio) return;
    if (!$playerState.renderer.startsWith("local")) {
      // For UPnP the backend drives advancement; nothing to arm.
      armedTrackId = null;
      return;
    }
    const target = computeNextTrackToArm(
      $playerState.queue,
      $playerState.current_index,
      $playerState.repeatMode,
    );
    if (!target || !target.track) {
      armedTrackId = null;
      // Clear stale standby src so a subsequent swap can't revive it.
      try {
        standbyAudio.removeAttribute("src");
        standbyAudio.load();
      } catch {
        /* ignore */
      }
      return;
    }
    if (armedTrackId === target.track.id) return;

    armingInFlight = true;
    try {
      const url = await getStreamUrl(target.track.id);
      // The user may have skipped while we were awaiting: re-check.
      const stillWanted = computeNextTrackToArm(
        $playerState.queue,
        $playerState.current_index,
        $playerState.repeatMode,
      );
      if (!stillWanted || stillWanted.track.id !== target.track.id) {
        armedTrackId = null;
        return;
      }
      standbyAudio.src = url;
      standbyAudio.preload = "auto";
      try {
        standbyAudio.load();
      } catch {
        /* ignore */
      }
      armedTrackId = target.track.id;
    } catch (e) {
      console.warn("[PlayerBar] armNextTrack failed:", e);
      armedTrackId = null;
    } finally {
      armingInFlight = false;
    }
  }

  // Re-arm whenever the current track, queue, or repeat mode changes.
  let lastArmedForTrackId: number | null = null;
  $: if (
    currentTrack &&
    (currentTrack.id !== lastArmedForTrackId ||
      $playerState.repeatMode !== undefined)
  ) {
    lastArmedForTrackId = currentTrack.id;
    // Debounce via microtask so reactive storms (reorder, play, etc.)
    // only trigger one armNext call.
    void Promise.resolve().then(() => armNextTrack());
  }

  // Swap the currently active audio element with the pre-armed standby.
  // SYNC play() must happen before any await so the browser keeps the
  // user-activation chain alive across the track boundary.
  // Returns true if a swap was performed.
  function swapToArmedNext(stopOldImmediately: boolean): boolean {
    const target = computeNextTrackToArm(
      $playerState.queue,
      $playerState.current_index,
      $playerState.repeatMode,
    );
    const canSwap =
      !!target &&
      !!standbyAudio &&
      !!standbyAudio.src &&
      armedTrackId === target.track.id;
    if (!canSwap || !target) return false;

    const oldEl = audio;

    // SYNC play() — must happen before any await/yield.
    const playPromise = standbyAudio.play();

    // Swap pointers immediately so the active audio reference updates.
    activeIsA = !activeIsA;
    armedTrackId = null;

    // Optimistic store update so the UI reflects the new track instantly.
    playerState.update((s) => ({
      ...s,
      current_index: target.index,
      position_seconds: 0,
      is_playing: true,
    }));
    isPlaying = true;

    if (stopOldImmediately) {
      try {
        oldEl.pause();
        oldEl.currentTime = 0;
      } catch {
        /* ignore */
      }
    }

    Promise.resolve(playPromise)
      .catch((e) => {
        console.warn("[PlayerBar] Swap play() rejected, falling back:", e);
        void next();
      })
      .finally(() => {
        // Stop the old element (after a brief overlap if we left it
        // running). Keeping audio uninterrupted across the swap is what
        // prevents the tab from being suspended on locked Android.
        if (!stopOldImmediately) {
          try {
            oldEl.pause();
            oldEl.currentTime = 0;
          } catch {
            /* ignore */
          }
        }
        // Tell the backend about the advance (no re-play).
        void advanceIndexLocal(target.index);
        // Arm the track after this one.
        void armNextTrack();
      });

    return true;
  }

  // Shared timeupdate handler. Attached to BOTH audio elements (because
  // either may be the active one after a swap) — we ignore events from
  // whichever element isn't currently the active `audio`.
  function handleTimeUpdate(ev: Event) {
    const el = ev.currentTarget as HTMLAudioElement;
    if (el !== audio) return;
    if (isRestoringPosition) return;

    const oldProgress = progress;
    progress = el.currentTime;
    duration = el.duration;
    playerState.update((s) => ({
      ...s,
      position_seconds: progress,
      is_playing: !el.paused,
    }));

    void oldProgress; // retained for future delta logic

    checkPlayThreshold();

    if (
      currentTrack &&
      Math.floor(el.currentTime) - lastUpdateTime >= 5
    ) {
      updateProgress(el.currentTime, !el.paused);
      lastUpdateTime = Math.floor(el.currentTime);
    }

    const nowMs =
      typeof performance !== "undefined" ? performance.now() : Date.now();
    if (currentTrack && el.duration && nowMs - lastPositionReportAt > 500) {
      setMediaSessionPositionState(el.currentTime, el.duration, 1);
      lastPositionReportAt = nowMs;
    }

    // Pre-emptive swap: switch to the standby element BEFORE the
    // natural end of this track. Critical for locked-screen Android:
    // the active element never fires `ended`, so the tab stays in
    // "actively playing media" state for the entire transition and
    // the new audio inherits the existing media activation context.
    if (
      !preEmptiveSwapDone &&
      el.duration > 0 &&
      el.currentTime >= el.duration - PRE_EMPTIVE_SWAP_LEAD_SECONDS &&
      armedTrackId !== null &&
      standbyAudio &&
      standbyAudio.src
    ) {
      preEmptiveSwapDone = true;
      // stopOldImmediately=false: let the old element keep playing for
      // its remaining ~0.5s so the OS sees uninterrupted audio output.
      const swapped = swapToArmedNext(false);
      if (!swapped) {
        // Re-allow another attempt if the swap was rejected (e.g.
        // armed track no longer matches because user reordered).
        preEmptiveSwapDone = false;
      }
    }
  }

  // Fires when the currently active audio element ends. This is the
  // FALLBACK path — under normal locked-screen conditions, the
  // pre-emptive swap in timeupdate runs first and `ended` never fires
  // for the active element. We keep this for cold edge cases (track
  // shorter than swap window, duration unknown, fast-forward to end).
  function handleActiveEnded(ev: Event) {
    const endedEl = ev.currentTarget as HTMLAudioElement;
    // Ignore stale listeners firing on the (now-standby) element.
    if (endedEl !== audio) return;

    if (!swapToArmedNext(true)) {
      // No pre-armed track or swap impossible — legacy path.
      void next();
    }
  }

  // Auto-resume playback when queue is loaded (reactive)
  $: if (
    !hasAttemptedAutoResume &&
    $playerState.queue.length > 0 &&
    $playerState.current_index >= 0 &&
    currentTrack
  ) {

    hasAttemptedAutoResume = true;
    // Trigger the play-local event to resume ONLY if local
    if ($playerState.renderer.startsWith("local")) {
      window.dispatchEvent(
        new CustomEvent("jamarr:play-local", { detail: currentTrack }),
      );
    } else {

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

      seek(time);
      progress = time; // Optimistic
      return;
    }

    // Local Seek
    if (audio) {

      audio.currentTime = time;
      progress = time;
      updateProgress(time, isPlaying);
    }
  }

  function handleSeekKeyDown(event: KeyboardEvent) {
    const totalDuration = currentTrack?.duration_seconds || audio?.duration || 0;
    if (!totalDuration) return;

    let nextTime: number | null = null;
    const step = Math.max(5, totalDuration * 0.05);

    if (event.key === "ArrowLeft") nextTime = Math.max(0, progress - step);
    if (event.key === "ArrowRight") nextTime = Math.min(totalDuration, progress + step);
    if (event.key === "Home") nextTime = 0;
    if (event.key === "End") nextTime = totalDuration;

    if (nextTime === null) return;

    event.preventDefault();

    if (!$playerState.renderer.startsWith("local")) {
      seek(nextTime);
      progress = nextTime;
      return;
    }

    if (audio) {
      audio.currentTime = nextTime;
      progress = nextTime;
      updateProgress(nextTime, isPlaying);
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

    // Initial Volume Sync: Capture browser-restored volume
    if (audio) {
      // Only seed browser volume for local playback.
      // Remote renderers must pull volume from the device — defaulting
      // to 100 would blast full volume on first slider touch.
      if ($playerState.volume === null && $playerState.renderer.includes("local")) {
        playerState.update((s) => ({
          ...s,
          volume: Math.round(audio.volume * 100),
        }));
      }
    }

    const playLocalTrack = async (track: any) => {

      // Relaxed check: Accept "local" or "local:..."
      if (!$playerState.renderer.includes("local")) return;

      if (!audio) {
        console.error("[PlayerBar] Audio element not found!");
        return;
      }

      // Check if we're switching to a different track
      const currentSrc = audio.src;
      let newSrc = `/api/stream/${track.id}`;
      try {
        newSrc = await getStreamUrl(track.id);
      } catch (e) {
        console.error("[PlayerBar] Failed to fetch stream URL:", e);
        return;
      }
      
      // Fix: isSameTrack check can be tricky with full URLs. 
      // We know we are changing tracks if the IDs don't match or src is different.
      // But for "reload" scenario, src might be empty or same.
      const isSameTrack = currentSrc.includes(`/api/stream/${track.id}`);

      // Prevent timeupdate from syncing 0 to store while we setup
      isRestoringPosition = true;

      const savedPosition = $playerState.position_seconds || 0;
      const isColdStart = !currentSrc || currentSrc === window.location.href; 
      
      // Define restoration logic to run once metadata is loaded
      const onLoadedMetadata = () => {

           
           // Check if we should restore
           if ((isSameTrack || isColdStart) && savedPosition > 0) {

              // Wrap in try-catch as setting currentTime can sometimes throw if not ready
              try {
                  audio.currentTime = savedPosition;
              } catch (e) {
                  console.error("[PlayerBar] Failed to set currentTime:", e);
              }
           } else {

              // We do NOT reset store here, because we want only 'timeupdate' to drive the store
              // efficiently, and we don't want to flash 0 if we can avoid it, 
              // but for a new track starting at 0 is correct.
              audio.currentTime = 0;
              playerState.update((s) => ({ ...s, position_seconds: 0 }));
           }

           // Allow updates again after a short delay
           setTimeout(() => {
              isRestoringPosition = false;
           }, 200);
      };

      // Attach one-time listener BUT also check if readyState is already enough
      // readyState >= 1 means HAVE_METADATA
      if (audio.readyState >= 1) {

           onLoadedMetadata();
      } else {
           audio.addEventListener("loadedmetadata", onLoadedMetadata, { once: true });
           
           // FAIL-SAFE: If loadedmetadata never fires (e.g. network stall), clear the flag eventually
           setTimeout(() => {
               if (isRestoringPosition) {
                   console.warn("[PlayerBar] loadedmetadata timed out, clearing isRestoringPosition flag");
                   isRestoringPosition = false;
               }
           }, 2000);
      }

      audio.src = newSrc;

      // Force Playback immediately - User action (click) initiated this chain
      audio
        .play()
        .then(() => {

          isPlaying = true;
          playerState.update((s) => ({ ...s, is_playing: true }));
        })
        .catch((e) => {
          console.warn("[PlayerBar] Auto-play blocked or failed:", e.message);
          // Don't revert state to false, let user try again if needed
        });
    };

    window.addEventListener("jamarr:play-local", (e: CustomEvent) => {
      const track = e.detail;
      void playLocalTrack(track);
    });

    window.addEventListener("jamarr:seek", (e: CustomEvent) => {

      if (!$playerState.renderer.startsWith("local") || !audio) return;

      const pos = e.detail.position;
      if (typeof pos === "number" && !isNaN(pos)) {
        audio.currentTime = pos;
        progress = pos; // Update local state immediately
        updateProgress(pos, isPlaying);
      }
    });

    window.addEventListener("jamarr:pause", () => {

      if (!$playerState.renderer.startsWith("local") || !audio) return;
      audio.pause();
      isPlaying = false;
      updateProgress(audio.currentTime, false);
    });

    window.addEventListener("jamarr:resume", () => {

      if (!$playerState.renderer.startsWith("local") || !audio) return;
      audio.play().catch((e) => console.error("[PlayerBar] Resume failed:", e));
      isPlaying = true;
      updateProgress(audio.currentTime, true);
    });

    // Attach timeupdate + ended to BOTH audio elements. After a swap,
    // `audio` reactively points to the other element; the handlers
    // each early-return if their event source isn't currently active.
    if (audioA) {
      audioA.addEventListener("timeupdate", handleTimeUpdate);
      audioA.addEventListener("ended", handleActiveEnded);
    } else {
      console.error("[PlayerBar] audioA element not found in onMount!");
    }
    if (audioB) {
      audioB.addEventListener("timeupdate", handleTimeUpdate);
      audioB.addEventListener("ended", handleActiveEnded);
    }

    // Polling for remote playback
    let lastTransportState = "";

    const interval = setInterval(async () => {
      const shouldPollRemote =
        !$playerState.renderer.startsWith("local") &&
        ($playerState.is_playing || Boolean(currentTrack));
      if (shouldPollRemote) {
        try {
          const res = await fetchWithAuth("/api/player/state", {
            headers: getHeaders(),
          });
          if (res.ok) {
            const state = await res.json();
            progress = state.position_seconds;

            // Update OS media session position (throttled to ~2/sec).
            const nowMs =
              typeof performance !== "undefined" ? performance.now() : Date.now();
            const remoteDuration = currentTrack?.duration_seconds || 0;
            if (
              currentTrack &&
              remoteDuration &&
              nowMs - lastPositionReportAt > 500
            ) {
              setMediaSessionPositionState(progress, remoteDuration, 1);
              lastPositionReportAt = nowMs;
            }

            // Sync Store (Queue, Index, IsPlaying)
            // This ensures if backend auto-advanced, we reflect it
            playerState.update((s) => {
              let newState = { ...s, position_seconds: state.position_seconds };
              let changed = false;

              if (s.position_seconds !== state.position_seconds) {
                changed = true;
              }

              if (s.current_index !== state.current_index) {

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

              // Sync volume from device for remote renderers
              if (
                state.volume !== null &&
                state.volume !== undefined &&
                s.volume !== state.volume
              ) {
                newState.volume = state.volume;
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

  onDestroy(() => {
    clearMediaSession();
  });

  function togglePlay() {
    // Remote / UPnP Logic
    if (!$playerState.renderer.startsWith("local")) {
      if ($playerState.is_playing) {

        pause();
        isPlaying = false; // Optimistic update
      } else {

        resume();
        isPlaying = true; // Optimistic update
      }
      return;
    }


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

      // Force is_playing to true so the event handler actually plays
      playerState.update((s) => ({ ...s, is_playing: true }));
      window.dispatchEvent(
        new CustomEvent("jamarr:play-local", { detail: currentTrack }),
      );
      return;
    }

    // Local Audio Logic
    if (audio.paused) {

      audio.play().catch((e) => console.error("[PlayerBar] Play failed:", e));
      isPlaying = true;
      updateProgress(audio.currentTime, true);
    } else {

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
  class="fixed bottom-0 w-full surface-glass-panel border-t border-subtle p-3 md:p-4 text-default z-50"
>
  <div class="mx-auto flex max-w-[1700px] flex-col gap-3 md:hidden">
    <div class="flex items-center gap-3">
      {#if currentTrack}
        <button
          class="relative h-12 w-12 flex-shrink-0 overflow-hidden rounded-lg bg-surface-3"
          aria-label="Open queue"
          on:click={toggleQueue}
        >
          <img
            src={currentTrack.art_sha1
              ? getArtUrl(currentTrack.art_sha1, 60)
              : "/assets/logo.png"}
            alt="Art"
            class="h-full w-full object-cover"
            on:error={handleImageError}
          />
        </button>
        <div class="min-w-0 flex-1">
          <div class="truncate text-sm font-semibold text-default">
            {currentTrack.title}
          </div>
          <div class="truncate text-xs text-muted">
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
          <div class="mt-0.5 text-[11px] text-subtle">
            {#if $playerState.queue.length > 0}
              {$playerState.current_index + 1} of {$playerState.queue.length}
            {:else}
              Ready to play
            {/if}
          </div>
        </div>
      {:else}
        <div class="min-w-0 flex-1">
          <div class="text-sm font-medium text-muted">No track playing</div>
        </div>
      {/if}

      <button
        class="btn btn-outline btn-sm flex-shrink-0"
        title="Queue"
        on:click={toggleQueue}
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
            d="M4 6h16M4 12h16M4 18h16"
          ></path>
        </svg>
      </button>
    </div>

    <div class="flex items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <button
          class="btn btn-outline btn-sm"
          aria-label="Previous track"
          on:click={previous}
        >
          <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
            <path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" />
          </svg>
        </button>

        <button class="btn btn-primary" on:click={togglePlay}>
          {#if isPlaying}
            <svg class="h-6 w-6" fill="currentColor" viewBox="0 0 24 24">
              <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
            </svg>
          {:else}
            <svg class="h-6 w-6" fill="currentColor" viewBox="0 0 24 24">
              <path d="M8 5v14l11-7z" />
            </svg>
          {/if}
        </button>

        <button
          class="btn btn-outline btn-sm"
          aria-label="Next track"
          on:click={next}
        >
          <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
            <path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" />
          </svg>
        </button>
      </div>

      <div class="flex items-center gap-2">
        <button
          class="btn btn-outline btn-sm {$playerState.repeatMode !== 'off'
            ? 'border-accent bg-accent/10 text-accent'
            : ''}"
          on:click={toggleRepeat}
          title="Repeat: {$playerState.repeatMode}"
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
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
            />
            {#if $playerState.repeatMode === "one"}
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M12 11L12 17"
              />
            {/if}
          </svg>
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
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"
            />
          </svg>
        </button>

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
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M4 8h16M4 16h10m-6-8v8"
            ></path>
          </svg>
        </button>
      </div>
    </div>

    <div class="flex items-center gap-2 text-[11px] text-muted">
      <span class="w-9 text-left">{formatTime(progress)}</span>
      <div
        class="relative h-4 flex-1 cursor-pointer"
        on:click={handleSeek}
        on:keydown={handleSeekKeyDown}
        role="slider"
        aria-valuenow={progress}
        aria-valuemin={0}
        aria-valuemax={duration || 100}
        tabindex="0"
      >
        <div class="absolute top-1/2 h-1 w-full -translate-y-1/2 rounded-full bg-surface-3 overflow-hidden">
          <div
            class="h-full bg-accent transition-all duration-100 ease-linear"
            style="width: {(progress / (duration || 1)) * 100}%"
          ></div>
        </div>
      </div>
      <span class="w-9 text-right">{formatTime(duration)}</span>
    </div>
  </div>

  <div class="hidden items-center justify-between max-w-[1700px] mx-auto md:flex">
    <!-- Track Info -->
    <div class="flex items-center gap-4 w-1/3">
      {#if currentTrack}
        <div
          class="relative h-14 w-14 flex-shrink-0 rounded-sm bg-surface-3 overflow-hidden group"
        >
          <img
            src={currentTrack.art_sha1
              ? getArtUrl(currentTrack.art_sha1, 60)
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
            class="h-full w-full rounded-sm object-contain"
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

  <audio bind:this={audioA} bind:volume preload="auto"></audio>
  <audio bind:this={audioB} preload="auto"></audio>
</div>

<QueueDrawer
  visible={showQueue}
  on:close={closeQueue}
  on:clear={clearAndStopQueue}
/>

<NowPlayingOverlay />
