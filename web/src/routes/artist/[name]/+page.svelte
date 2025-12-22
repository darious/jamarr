<script lang="ts">
  import type { Album, Artist, Track, MissingAlbum } from "$lib/api";
  import {
    fetchTracks,
    refreshArtistMetadata,
    refreshArtistSingles,
    fetchMissingAlbums,
    triggerMissingAlbumsScan,
    triggerMetadataScan,
  } from "$lib/api";
  import { goto, invalidateAll } from "$app/navigation";
  import { addToQueue, loadQueueFromServer, setQueue } from "$stores/player";
  import { browser } from "$app/environment";

  export let data: {
    name: string;
    canonicalName: string;
    artist?: Artist;
    albums: Album[];
    similarArtists: {
      name: string;
      art_id?: number | null;
      art_sha1?: string | null;
    }[];
  };

  let artist: Artist | undefined = data.artist;
  let tracks: Track[] = [];
  let loadingTracks = true;
  let refreshing = false;
  let refreshingSingles = false;
  let message = "";
  let lastKey = "";

  // Missing Albums State
  let missingAlbums: MissingAlbum[] = [];
  let loadingMissingAlbums = false;
  let scanningMissing = false;

  const loadMissingAlbums = async () => {
    if (!artist?.mbid) return;
    loadingMissingAlbums = true;
    try {
      missingAlbums = await fetchMissingAlbums(artist.mbid);
    } catch (e) {
      console.error("Failed to load missing albums", e);
    } finally {
      loadingMissingAlbums = false;
    }
  };

  const scanMissing = async () => {
    if (!artist?.mbid) return;
    scanningMissing = true;
    try {
      await triggerMissingAlbumsScan(artist.mbid);
      message = "Scanning for missing albums...";
      // Poll for a bit or just wait
      setTimeout(() => {
        loadMissingAlbums();
        scanningMissing = false;
        message = "Missing albums scan complete.";
        setTimeout(() => {
          if (message.includes("scan complete")) message = "";
        }, 3000);
      }, 5000);
    } catch (e) {
      console.error(e);
      scanningMissing = false;
      message = "Failed to start scan.";
    }
  };

  $: if (artist?.mbid) {
    loadMissingAlbums();
  }

  // Update artist when route data changes (client nav)
  $: if (data.artist !== artist) {
    artist = data.artist;
  }

  const refreshTracks = async () => {
    loadingTracks = true;
    try {
      try {
        await loadQueueFromServer();
      } catch (e) {
        // Non-fatal in dev if backend not ready
        console.warn("Queue sync failed", e);
      }
      tracks = await fetchTracks({ artist: data.canonicalName || data.name });
    } catch (e) {
      console.error("Track load failed", e);
      tracks = [];
    } finally {
      loadingTracks = false;
    }
  };

  $: if (browser && data.canonicalName && data.canonicalName !== lastKey) {
    lastKey = data.canonicalName;
    void refreshTracks();
  }

  if (browser && !lastKey) {
    lastKey = data.canonicalName || data.name;
    void refreshTracks();
  }

  const formatDuration = (seconds?: number | null) => {
    if (!seconds) return "—";
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60)
      .toString()
      .padStart(2, "0");
    return `${mins}:${secs}`;
  };

  $: displayedTopTracks = (() => {
    const fromMeta = artist?.top_tracks || [];
    return fromMeta.map((t) => {
      if (t.local_track_id) {
        // Track is in library - find full track object
        const local = tracks.find((lt) => lt.id === t.local_track_id);
        if (local) return local;

        // Fallback if track not loaded yet - use API data
        return {
          id: t.local_track_id,
          title: t.name,
          album: t.album || "",
          artist: artist?.name || "",
          duration_seconds:
            t.duration_seconds ||
            (t.duration_ms ? Math.round(t.duration_ms / 1000) : null),
          codec: t.codec,
          bit_depth: t.bit_depth,
          sample_rate_hz: t.sample_rate_hz,
        };
      } else {
        // Track not in library - return placeholder
        return {
          id: -1,
          title: t.name,
          album: t.album || "",
          artist: artist?.name || "",
          duration_seconds: t.duration_ms
            ? Math.round(t.duration_ms / 1000)
            : null,
        };
      }
    });
  })();

  $: displayedSimilarArtists = (() => {
    return artist?.similar_artists || [];
  })();

  $: displayedSingles = (() => {
    const singles = artist?.singles || [];
    return singles
      .map((s) => {
        let tracksToPlay: Track[] = [];
        let techData = {};
        let localId = null;
        let navAlbum = null;
        let art_id = null;
        let art_sha1 = null;

        if (s.local_track_id) {
          // Single is in library - find the track
          const localTrack = tracks.find((t) => t.id === s.local_track_id);
          if (localTrack) {
            localId = s.title; // Use title as ID
            navAlbum = localTrack.album;
            tracksToPlay = [localTrack];
            techData = {
              codec: s.codec || localTrack.codec,
              bit_depth: s.bit_depth || localTrack.bit_depth,
              sample_rate_hz: s.sample_rate_hz || localTrack.sample_rate_hz,
            };

            // Get artwork from album
            const album = data.albums.find((a) => a.album === localTrack.album);
            if (album) {
              art_id = album.art_id;
              art_sha1 = album.art_sha1;
            }
          }
        }

        return {
          ...s,
          localId,
          art_id,
          art_sha1,
          navAlbum,
          ...techData,
          tracksToPlay,
        };
      })
      .sort((a, b) => {
        const dateA = a.date || "";
        const dateB = b.date || "";
        return dateA.localeCompare(dateB);
      });
  })();

  $: displayedMissingAlbums = (() => {
    const missing = artist?.albums || [];
    return missing.filter((m) => {
      // Filter out if we have this album in our library
      // Loose matching on title
      const hasAlbum = data.albums.some(
        (a) => a.album.toLowerCase().trim() === m.title.toLowerCase().trim(),
      );
      return !hasAlbum;
    });
  })();

  $: mainAlbums = data.albums.filter((a) => !a.type || a.type === "main");

  $: appearsOnAlbums = data.albums.filter((a) => a.type === "appears_on");

  async function refreshMeta() {
    refreshing = true;
    message = "Requesting fresh metadata...";
    try {
      if (artist?.mbid) {
        // "Replace everything except missing albums"
        // bioOnly=true fetches Bio + Images + Links, but skips Release Groups (Albums)
        // missingOnly=false forces a refresh even if data exists
        await triggerMetadataScan({
          mbidFilter: artist.mbid,
          bioOnly: true,
          missingOnly: false,
          linksOnly: false,
        });
      } else {
        await refreshArtistMetadata(data.canonicalName || data.name);
      }
      message = "Metadata updated. Reloading...";
      await invalidateAll();
      message = "Metadata updated successfully!";
      setTimeout(() => {
        if (message === "Metadata updated successfully!") message = "";
      }, 3000);
    } catch (e) {
      console.error(e);
      message = "Failed to refresh metadata.";
    } finally {
      refreshing = false;
    }
  }

  async function refreshSingles() {
    refreshingSingles = true;
    try {
      await refreshArtistSingles(data.canonicalName || data.name);
      message = "Singles updated. Reloading...";
      await invalidateAll();
      message = "Singles updated successfully!";
      setTimeout(() => {
        if (message === "Singles updated successfully!") message = "";
      }, 3000);
    } catch (e) {
      message = "Failed to refresh singles.";
    } finally {
      refreshingSingles = false;
    }
  }

  async function playAllSingles() {
    const allSingleTracks: Track[] = [];
    for (const single of displayedSingles) {
      if (single.tracksToPlay && single.tracksToPlay.length > 0) {
        allSingleTracks.push(...single.tracksToPlay);
      }
    }
    if (allSingleTracks.length > 0) {
      await setQueue(allSingleTracks, 0);
    }
  }

  async function playAlbum(album: Album) {
    const albumTracks = tracks.filter((t) => t.album === album.album);
    if (albumTracks.length) {
      await setQueue(albumTracks, 0);
    } else {
      goto(
        `/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`,
      );
    }
  }

  async function addAlbumToQueue(album: Album) {
    const albumTracks = tracks.filter((t) => t.album === album.album);
    if (albumTracks.length) {
      await addToQueue(albumTracks);
    }
  }

  async function playTrackById(trackId: number) {
    const track = tracks.find((t) => t.id === trackId);
    if (track) {
      await setQueue([track], 0);
    }
  }

  async function addTrackToQueue(trackId: number) {
    const track = tracks.find((t) => t.id === trackId);
    if (track) {
      await addToQueue([track]);
    }
  }

  function handleImageError(e: Event) {
    (e.currentTarget as HTMLImageElement).src = "/assets/logo.png";
  }
</script>

<div class="fixed inset-0 z-0 overflow-hidden pointer-events-none">
  <div
    class="absolute inset-0 bg-cover bg-center blur-3xl opacity-30 scale-110"
    style={`background-image:url('${artist?.art_sha1 ? `/art/file/${artist.art_sha1}` : artist?.art_id ? `/art/${artist.art_id}` : "/assets/default-artist.svg"}')`}
  ></div>
  <div
    class="absolute inset-0 bg-gradient-to-b from-surface-900/50 via-surface-900/80 to-surface-900"
  ></div>
</div>

<section
  class="relative z-10 mx-auto flex w-full max-w-[1700px] flex-col gap-10 px-8 py-10"
>
  <div class="grid gap-8 md:grid-cols-[300px,1fr] items-start">
    <div
      class="relative aspect-square w-full max-w-[300px] rounded-2xl overflow-hidden shadow-2xl"
    >
      <img
        class="h-full w-full object-cover"
        src={artist?.art_sha1
          ? `/art/file/${artist.art_sha1}`
          : artist?.art_id
            ? `/art/${artist.art_id}`
            : "/assets/default-artist.svg"}
        alt={artist?.name ?? data.name}
      />
    </div>

    <div class="space-y-6">
      <div class="space-y-2">
        <p class="pill w-max bg-white/10 text-white/70 backdrop-blur-md">
          Artist
        </p>
        <h1 class="text-4xl md:text-6xl font-bold tracking-tight">
          {artist?.name ?? data.name}
        </h1>
      </div>

      <div class="flex flex-wrap gap-2">
        {#if artist?.homepage}
          <a
            class="pill hover:bg-white/15"
            target="_blank"
            href={artist.homepage}
          >
            <svg class="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
              <path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z" />
            </svg>
            Homepage
          </a>
        {/if}
        {#if artist?.musicbrainz_url}
          <a
            class="pill hover:bg-white/15"
            target="_blank"
            href={artist.musicbrainz_url}
          >
            <img
              src="/assets/logo-musicbrainz.svg"
              alt="MusicBrainz"
              class="h-4 w-4"
            /> MusicBrainz
          </a>
        {/if}
        {#if artist?.wikipedia_url}
          <a
            class="pill hover:bg-white/15"
            target="_blank"
            href={artist.wikipedia_url}
          >
            <img
              src="/assets/logo-wikipedia.svg"
              alt="Wikipedia"
              class="h-4 w-4"
            /> Wiki
          </a>
        {/if}
        {#if artist?.tidal_url}
          <a
            class="pill hover:bg-white/15"
            target="_blank"
            href={artist.tidal_url}
          >
            <img src="/assets/logo-tidal.png" alt="Tidal" class="h-4 w-4" /> Tidal
          </a>
        {/if}

        {#if artist?.qobuz_url}
          <a
            class="pill hover:bg-white/15"
            target="_blank"
            href={artist.qobuz_url}
          >
            <img src="/assets/logo-qobuz.png" alt="Qobuz" class="h-4 w-4" /> Qobuz
          </a>
        {/if}
        {#if artist?.spotify_url}
          <a
            class="pill hover:bg-white/15"
            target="_blank"
            href={artist.spotify_url}
          >
            <img src="/assets/logo-spotify.svg" alt="Spotify" class="h-4 w-4" />
            Spotify
          </a>
        {/if}
      </div>

      <div class="flex items-center gap-6 text-sm text-white/60">
        <a
          href="#albums"
          class="hover:text-white hover:underline transition-colors"
          >{data.albums.length} Albums</a
        >
        <a
          href="#missing-albums"
          class="hover:text-white hover:underline transition-colors"
          >{missingAlbums.length} Missing</a
        >
        <span>{loadingTracks ? "Loading…" : tracks.length} Tracks</span>
        <button
          class="btn btn-ghost btn-sm"
          on:click={refreshMeta}
          disabled={refreshing}
        >
          {refreshing ? "Refreshing…" : "Refresh Metadata"}
        </button>
        <button
          class="btn btn-ghost btn-sm"
          on:click={scanMissing}
          disabled={scanningMissing}
        >
          {scanningMissing ? "Scanning..." : "Check Missing"}
        </button>
      </div>
      {#if message}
        <p class="text-sm text-white/60">{message}</p>
      {/if}

      <div class="prose prose-invert max-w-none">
        <p
          class="whitespace-pre-line text-white/80 leading-relaxed line-clamp-[10] hover:line-clamp-none transition-all"
        >
          {artist?.bio || "No biography available yet."}
        </p>
      </div>
    </div>
  </div>

  <div class="grid gap-8 md:grid-cols-3 items-start">
    <div class="space-y-4 h-full flex flex-col">
      <div class="section-head">
        <div>
          <p class="text-sm uppercase tracking-wide text-white/60">Essential</p>
          <h3 class="text-xl font-semibold">Top tracks</h3>
        </div>
      </div>
      <div class="glass-panel flex-1 min-h-0 overflow-hidden flex flex-col">
        <div class="overflow-y-auto max-h-[360px] divide-y divide-white/5">
          {#if loadingTracks}
            <div class="h-24 animate-pulse"></div>
          {:else if displayedTopTracks.length === 0}
            <div class="p-4 text-white/60">No tracks yet.</div>
          {:else}
            {#each displayedTopTracks as track, idx}
              <div
                class="group flex items-center gap-4 px-4 py-3 hover:bg-white/5 transition-colors"
              >
                <div class="w-8 text-center text-xs text-white/50">
                  {idx + 1}
                </div>

                <div
                  class="h-12 w-12 flex-shrink-0 rounded bg-white/10 overflow-hidden relative"
                >
                  {#if track.id && track.id > 0}
                    <img
                      src={(() => {
                        const alb = data.albums.find(
                          (a) => a.album === track.album,
                        );
                        if (alb?.art_sha1) return `/art/file/${alb.art_sha1}`;
                        if (alb?.art_id) return `/art/${alb.art_id}`;
                        return "/assets/default-artist.svg"; // Fallback
                      })()}
                      alt={track.album}
                      class="h-full w-full object-cover"
                      on:error={handleImageError}
                    />
                    <div
                      class="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <button
                        class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-sm hover:scale-110 transition-transform"
                        title="Play"
                        on:click|stopPropagation={() => playTrackById(track.id)}
                      >
                        <svg
                          class="h-5 w-5"
                          fill="currentColor"
                          viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg
                        >
                      </button>
                    </div>
                  {:else}
                    <div
                      class="h-full w-full flex items-center justify-center bg-white/5"
                    >
                      <span class="text-white/10 text-xs">•</span>
                    </div>
                  {/if}
                </div>

                <div class="flex-1 min-w-0">
                  <p
                    class={`truncate text-sm font-semibold ${track.id > 0 ? "text-white/90 group-hover:text-white" : "text-white/30 line-through"}`}
                  >
                    {track.title}
                  </p>
                  <div
                    class={`flex items-center gap-2 text-xs mt-0.5 ${track.id > 0 ? "text-white/50" : "text-white/20 line-through"}`}
                  >
                    <a
                      href={`/album/${encodeURIComponent(artist?.name || "")}/${encodeURIComponent(track.album)}`}
                      class="hover:text-white hover:underline"
                      on:click|stopPropagation
                    >
                      {track.album}
                    </a>
                    {#if track.codec}
                      <span class="text-white/30">•</span>
                      <span class="uppercase">{track.codec}</span>
                    {/if}
                    {#if track.bit_depth && track.sample_rate_hz}
                      <span class="text-white/30">•</span>
                      <span
                        >{track.bit_depth}bit / {track.sample_rate_hz /
                          1000}kHz</span
                      >
                    {/if}
                  </div>
                </div>

                <div class="flex items-center gap-4">
                  {#if track.id && track.id > 0}
                    <button
                      class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-xs opacity-0 group-hover:opacity-100 transition-opacity"
                      title="Add to Queue"
                      on:click|stopPropagation={() => addTrackToQueue(track.id)}
                    >
                      <svg
                        class="h-4 w-4"
                        fill="currentColor"
                        viewBox="0 0 24 24"
                        ><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg
                      >
                    </button>
                  {/if}
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
      </div>
    </div>

    <div class="space-y-4 h-full flex flex-col">
      <div class="section-head">
        <div>
          <p class="text-sm uppercase tracking-wide text-white/60">Releases</p>
          <h3 class="text-xl font-semibold">Singles</h3>
        </div>
        <button
          class="btn btn-ghost btn-sm"
          on:click={playAllSingles}
          title="Play All Singles"
        >
          ▶ Play All
        </button>
      </div>
      <div class="glass-panel flex-1 min-h-0 overflow-hidden flex flex-col">
        <div class="overflow-y-auto max-h-[360px] divide-y divide-white/5">
          {#if artist?.singles?.length}
            {#each displayedSingles as single}
              <div
                class="group flex items-center gap-4 px-4 py-3 hover:bg-white/5 transition-colors"
              >
                <div
                  class="h-12 w-12 flex-shrink-0 rounded bg-white/10 overflow-hidden relative"
                >
                  {#if single.art_sha1 || single.art_id}
                    <img
                      src={single.art_sha1
                        ? `/art/file/${single.art_sha1}`
                        : `/art/${single.art_id}`}
                      alt={single.title}
                      class="h-full w-full object-cover"
                    />
                    {#if single.localId}
                      <div
                        class="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        <button
                          class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-sm hover:scale-110 transition-transform"
                          title="Play"
                          on:click|stopPropagation={() => {
                            if (
                              single.tracksToPlay &&
                              single.tracksToPlay.length > 0
                            ) {
                              setQueue(single.tracksToPlay, 0);
                            }
                          }}
                        >
                          <svg
                            class="h-5 w-5"
                            fill="currentColor"
                            viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg
                          >
                        </button>
                      </div>
                    {/if}
                  {:else}
                    <div
                      class="h-full w-full flex items-center justify-center bg-white/5"
                    >
                      <span class="text-white/10 text-xs">•</span>
                    </div>
                  {/if}
                </div>

                <div class="flex-1 min-w-0">
                  <button
                    class={`truncate text-sm font-semibold text-left w-full ${single.localId ? "text-white/90 group-hover:text-white" : "text-white/30 line-through"}`}
                    disabled={!single.localId}
                    on:click={() =>
                      single.localId &&
                      goto(
                        `/album/${encodeURIComponent(data.name)}/${encodeURIComponent(single.title)}`,
                      )}
                  >
                    {single.title}
                  </button>
                  <div
                    class={`flex items-center gap-2 text-xs mt-0.5 ${single.localId ? "text-white/50" : "text-white/20 line-through"}`}
                  >
                    {#if single.localId}
                      {#if single.codec}
                        <span class="uppercase">{single.codec}</span>
                        <span class="text-white/30">•</span>
                      {/if}
                      {#if single.bit_depth && single.sample_rate_hz}
                        <span
                          >{single.bit_depth}bit / {single.sample_rate_hz /
                            1000}kHz</span
                        >
                        <span class="text-white/30">•</span>
                      {/if}
                    {/if}
                    <span
                      >{single.date
                        ? single.date.substring(0, 4)
                        : "Unknown"}</span
                    >
                  </div>
                </div>

                <div class="flex items-center gap-4">
                  {#if single.localId}
                    <button
                      class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-xs opacity-0 group-hover:opacity-100 transition-opacity"
                      title="Add to Queue"
                      on:click|stopPropagation={() => {
                        if (
                          single.tracksToPlay &&
                          single.tracksToPlay.length > 0
                        ) {
                          addToQueue(single.tracksToPlay);
                        }
                      }}
                    >
                      <svg
                        class="h-4 w-4"
                        fill="currentColor"
                        viewBox="0 0 24 24"
                        ><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg
                      >
                    </button>
                  {/if}
                </div>
              </div>
            {/each}
          {:else}
            <div class="p-4 text-white/60">No singles recorded.</div>
          {/if}
        </div>
      </div>
    </div>

    <div class="space-y-4 h-full flex flex-col">
      <div class="section-head">
        <div>
          <p class="text-sm uppercase tracking-wide text-white/60">Discovery</p>
          <h3 class="text-xl font-semibold">Similar artists</h3>
        </div>
      </div>
      <div class="glass-panel flex-1 min-h-0 overflow-hidden flex flex-col">
        <div class="overflow-y-auto max-h-[360px] divide-y divide-white/5">
          {#if artist?.similar_artists?.length}
            {#each displayedSimilarArtists as sim}
              <button
                class="flex w-full items-center gap-4 px-4 py-3 text-left hover:bg-white/5 transition-colors"
                on:click={() => goto(`/artist/${encodeURIComponent(sim.name)}`)}
              >
                {#if sim.art_sha1 || sim.art_id}
                  <img
                    src={sim.art_sha1
                      ? `/art/file/${sim.art_sha1}`
                      : `/art/${sim.art_id}`}
                    alt={sim.name}
                    class="h-12 w-12 rounded-full object-cover"
                  />
                {:else}
                  <div
                    class="h-12 w-12 rounded-full bg-white/10 text-center text-sm font-semibold leading-[3rem]"
                  >
                    {sim.name ? sim.name.charAt(0).toUpperCase() : "?"}
                  </div>
                {/if}
                <div class="truncate text-sm font-semibold">{sim.name}</div>
              </button>
            {/each}
          {:else}
            <div class="p-4 text-white/60">No similar artists recorded.</div>
          {/if}
        </div>
      </div>
    </div>
  </div>

  {#if mainAlbums.length > 0}
    <div class="section-head" id="albums">
      <div>
        <p class="text-sm uppercase tracking-wide text-white/60">Library</p>
        <h3 class="text-xl font-semibold">Albums</h3>
      </div>
    </div>
    <div
      class="grid gap-5 [grid-template-columns:repeat(auto-fill,minmax(200px,1fr))]"
    >
      {#each mainAlbums as album}
        <article class="grid-card flex flex-col gap-3">
          <button
            class="group relative aspect-square overflow-hidden rounded-2xl"
            on:click={() =>
              goto(
                `/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`,
              )}
          >
            <img
              src={album.art_sha1
                ? `/art/file/${album.art_sha1}`
                : album.art_id
                  ? `/art/${album.art_id}`
                  : "/assets/logo.png"}
              alt={album.album}
              class="h-full w-full object-cover transition-transform duration-200 group-hover:scale-[1.03]"
            />
            {#if album.is_hires}
              <img
                src="/assets/logo-hires.png"
                class="absolute bottom-2 right-2 h-8 w-8"
                alt="Hi-res"
              />
            {/if}
            <div
              class="absolute right-2 top-2 flex gap-2 opacity-0 transition-opacity group-hover:opacity-100"
            >
              <button
                class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-sm hover:scale-110 transition-transform"
                title="Play"
                on:click|stopPropagation={() => playAlbum(album)}
              >
                <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24"
                  ><path d="M8 5v14l11-7z" /></svg
                >
              </button>
              <button
                class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-sm hover:scale-110 transition-transform"
                title="Add to queue"
                on:click|stopPropagation={() => addAlbumToQueue(album)}
              >
                <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24"
                  ><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg
                >
              </button>
            </div>
          </button>
          <div class="space-y-1">
            <p class="text-base font-semibold line-clamp-1">{album.album}</p>
            <p class="text-xs text-white/60">
              {album.year ? album.year.substring(0, 4) : "—"} • {album.track_count ||
                0} tracks
            </p>
          </div>
        </article>
      {/each}
    </div>
  {/if}

  {#if appearsOnAlbums.length > 0}
    <div class="section-head mt-10">
      <div>
        <p class="text-sm uppercase tracking-wide text-white/60">Features</p>
        <h3 class="text-xl font-semibold">Appears On</h3>
      </div>
    </div>
    <div
      class="grid gap-5 [grid-template-columns:repeat(auto-fill,minmax(200px,1fr))]"
    >
      {#each appearsOnAlbums as album}
        <article class="grid-card flex flex-col gap-3">
          <button
            class="group relative aspect-square overflow-hidden rounded-2xl"
            on:click={() =>
              goto(
                `/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`,
              )}
          >
            <img
              src={album.art_sha1
                ? `/art/file/${album.art_sha1}`
                : album.art_id
                  ? `/art/${album.art_id}`
                  : "/assets/logo.png"}
              alt={album.album}
              class="h-full w-full object-cover transition-transform duration-200 group-hover:scale-[1.03]"
            />
            {#if album.is_hires}
              <img
                src="/assets/logo-hires.png"
                class="absolute bottom-2 right-2 h-8 w-8"
                alt="Hi-res"
              />
            {/if}
            <div
              class="absolute right-2 top-2 flex gap-2 opacity-0 transition-opacity group-hover:opacity-100"
            >
              <button
                class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-sm hover:scale-110 transition-transform"
                title="Play"
                on:click|stopPropagation={() => playAlbum(album)}
              >
                <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24"
                  ><path d="M8 5v14l11-7z" /></svg
                >
              </button>
              <button
                class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-sm hover:scale-110 transition-transform"
                title="Add to queue"
                on:click|stopPropagation={() => addAlbumToQueue(album)}
              >
                <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24"
                  ><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg
                >
              </button>
            </div>
          </button>
          <div class="space-y-1">
            <p class="text-base font-semibold line-clamp-1">{album.album}</p>
            <p class="text-xs text-white/60">
              {album.year ? album.year.substring(0, 4) : "—"} • {album.track_count ||
                0} tracks
            </p>
          </div>
        </article>
      {/each}
    </div>
  {/if}

  {#if missingAlbums.length > 0}
    <div class="section-head mt-10" id="missing-albums">
      <div>
        <p class="text-sm uppercase tracking-wide text-white/60">Discovery</p>
        <h3 class="text-xl font-semibold">Missing Albums</h3>
      </div>
    </div>
    <div
      class="grid gap-5 [grid-template-columns:repeat(auto-fill,minmax(200px,1fr))]"
    >
      {#each missingAlbums as album}
        <article
          class="grid-card flex flex-col gap-3 opacity-80 hover:opacity-100 transition-opacity"
        >
          <div
            class="group relative aspect-square overflow-hidden rounded-2xl bg-white/5"
          >
            {#if album.image_url}
              <img
                src={album.image_url}
                alt={album.title}
                class="h-full w-full object-cover"
              />
            {:else}
              <div class="h-full w-full flex items-center justify-center">
                <span class="text-4xl text-white/10">?</span>
              </div>
            {/if}

            <div
              class="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity gap-2"
            >
              {#if album.tidal_url}
                <a
                  href={album.tidal_url}
                  target="_blank"
                  class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-sm"
                  title="Open in Tidal"
                >
                  <img
                    src="/assets/logo-tidal.png"
                    alt="Tidal"
                    class="h-4 w-4"
                  />
                </a>
              {/if}
              {#if album.qobuz_url}
                <a
                  href={album.qobuz_url}
                  target="_blank"
                  class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-sm"
                  title="Open in Qobuz"
                >
                  <img
                    src="/assets/logo-qobuz.png"
                    alt="Qobuz"
                    class="h-4 w-4"
                  />
                </a>
              {/if}
              {#if album.musicbrainz_url}
                <a
                  href={album.musicbrainz_url}
                  target="_blank"
                  class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-sm"
                  title="Open in MusicBrainz"
                >
                  <img
                    src="/assets/logo-musicbrainz.svg"
                    alt="MB"
                    class="h-4 w-4"
                  />
                </a>
              {/if}
            </div>
          </div>
          <div class="space-y-1">
            <p class="text-base font-semibold line-clamp-1">{album.title}</p>
            <p class="text-xs text-white/60">
              {album.release_date ? album.release_date.substring(0, 4) : "—"} • Missing
            </p>
          </div>
        </article>
      {/each}
    </div>
  {/if}
</section>
