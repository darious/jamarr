<script lang="ts">
  import {
    playerState,
    next,
    previous,
    playFromQueue,
    updateProgress,
    setVolume,
  } from "$stores/player";
  import { onMount } from "svelte";
  import { page } from "$app/stores";
  import { goto } from "$app/navigation";

  let audio: HTMLAudioElement;
  let isPlaying = false;
  let currentTrack: any = null;
  let progress = 0;
  let duration = 0;
  let volume = 1;
  let deviceName = "Local"; // Default name
  let lastDeviceName = "Local"; // Track previous device to detect changes
  let hasLoggedCurrentTrack = false; // Track if we've logged this track to history
  let lastLoggedTrackId: number | null = null; // Track the last logged track ID
  let hasAttemptedAutoResume = false; // Track if we've already tried to auto-resume

  // Subscribe to store
  $: currentTrack = $playerState.queue[$playerState.current_index];
  $: isPlaying = $playerState.is_playing;
  $: {
    const r = $playerState.renderers.find(
      (r) => r.udn === $playerState.renderer,
    );
    deviceName = r ? r.name : "Local";

    // Check for switch to "Office"
    if (deviceName === "Office" && lastDeviceName !== "Office") {
      console.log("[PlayerBar] Switched to Office, defaulting volume to 20%");
      volume = 0.2;
      setVolume(20);
    }
    lastDeviceName = deviceName;
  }

  // Reset logged flag when track ID actually changes
  $: if (currentTrack && currentTrack.id !== lastLoggedTrackId) {
    hasLoggedCurrentTrack = false;
    console.log("[PlayerBar] Track changed, reset hasLoggedCurrentTrack");
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
    // Trigger the play-local event to resume
    window.dispatchEvent(
      new CustomEvent("jamarr:play-local", { detail: currentTrack }),
    );
  }

  async function logPlayToHistory(track: any) {
    if (!track || hasLoggedCurrentTrack) return;

    try {
      const hostname = window.location.hostname;
      await fetch("/api/player/log-play", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          track_id: track.id,
          hostname,
        }),
      });
      hasLoggedCurrentTrack = true;
      lastLoggedTrackId = track.id;
      console.log("[PlayerBar] Logged play to history:", track.title);
    } catch (e) {
      console.error("[PlayerBar] Failed to log play:", e);
    }
  }

  function checkPlayThreshold() {
    if (!currentTrack || !audio || hasLoggedCurrentTrack) return;

    const playedSeconds = audio.currentTime;
    const totalSeconds = audio.duration;

    if (!totalSeconds || totalSeconds === 0) return;

    // Log if played for 30 seconds OR 20% of track length, whichever is shorter
    const threshold = Math.min(30, totalSeconds * 0.2);

    if (playedSeconds >= threshold) {
      logPlayToHistory(currentTrack);
    }
  }

  onMount(() => {
    console.log("[PlayerBar] onMount called, setting up event listener");
    window.addEventListener("jamarr:play-local", (e: CustomEvent) => {
      console.log("[PlayerBar] jamarr:play-local event received:", e.detail);
      const track = e.detail;
      if (audio) {
        console.log(
          "[PlayerBar] Setting audio src to:",
          `/api/stream/${track.id}`,
        );
        audio.src = `/api/stream/${track.id}`;

        // Check if we should resume from a saved position
        const savedPosition = $playerState.position_seconds || 0;
        if (savedPosition > 0) {
          console.log("[PlayerBar] Resuming from position:", savedPosition);
          audio.currentTime = savedPosition;
        }

        // Only auto-play if was playing before AND user has interacted
        // (browser blocks auto-play without user interaction)
        if ($playerState.is_playing) {
          audio
            .play()
            .then(() => {
              console.log("[PlayerBar] Audio playback started successfully");
              isPlaying = true;
            })
            .catch((e) => {
              console.warn(
                "[PlayerBar] Auto-play blocked by browser, user must click play:",
                e.message,
              );
              // Update state to reflect that we're not actually playing
              updateProgress(audio.currentTime, false);
            });
        }
      } else {
        console.error("[PlayerBar] Audio element not found!");
      }
    });

    if (audio) {
      console.log(
        "[PlayerBar] Audio element found, adding timeupdate and ended listeners",
      );
      let timeupdateCount = 0;
      let lastUpdateTime = 0;
      audio.addEventListener("timeupdate", () => {
        timeupdateCount++;
        const oldProgress = progress;
        progress = audio.currentTime;
        duration = audio.duration;

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
    const interval = setInterval(async () => {
      if ($playerState.renderer !== "local" && $playerState.is_playing) {
        try {
          const res = await fetch("/api/player/state");
          if (res.ok) {
            const state = await res.json();
            progress = state.position_seconds;
            // Only update duration if needed, usually static per track
          }
        } catch (e) {
          console.error("Polling error", e);
        }
      }
    }, 1000);

    return () => clearInterval(interval);
  });

  function togglePlay() {
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

    // If no source is set, try to resume the current track
    if (!audio.src || audio.src === window.location.href) {
      console.log(
        "[PlayerBar] togglePlay: no src set, dispatching play-local event",
      );
      if (currentTrack) {
        window.dispatchEvent(
          new CustomEvent("jamarr:play-local", { detail: currentTrack }),
        );
      } else {
        console.error("[PlayerBar] togglePlay: no currentTrack to play");
      }
      return;
    }

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
    if ($page.url.pathname === "/queue") {
      history.back();
    } else {
      goto("/queue");
    }
  }

  function handleImageError(e: Event) {
    const img = e.currentTarget as HTMLImageElement;
    img.src = "/assets/logo.png";
  }
</script>

<div
  class="fixed bottom-0 w-full bg-surface-900 border-t border-white/10 p-4 text-white z-50"
>
  <div class="flex items-center justify-between max-w-[1700px] mx-auto">
    <!-- Track Info -->
    <div class="flex items-center gap-4 w-1/3">
      {#if currentTrack}
        <div
          class="relative h-14 w-14 flex-shrink-0 rounded bg-surface-800 overflow-hidden group"
        >
          <img
            src={currentTrack.art_id
              ? `/art/${currentTrack.art_id}`
              : "/assets/logo.png"}
            alt="Art"
            class="h-full w-full object-cover"
            on:error={handleImageError}
          />
          <button
            class="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
            on:click={toggleQueue}
          >
            <svg
              class="w-6 h-6 text-white"
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
        <div class="min-w-0">
          <div class="font-medium truncate">{currentTrack.title}</div>
          <div class="text-sm text-white/60 truncate">
            {currentTrack.artist}
          </div>
          <div class="flex items-center gap-2 text-xs text-white/40 mt-0.5">
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
        <div class="text-white/40">No track playing</div>
      {/if}
    </div>

    <!-- Controls -->
    <div class="flex flex-col items-center gap-2 w-1/3">
      <div class="flex items-center gap-4">
        <button class="btn btn-ghost btn-sm btn-circle" on:click={previous}>
          <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24"
            ><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" /></svg
          >
        </button>

        <button class="btn btn-circle btn-primary" on:click={togglePlay}>
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

        <button class="btn btn-ghost btn-sm btn-circle" on:click={next}>
          <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24"
            ><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" /></svg
          >
        </button>
      </div>

      <!-- Progress -->
      <div
        class="flex items-center gap-2 w-full max-w-md text-xs text-white/60"
      >
        <span>{formatTime(progress)}</span>
        <input
          type="range"
          min="0"
          max={duration || 100}
          value={progress}
          class="range range-xs range-primary"
          on:input={(e) => {
            if (audio) audio.currentTime = parseFloat(e.currentTarget.value);
          }}
        />
        <span>{formatTime(duration)}</span>
      </div>
    </div>

    <!-- Volume / Extra -->
    <div class="w-1/3 flex justify-end items-center gap-4">
      <div class="text-xs text-white/40">{deviceName}</div>
      <div class="flex items-center gap-2 group">
        <svg
          class="h-5 w-5 text-white/60"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          ><path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z"
          ></path></svg
        >
        <input
          type="range"
          min="0"
          max="1"
          step="0.01"
          value={volume}
          on:input={(e) => {
            const val = parseFloat(e.currentTarget.value);
            volume = val;
            if ($playerState.renderer !== "local") {
              setVolume(Math.round(val * 100)); // Convert 0-1 to 0-100
            }
          }}
          class="range range-xs range-primary w-24 opacity-0 group-hover:opacity-100 transition-opacity"
        />
      </div>
      <button
        class="btn btn-ghost btn-sm btn-circle"
        title="Queue"
        on:click={toggleQueue}
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

  <audio bind:this={audio} bind:volume />
</div>
