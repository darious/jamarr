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
  import ColorThief from "colorthief";

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
  let accentColor: [number, number, number] | null = null;
  let headerRef: HTMLDivElement;

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

  // Extract accent color
  $: if (browser && artist) {
    const bgUrl = artist.background_sha1
      ? `/art/file/${artist.background_sha1}`
      : artist.background_art_id
        ? `/art/${artist.background_art_id}`
        : artist.art_sha1
          ? `/art/file/${artist.art_sha1}`
          : artist.art_id
            ? `/art/${artist.art_id}`
            : null;

    if (bgUrl) {
      const img = new Image();
      img.crossOrigin = "Anonymous";
      img.src = bgUrl;
      img.onload = () => {
        try {
          const thief = new ColorThief();
          accentColor = thief.getColor(img);
        } catch (e) {
          console.warn("Color extraction failed", e);
          accentColor = null;
        }
      };
    } else {
      accentColor = null;
    }
  }

  const formatPlays = (plays?: number) => {
    if (!plays) return "";
    if (plays >= 1000000) return `${(plays / 1000000).toFixed(1)}M plays`;
    if (plays >= 1000) return `${(plays / 1000).toFixed(1)}K plays`;
    return `${plays} plays`;
  };

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
      let result: Track;
      if (t.local_track_id) {
        // Track is in library - find full track object
        const local = tracks.find((lt) => lt.id === t.local_track_id);
        if (local) {
          result = { ...local };
        } else {
          // Fallback if track not loaded yet - use API data
          result = {
            id: t.local_track_id,
            path: "",
            title: t.name,
            artist: artist?.name || "",
            album: t.album || "",
            album_artist: artist?.name || "",
            track_no: null,
            disc_no: null,
            date: t.date,
            duration_seconds:
              t.duration_seconds ||
              (t.duration_ms ? Math.round(t.duration_ms / 1000) : 0),
            art_id: null,
            codec: t.codec || null,
            bitrate: null,
            sample_rate_hz: t.sample_rate_hz || null,
            bit_depth: t.bit_depth || null,
          };
        }
      } else {
        // Track not in library - return placeholder
        result = {
          id: -1,
          path: "",
          title: t.name,
          artist: artist?.name || "",
          album: t.album || "",
          album_artist: artist?.name || "",
          track_no: null,
          disc_no: null,
          date: t.date,
          duration_seconds: t.duration_ms
            ? Math.round(t.duration_ms / 1000)
            : 0,
          art_id: null,
          codec: null,
          bitrate: null,
          sample_rate_hz: null,
          bit_depth: null,
        };
      }
      if (t.popularity) result.popularity = t.popularity;
      return result;
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
        return dateA.localeCompare(dateB); // Oldest first
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

  $: mainAlbums = data.albums
    .filter((a) => !a.type || a.type === "main")
    .sort((a, b) => (b.year || "").localeCompare(a.year || "")); // Newest first

  $: appearsOnAlbums = data.albums.filter((a) => a.type === "appears_on");

  async function refreshMeta() {
    refreshing = true;
    message = "Requesting fresh metadata...";
    try {
      if (artist?.mbid) {
        await triggerMetadataScan({
          mbidFilter: artist.mbid,
          missingOnly: false,
          fetchBio: true,
          fetchLinks: true,
          fetchArtwork: true,
          fetchMetadata: true,
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

  async function playAllTopTracks() {
    const playableTracks: Track[] = displayedTopTracks
      .map((t) => {
        if (!t.id || t.id <= 0) return null;
        return tracks.find((lt) => lt.id === t.id) || t;
      })
      .filter((t): t is Track => Boolean(t));
    if (playableTracks.length > 0) {
      await setQueue(playableTracks, 0);
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
    (e.currentTarget as HTMLImageElement).src =
      "/assets/default-artist-placeholder.svg";
  }
</script>

<div
  class="min-h-screen bg-surface-900 pb-20 relative overflow-hidden"
  style={accentColor ? `--accent-color: ${accentColor.join(",")}` : ""}
>
  <!-- Global Blurred Background -->
  <div class="fixed inset-0 z-0 pointer-events-none">
    <div
      class="absolute inset-0 bg-cover bg-center blur-[100px] opacity-30 scale-110 saturate-[1.5]"
      style={`background-image:url('${
        artist?.background_sha1
          ? `/art/file/${artist.background_sha1}`
          : artist?.background_art_id
            ? `/art/${artist.background_art_id}`
            : artist?.art_sha1
              ? `/art/file/${artist.art_sha1}`
              : artist?.art_id
                ? `/art/${artist.art_id}`
                : "/assets/default-artist-placeholder.svg"
      }')`}
    ></div>
    <div class="absolute inset-0 bg-surface-900/80"></div>
  </div>

  <!-- Hero Banner -->
  <div
    class="relative w-full h-[40vh] min-h-[350px] overflow-hidden group z-10"
  >
    <!-- Background Image Layers -->

    <!-- Background Image Layers -->

    <!-- Mask Wrapper (Static - Keeps the fade fixed) -->
    <div
      class="absolute inset-0"
      style="mask-image: linear-gradient(to bottom, black 50%, transparent 100%); -webkit-mask-image: linear-gradient(to bottom, black 50%, transparent 100%);"
    >
      <!-- Sharp Top Layer (Fades into Global Background) -->
      <div
        class="absolute inset-0 bg-cover bg-top transition-transform duration-1000 scale-105 group-hover:scale-100"
        style={`background-image:url('${
          artist?.background_sha1
            ? `/art/file/${artist.background_sha1}`
            : artist?.background_art_id
              ? `/art/${artist.background_art_id}`
              : artist?.art_sha1
                ? `/art/file/${artist.art_sha1}`
                : artist?.art_id
                  ? `/art/${artist.art_id}`
                  : "/assets/default-artist-placeholder.svg"
        }');`}
      >
        <!-- Gradient Fade to Bottom (Start of merge) - Inside scaling div to match atmosphere -->
        <div
          class="absolute inset-0 bg-gradient-to-b from-black/20 via-transparent to-surface-900/40"
        ></div>
      </div>
    </div>

    <!-- Bottom Gradient to Body Color (Seamless merge) -->
    <div
      class="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-surface-900 via-surface-900/60 to-transparent"
    ></div>

    <!-- Hero Content -->
    <div class="absolute inset-0 flex items-end p-8 md:p-12 pb-16">
      <div
        class="w-full max-w-[1800px] mx-auto grid md:grid-cols-[1fr,auto] gap-8 items-end"
      >
        <div class="space-y-4 w-full">
          <h1
            class="text-5xl md:text-7xl lg:text-8xl font-bold tracking-tight text-white drop-shadow-xl"
          >
            {artist?.name ?? data.name}
          </h1>
          <div
            class="glass-surface p-4 rounded-xl border border-white/5 bg-black/20 backdrop-blur-md max-w-4xl max-h-[120px] overflow-y-auto custom-scrollbar"
          >
            <p
              class="text-base text-white/90 leading-relaxed whitespace-pre-wrap"
            >
              {artist?.bio || "No biography available yet."}
            </p>
          </div>
        </div>

        <!-- Links (Right Side) -->
        <div class="flex flex-col items-end gap-3">
          <div class="flex flex-wrap justify-end gap-2">
            {#if artist?.homepage}
              <a
                class="btn-icon btn-icon-sm variant-filled-surface hover:border-[#3b82f6] hover:bg-[#3b82f6] hover:text-white transition-all border border-transparent"
                target="_blank"
                href={artist.homepage}
                title="Homepage"
              >
                <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24"
                  ><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z" /></svg
                >
              </a>
            {/if}
            {#if artist?.musicbrainz_url}
              <a
                class="btn-icon btn-icon-sm variant-filled-surface hover:border-[#BA478F] hover:bg-[#BA478F] hover:text-white transition-all border border-transparent"
                target="_blank"
                href={artist.musicbrainz_url}
                title="MusicBrainz"
              >
                <img
                  src="/assets/logo-musicbrainz.svg"
                  alt="MB"
                  class="h-5 w-5"
                />
              </a>
            {/if}
            {#if artist?.tidal_url}
              <a
                class="btn-icon btn-icon-sm variant-filled-surface hover:border-black hover:bg-black hover:text-white transition-all border border-transparent"
                target="_blank"
                href={artist.tidal_url}
                title="Tidal"
              >
                <img src="/assets/logo-tidal.png" alt="Tidal" class="h-5 w-5" />
              </a>
            {/if}
            {#if artist?.lastfm_url}
              <a
                class="btn-icon btn-icon-sm variant-filled-surface hover:border-[#D51007] hover:bg-[#D51007] hover:text-white transition-all border border-transparent"
                target="_blank"
                href={artist.lastfm_url}
                title="Last.fm"
              >
                <img
                  src="/assets/logo-lastfm.png"
                  alt="Last.fm"
                  class="h-5 w-5"
                />
              </a>
            {/if}
            {#if artist?.qobuz_url}
              <a
                class="btn-icon btn-icon-sm variant-filled-surface hover:border-black hover:bg-black hover:text-white transition-all border border-transparent"
                target="_blank"
                href={artist.qobuz_url}
                title="Qobuz"
              >
                <img src="/assets/logo-qobuz.png" alt="Qobuz" class="h-5 w-5" />
              </a>
            {/if}
            {#if artist?.spotify_url}
              <a
                class="btn-icon btn-icon-sm variant-filled-surface hover:border-[#1DB954] hover:bg-[#1DB954] hover:text-white transition-all border border-transparent"
                target="_blank"
                href={artist.spotify_url}
                title="Spotify"
              >
                <img
                  src="/assets/logo-spotify.svg"
                  alt="Spotify"
                  class="h-5 w-5"
                />
              </a>
            {/if}
          </div>

          <div
            class="flex gap-2 text-sm text-white/70 font-medium bg-black/30 backdrop-blur-md px-4 py-2 rounded-full border border-white/5"
          >
            <span>{data.albums.length} Albums</span>
            <span class="opacity-50">•</span>
            <span>{tracks.length} Tracks</span>
          </div>

          <div class="flex gap-2">
            <button
              class="btn btn-sm variant-ghost-surface backdrop-blur-md"
              on:click={refreshMeta}
              disabled={refreshing}
            >
              {refreshing ? "Refreshing..." : "Refresh Metadata"}
            </button>
            <button
              class="btn btn-sm variant-ghost-surface backdrop-blur-md"
              on:click={scanMissing}
              disabled={scanningMissing}
            >
              {scanningMissing ? "Scanning..." : "Check Missing"}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <main
    class="relative z-10 max-w-[1800px] mx-auto px-6 md:px-12 mt-8 space-y-16"
  >
    <!-- Albums Section -->
    <section>
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-3xl font-bold text-white drop-shadow-md">Albums</h2>
      </div>

      <div
        class="grid gap-8 grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
      >
        {#each mainAlbums as album}
          <article class="group flex flex-col gap-4">
            <button
              class="relative aspect-square overflow-hidden rounded-lg shadow-2xl bg-surface-800 transition-transform duration-300 hover:scale-[1.02]"
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
                    : "/assets/default-album-placeholder.svg"}
                alt={album.album}
                class="h-full w-full object-cover"
                loading="lazy"
              />
              <!-- Play Overlay -->
              <div
                class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-3"
              >
                <button
                  class="btn-icon btn-icon-lg bg-black/60 hover:bg-black/80 text-white backdrop-blur-md border border-white/10 shadow-xl"
                  title="Play"
                  on:click|stopPropagation={() => playAlbum(album)}
                >
                  <svg
                    class="h-8 w-8 ml-1"
                    fill="currentColor"
                    viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg
                  >
                </button>
                <button
                  class="btn-icon btn-icon-md bg-black/60 hover:bg-black/80 text-white backdrop-blur-md border border-white/10 shadow-xl"
                  title="Add to Queue"
                  on:click|stopPropagation={() => addAlbumToQueue(album)}
                >
                  <svg class="h-6 w-6" fill="currentColor" viewBox="0 0 24 24"
                    ><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg
                  >
                </button>
              </div>

              <!-- Hi-Res Badge -->
              {#if album.is_hires}
                <img
                  src="/assets/logo-hires.png"
                  class="absolute bottom-3 right-3 h-6 w-auto drop-shadow-lg"
                  alt="Hi-Res"
                />
              {/if}
            </button>
            <div class="space-y-1">
              <h3
                class="text-base font-bold text-white leading-tight line-clamp-2 group-hover:text-primary-400 transition-colors"
                title={album.album}
              >
                {album.album}
              </h3>
              <p class="text-sm text-white/50 font-medium">
                {album.year ? album.year.substring(0, 4) : "Unknown"}
                <span class="mx-1 opacity-50">•</span>
                {album.track_count} tracks
              </p>
            </div>
          </article>
        {/each}
      </div>
    </section>

    <!-- Bottom Grids -->
    <div class="grid lg:grid-cols-2 xl:grid-cols-3 gap-8 items-start">
      <!-- Top Tracks -->
      <section
        class="glass-surface p-6 rounded-2xl border border-white/5 bg-surface-900/40 backdrop-blur-xl"
      >
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-xl font-bold">Top Tracks</h3>
          <button
            class="btn btn-sm variant-ghost-surface"
            on:click={playAllTopTracks}>Play All</button
          >
        </div>
        <div
          class="space-y-1 max-h-[320px] overflow-y-auto pr-2 custom-scrollbar"
        >
          {#each displayedTopTracks as track, i}
            <div
              class="w-full flex items-center gap-3 p-2 rounded-lg hover:bg-white/5 group transition-colors text-left"
            >
              <span
                class="w-6 text-center text-xs text-white/40 font-mono flex-shrink-0"
                >{i + 1}</span
              >
              <div class="relative w-10 h-10 flex-shrink-0">
                <img
                  src={(() => {
                    const alb = data.albums.find(
                      (a) => a.album === track.album,
                    );
                    if (alb?.art_sha1) return `/art/file/${alb.art_sha1}`;
                    if (alb?.art_id) return `/art/${alb.art_id}`;
                    return "/assets/default-artist-placeholder.svg";
                  })()}
                  class="w-full h-full rounded object-cover bg-surface-700"
                  alt="Art"
                />
                <button
                  class="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity"
                  on:click={() => track.id > 0 && playTrackById(track.id)}
                >
                  <svg
                    class="w-5 h-5 text-white"
                    fill="currentColor"
                    viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg
                  >
                </button>
              </div>

              <div class="flex-1 min-w-0">
                <p
                  class={`text-sm font-medium truncate ${track.id > 0 ? "text-white" : "text-white/40 line-through"}`}
                >
                  {track.title}
                </p>
                <div class="flex items-center gap-2 text-xs text-white/40">
                  <a
                    href={`/album/${encodeURIComponent(artist?.name || "")}/${encodeURIComponent(track.album)}`}
                    class="hover:text-white hover:underline truncate max-w-[150px]"
                    >{track.album}</a
                  >
                  {#if track.popularity}
                    <span class="opacity-30">•</span>
                    <span>{formatPlays(track.popularity)}</span>
                  {/if}
                  {#if track.codec}
                    <span class="opacity-30">•</span>
                    <span class="uppercase">{track.codec}</span>
                  {/if}
                  {#if track.bit_depth && track.sample_rate_hz}
                    <span class="opacity-30">•</span>
                    <span>{track.bit_depth}/{track.sample_rate_hz / 1000}</span>
                  {/if}
                </div>
              </div>

              {#if track.id > 0}
                <button
                  class="btn-icon btn-icon-sm opacity-0 group-hover:opacity-100 transition-opacity"
                  title="Add to Queue"
                  on:click={() => addTrackToQueue(track.id)}
                >
                  <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"
                    ><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg
                  >
                </button>
              {/if}
              <span
                class="text-xs text-white/30 font-mono w-10 text-right flex-shrink-0"
                >{formatDuration(track.duration_seconds)}</span
              >
            </div>
          {/each}
        </div>
      </section>

      <!-- Singles -->
      <section
        class="glass-surface p-6 rounded-2xl border border-white/5 bg-surface-900/40 backdrop-blur-xl"
      >
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-xl font-bold">Singles</h3>
          <button
            class="btn btn-sm variant-ghost-surface"
            on:click={playAllSingles}>Play All</button
          >
        </div>
        <div
          class="space-y-1 max-h-[320px] overflow-y-auto pr-2 custom-scrollbar"
        >
          {#if displayedSingles.length === 0}
            <p class="text-white/40 text-sm p-4 text-center">
              No singles found.
            </p>
          {:else}
            {#each displayedSingles as single}
              <div
                class="w-full flex items-center gap-3 p-2 rounded-lg hover:bg-white/5 group transition-colors text-left"
              >
                <div class="relative w-10 h-10 flex-shrink-0">
                  <img
                    src={single.art_sha1
                      ? `/art/file/${single.art_sha1}`
                      : single.art_id
                        ? `/art/${single.art_id}`
                        : "/assets/default-artist-placeholder.svg"}
                    class="w-full h-full rounded object-cover bg-surface-700"
                    alt="Art"
                  />
                  {#if single.localId}
                    <button
                      class="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity"
                      on:click={() => {
                        if (
                          single.tracksToPlay &&
                          single.tracksToPlay.length > 0
                        )
                          setQueue(single.tracksToPlay, 0);
                      }}
                    >
                      <svg
                        class="w-5 h-5 text-white"
                        fill="currentColor"
                        viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg
                      >
                    </button>
                  {/if}
                </div>

                <div class="flex-1 min-w-0">
                  <p
                    class={`text-sm font-medium truncate ${single.localId ? "text-white" : "text-white/40 line-through"}`}
                  >
                    {single.title}
                  </p>
                  <div class="flex items-center gap-2 text-xs text-white/40">
                    <span>{single.date?.substring(0, 4) || "Unknown"}</span>
                    {#if single.codec}
                      <span class="opacity-30">•</span>
                      <span class="uppercase">{single.codec}</span>
                    {/if}
                    {#if single.bit_depth && single.sample_rate_hz}
                      <span class="opacity-30">•</span>
                      <span
                        >{single.bit_depth}/{single.sample_rate_hz / 1000}</span
                      >
                    {/if}
                  </div>
                </div>

                {#if single.localId && single.tracksToPlay && single.tracksToPlay.length > 0}
                  <button
                    class="btn-icon btn-icon-sm opacity-0 group-hover:opacity-100 transition-opacity"
                    title="Add to Queue"
                    on:click={() => addToQueue(single.tracksToPlay)}
                  >
                    <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"
                      ><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg
                    >
                  </button>
                {/if}
              </div>
            {/each}
          {/if}
        </div>
      </section>

      <!-- Similar Artists -->
      <section
        class="glass-surface p-6 rounded-2xl border border-white/5 bg-surface-900/40 backdrop-blur-xl"
      >
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-xl font-bold">Similar Artists</h3>
        </div>
        <div
          class="space-y-1 max-h-[320px] overflow-y-auto pr-2 custom-scrollbar"
        >
          {#if displayedSimilarArtists.length === 0}
            <p class="text-white/40 text-sm p-4 text-center">
              No similar artists found.
            </p>
          {:else}
            {#each displayedSimilarArtists as sim}
              <button
                class="w-full flex items-center gap-3 p-2 rounded-lg hover:bg-white/5 group transition-colors text-left"
                on:click={() => goto(`/artist/${encodeURIComponent(sim.name)}`)}
              >
                {#if sim.art_sha1 || sim.art_id}
                  <img
                    src={sim.art_sha1
                      ? `/art/file/${sim.art_sha1}`
                      : `/art/${sim.art_id}`}
                    class="w-10 h-10 rounded-full object-cover bg-surface-700"
                    alt={sim.name}
                  />
                {:else}
                  <div
                    class="w-10 h-10 rounded-full bg-surface-700 flex items-center justify-center text-xs font-bold text-white/50"
                  >
                    ?
                  </div>
                {/if}
                <span
                  class="text-sm font-medium text-white group-hover:text-primary-400 transition-colors"
                  >{sim.name}</span
                >
              </button>
            {/each}
          {/if}
        </div>
      </section>
    </div>

    {#if missingAlbums.length > 0}
      <section class="pb-10">
        <div class="flex items-center justify-between mb-6">
          <h2 class="text-2xl font-bold text-white/80">Missing Albums</h2>
        </div>
        <div
          class="glass-surface rounded-2xl overflow-hidden border border-white/5 bg-surface-900/40 backdrop-blur-xl"
        >
          <table class="w-full text-left text-sm whitespace-nowrap">
            <thead
              class="uppercase tracking-wider border-b border-white/10 text-white/40 text-xs bg-white/5"
            >
              <tr>
                <th class="px-6 py-4">Album</th>
                <th class="px-6 py-4">Released</th>
                <th class="px-6 py-4 text-center">Links</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/5">
              {#each missingAlbums as album}
                <tr class="hover:bg-white/5 transition-colors">
                  <td class="px-6 py-4 font-medium text-white/90"
                    >{album.title}</td
                  >
                  <td class="px-6 py-4 text-white/50"
                    >{album.release_date || "—"}</td
                  >
                  <td class="px-6 py-4">
                    <div class="flex items-center justify-center gap-3">
                      {#if album.musicbrainz_url}
                        <a
                          href={album.musicbrainz_url}
                          target="_blank"
                          class="opacity-50 hover:opacity-100 transition-opacity hover:scale-110 transform"
                          ><img
                            src="/assets/logo-musicbrainz.svg"
                            class="w-5 h-5"
                            alt="MB"
                          /></a
                        >
                      {/if}
                      {#if album.tidal_url}
                        <a
                          href={album.tidal_url}
                          target="_blank"
                          class="opacity-50 hover:opacity-100 transition-opacity hover:scale-110 transform"
                          ><img
                            src="/assets/logo-tidal.png"
                            class="w-5 h-5"
                            alt="Tidal"
                          /></a
                        >
                      {/if}
                      {#if album.qobuz_url}
                        <a
                          href={album.qobuz_url}
                          target="_blank"
                          class="opacity-50 hover:opacity-100 transition-opacity hover:scale-110 transform"
                          ><img
                            src="/assets/logo-qobuz.png"
                            class="w-5 h-5"
                            alt="Qobuz"
                          /></a
                        >
                      {/if}
                    </div>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </section>
    {/if}
  </main>
</div>

<style>
  .custom-scrollbar::-webkit-scrollbar {
    width: 6px;
  }
  .custom-scrollbar::-webkit-scrollbar-track {
    background: transparent;
  }
  .custom-scrollbar::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.1);
    border-radius: 10px;
  }
  .custom-scrollbar::-webkit-scrollbar-thumb:hover {
    background: rgba(255, 255, 255, 0.2);
  }
</style>
