<script lang="ts">
  import type { Album, Artist, Track, MissingAlbum } from "$lib/api";
  import {
    fetchTracks,
    fetchMissingAlbums,
    triggerMissingAlbumsScan,
    triggerMetadataScan,
  } from "$lib/api";
  import { goto, invalidateAll } from "$app/navigation";
  import { addToQueue, loadQueueFromServer, setQueue } from "$stores/player";
  import { browser } from "$app/environment";
  import ColorThief from "colorthief";
  import Tabs from "$lib/components/Tabs.svelte";
  import AddToPlaylistModal from "$components/AddToPlaylistModal.svelte";

  let showPlaylistModal = false;
  let selectedTrackIds: number[] = [];

  function openPlaylistModal(ids: number | number[]) {
    selectedTrackIds = Array.isArray(ids) ? ids : [ids];
    showPlaylistModal = true;
  }

  export let data: {
    name: string;
    canonicalName: string;
    artist?: Artist;
    albums: Album[];
    similarArtists: {
      name: string;
      art_id?: number | null;
      art_sha1?: string | null;
      in_library?: boolean;
      external_url?: string | null;
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
    const hasAlbums = data.albums.length > 0;
    activeTab = "album"; // Reset logic will handle correct tab
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

  const getInitials = (name: string) => {
    return name
      .split(" ")
      .map((n) => n[0])
      .slice(0, 2)
      .join("")
      .toUpperCase();
  };

  $: displayedTopTracks = (() => {
    const fromMeta = artist?.top_tracks || [];
    return fromMeta.map((t) => {
      let result: Track;
      if (t.local_track_id) {
        // Track is in library - find full track object and MERGE with top track data
        const local = tracks.find((lt) => lt.id === t.local_track_id);
        if (local) {
          // Merge local track data with top track metadata
          // Local track provides: path, codec, bitrate, sample_rate, bit_depth, art_id, art_sha1
          // Top track provides: name, album, date, duration_ms, popularity
          result = {
            ...local,
            // Preserve top track metadata that might be different/better
            title: t.name || local.title,
            album: t.album || local.album,
            date: t.date || local.date,
            duration_seconds: t.duration_seconds || local.duration_seconds,
            popularity: t.popularity,
            // CRITICAL: Preserve artwork from EITHER source (top track API or local track)
            art_id: t.art_id || local.art_id,
            art_sha1: t.art_sha1 || local.art_sha1,
          };
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
            art_id: t.art_id || null,
            art_sha1: t.art_sha1 || null,
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
    return data.similarArtists || [];
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

            // Get artwork - prioritize from Singles API data, then from local track, then from album
            art_id = s.art_id || localTrack.art_id;
            art_sha1 = s.art_sha1 || localTrack.art_sha1;

            // Fallback to album artwork if still not found
            if (!art_id && !art_sha1) {
              const album = data.albums.find(
                (a) => a.album === localTrack.album,
              );
              if (album) {
                art_id = album.art_id;
                art_sha1 = album.art_sha1;
              }
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

  // Group Albums by Type
  $: groupedAlbums = (() => {
    const groups: Record<string, Album[]> = {
      album: [],
      ep: [],
      single: [],
      compilation: [],
      live: [],
      appears_on: [],
    };

    data.albums.forEach((album) => {
      // Priority 1: Appears On
      if (album.type === "appears_on") {
        groups.appears_on.push(album);
        return;
      }

      // Priority 2: Release Type (default to 'album')
      const type = (album.release_type || "album").toLowerCase();
      if (groups[type]) {
        groups[type].push(album);
      } else {
        // Fallback for unknown types (e.g. remix, demo) -> 'album'
        groups.album.push(album);
      }
    });

    // Sort each group: Newest first
    Object.values(groups).forEach((list) => {
      list.sort((a, b) => (b.year || "").localeCompare(a.year || ""));
    });

    return groups;
  })();

  // Displayed Albums based on active tab
  $: displayedAlbums = (() => {
    return groupedAlbums[activeTab as keyof typeof groupedAlbums] || [];
  })();

  async function refreshMeta() {
    refreshing = true;
    message = "Requesting artist refresh...";
    try {
      await triggerMetadataScan({
        artistFilter: data.canonicalName || data.name,
        mbidFilter: artist?.mbid,
        missingOnly: false,
        fetchMetadata: true,
        fetchBio: true,
        fetchArtwork: true,
        fetchSpotifyArtwork: true,
        refreshTopTracks: true,
        refreshSingles: true,
        fetchSimilarArtists: true,
      });
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

  async function queueAllTopTracks() {
    const playableTracks: Track[] = displayedTopTracks
      .map((t) => {
        if (!t.id || t.id <= 0) return null;
        return tracks.find((lt) => lt.id === t.id) || t;
      })
      .filter((t): t is Track => Boolean(t));
    if (playableTracks.length > 0) {
      await addToQueue(playableTracks);
    }
  }

  async function openPlaylistModalForTopTracks() {
    const ids = displayedTopTracks
      .map((t) => t.id)
      .filter((id) => id && id > 0) as number[];
    if (ids.length) openPlaylistModal(ids);
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

  async function queueAllSingles() {
    const allSingleTracks: Track[] = [];
    for (const single of displayedSingles) {
      if (single.tracksToPlay && single.tracksToPlay.length > 0) {
        allSingleTracks.push(...single.tracksToPlay);
      }
    }
    if (allSingleTracks.length > 0) {
      await addToQueue(allSingleTracks);
    }
  }

  async function openPlaylistModalForSingles() {
    const ids: number[] = [];
    for (const single of displayedSingles) {
      if (single.tracksToPlay) {
        ids.push(...single.tracksToPlay.map((t) => t.id));
      }
    }
    if (ids.length) openPlaylistModal(ids);
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

  // Local state for tabs
  let activeTab = "album"; // Default, will update via reactive statement
  let isBioExpanded = false;

  // Reactive tab items
  // Release Tabs (Left Side)
  $: releaseTabs = [
    {
      label: "Albums",
      value: "album",
      count: groupedAlbums.album.length,
    },
    {
      label: "EPs",
      value: "ep",
      count: groupedAlbums.ep.length,
    },
    {
      label: "Singles",
      value: "single",
      count: groupedAlbums.single.length, // Release-type singles
    },
    {
      label: "Compilations",
      value: "compilation",
      count: groupedAlbums.compilation.length,
    },
    {
      label: "Live",
      value: "live",
      count: groupedAlbums.live.length,
    },
    {
      label: "Appears On",
      value: "appears_on",
      count: groupedAlbums.appears_on.length,
    },
  ]
    .filter((t) => t.count > 0)
    .map((t) => ({ ...t, label: `${t.label} (${t.count})` }));

  // Track Tabs (Right Side)
  $: trackTabs = [
    {
      label: "Top Tracks",
      value: "top_tracks",
      count: displayedTopTracks.length,
    },
    {
      label: "Singles",
      value: "singles_list", // Distinction from release-type singles
      count: displayedSingles.length,
    },
  ]
    .filter((t) => t.count > 0)
    .map((t) => ({ ...t, label: `${t.label} (${t.count})` }));

  $: allTabs = [...releaseTabs, ...trackTabs];

  // Ensure activeTab is valid
  $: if (allTabs.length > 0 && !allTabs.find((t) => t.value === activeTab)) {
    // Default to first available release tab, or first track tab
    if (releaseTabs.length > 0) activeTab = releaseTabs[0].value;
    else if (trackTabs.length > 0) activeTab = trackTabs[0].value;
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
    class="relative w-full h-[60vh] min-h-[500px] overflow-hidden group z-10"
  >
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
      class="absolute inset-x-0 bottom-0 h-48 bg-gradient-to-t from-surface-900 via-surface-900/60 to-transparent"
    ></div>

    <!-- Hero Content -->
    <div class="absolute inset-0 flex items-end px-6 md:px-12 xl:px-16 pb-12">
      <div class="w-full space-y-2">
        <h1
          class="text-6xl md:text-8xl lg:text-9xl font-bold tracking-tight text-white drop-shadow-2xl"
        >
          {artist?.name ?? data.name}
        </h1>
        {#if artist?.genres?.length}
          <div class="flex flex-wrap gap-2 text-white/60 font-medium text-lg">
            {artist.genres.map((g) => g.name).join(" · ")}
          </div>
        {/if}
      </div>
    </div>
  </div>

  <main
    class="relative z-10 w-full px-6 md:px-12 xl:px-16 mt-8 grid grid-cols-1 lg:grid-cols-[1fr_clamp(280px,22vw,360px)] gap-12 lg:gap-16 pb-20"
  >
    <!-- Left Column: Main Content -->
    <div class="space-y-16 min-w-0">
      <!-- Bio Section -->
      {#if artist?.bio}
        <section>
          <div class="relative group">
            <p
              class={`text-lg md:text-xl leading-relaxed text-white/90 font-medium max-w-4xl transition-all duration-500 ${
                isBioExpanded ? "" : "line-clamp-3"
              }`}
            >
              {artist.bio}
            </p>
            {#if artist.bio.length > 300}
              <button
                on:click={() => (isBioExpanded = !isBioExpanded)}
                class="mt-3 text-sm font-bold text-white/50 uppercase tracking-widest hover:text-white transition-colors"
              >
                {isBioExpanded ? "Read less" : "Read more"}
              </button>
            {/if}
          </div>
        </section>
      {/if}

      <!-- Similar Artists -->
      {#if displayedSimilarArtists.length > 0}
        <section>
          <h3
            class="text-xs font-bold text-white/40 uppercase tracking-widest mb-6"
          >
            Similar Artists
          </h3>
          <div class="flex flex-wrap gap-4">
            {#each displayedSimilarArtists.slice(0, 10) as sim}
              <button
                class="group w-24 text-center space-y-2"
                on:click|stopPropagation={() => {
                  if (sim.in_library) {
                    goto(`/artist/${encodeURIComponent(sim.name)}`);
                  } else if (sim.external_url) {
                    window.open(sim.external_url, "_blank");
                  }
                }}
              >
                <div
                  class="relative aspect-square rounded-full overflow-hidden bg-surface-800 ring-1 ring-white/10 group-hover:ring-primary-500 transition-all shadow-lg"
                >
                  {#if sim.art_sha1 || sim.art_id}
                    <img
                      src={sim.art_sha1
                        ? `/art/file/${sim.art_sha1}`
                        : `/art/${sim.art_id}`}
                      class="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity"
                      alt={sim.name}
                    />
                  {:else}
                    <div
                      class="w-full h-full flex items-center justify-center text-xs font-bold text-white/40 bg-surface-700"
                    >
                      {getInitials(sim.name)}
                    </div>
                  {/if}
                </div>
                <p
                  class="text-xs font-medium text-white/70 group-hover:text-white truncate"
                >
                  {sim.name}
                </p>
              </button>
            {/each}
          </div>
        </section>
      {/if}

      {#if allTabs.length > 0}
        <!-- Tabs Header -->
        <div
          class="flex flex-wrap items-center gap-8 border-b border-white/5 pb-0 mb-8"
        >
          <!-- Left Group: Releases -->
          <div
            class="flex gap-1 p-1 bg-white/5 rounded-lg border border-white/5"
          >
            {#each releaseTabs as tab}
              <button
                class={`px-4 py-1.5 rounded-md text-sm font-medium transition-all duration-200 ${
                  activeTab === tab.value
                    ? "bg-white/10 text-white shadow-lg"
                    : "text-white/50 hover:text-white/80 hover:bg-white/5"
                }`}
                on:click={() => (activeTab = tab.value)}
              >
                {tab.label}
              </button>
            {/each}
          </div>

          <!-- Spacer -->
          <div class="flex-1"></div>

          <!-- Right Group: Tracks -->
          <div
            class="flex gap-1 p-1 bg-white/5 rounded-lg border border-white/5"
          >
            {#each trackTabs as tab}
              <button
                class={`px-4 py-1.5 rounded-md text-sm font-medium transition-all duration-200 ${
                  activeTab === tab.value
                    ? "bg-white/10 text-white shadow-lg"
                    : "text-white/50 hover:text-white/80 hover:bg-white/5"
                }`}
                on:click={() => (activeTab = tab.value)}
              >
                {tab.label}
              </button>
            {/each}
          </div>
        </div>

        <!-- Albums Grid -->
        {#if ["album", "ep", "single", "compilation", "live", "appears_on"].includes(activeTab)}
          {#if displayedAlbums.length > 0}
            <div
              class="grid gap-8 grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
            >
              {#each displayedAlbums as album (album.album + album.artist_name)}
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
                        <svg
                          class="h-6 w-6"
                          fill="currentColor"
                          viewBox="0 0 24 24"
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
                      {#if activeTab === "appears_on"}
                        {album.artist_name}
                        <span class="mx-1 opacity-50">•</span>
                      {/if}
                      {album.year ? album.year.substring(0, 4) : "Unknown"}
                      <span class="mx-1 opacity-50">•</span>
                      {album.track_count} tracks
                    </p>
                  </div>
                </article>
              {/each}
            </div>
          {/if}
        {:else if activeTab === "top_tracks"}
          <!-- Top Tracks List View -->
          <div class="flex items-center gap-4 mb-4">
            <button
              class="btn btn-sm variant-filled-primary"
              on:click={playAllTopTracks}
            >
              <svg class="w-4 h-4 mr-2" fill="currentColor" viewBox="0 0 24 24"
                ><path d="M8 5v14l11-7z" /></svg
              >
              Play All
            </button>
            <button
              class="btn btn-sm variant-ghost-surface"
              on:click={queueAllTopTracks}
            >
              Add All to Queue
            </button>
            <button
              class="btn btn-sm variant-ghost-surface"
              on:click={openPlaylistModalForTopTracks}
            >
              Add to Playlist
            </button>
          </div>

          <div class="space-y-0.5 max-w-5xl mx-auto">
            {#each displayedTopTracks as track, i}
              <div
                class="w-full grid grid-cols-[auto,auto,1fr,auto] items-center gap-4 px-3 py-2 rounded-xl hover:bg-white/5 group transition-colors text-left border border-transparent hover:border-white/5 relative"
              >
                <span class="w-8 text-center text-sm text-white/40 font-mono"
                  >{i + 1}</span
                >

                <!-- Artwork -->
                <div
                  class="relative w-14 h-14 rounded overflow-hidden bg-surface-800 shadow-lg"
                >
                  <img
                    src={(() => {
                      if (track.art_sha1) return `/art/file/${track.art_sha1}`;
                      if (track.art_id) return `/art/${track.art_id}`;
                      const alb = data.albums.find(
                        (a) => a.album === track.album,
                      );
                      if (alb?.art_sha1) return `/art/file/${alb.art_sha1}`;
                      if (alb?.art_id) return `/art/${alb.art_id}`;
                      return "/assets/default-artist-placeholder.svg";
                    })()}
                    class="w-full h-full object-cover"
                    alt="Art"
                  />
                  <!-- Hover Play Overlay -->
                  <div
                    class="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity"
                  >
                    <button
                      class="text-white hover:scale-110 transition-transform"
                      on:click={() => track.id > 0 && playTrackById(track.id)}
                    >
                      <svg
                        class="w-6 h-6"
                        fill="currentColor"
                        viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg
                      >
                    </button>
                  </div>
                </div>

                <!-- Info Block -->
                <div class="min-w-0 space-y-1">
                  <!-- Row 1: Title + Album + Plays -->
                  <div class="flex items-center gap-2 min-w-0">
                    <p
                      class={`truncate text-base font-medium ${track.id > 0 ? "text-white" : "text-white/40 line-through"}`}
                    >
                      {track.title}
                    </p>
                    <span class="text-white/40">·</span>
                    <div
                      class="flex items-center gap-2 text-sm text-white/60 truncate"
                    >
                      <span class="truncate">{track.album || "—"}</span>
                      {#if track.popularity}
                        <span class="opacity-50">•</span>
                        <span class="text-white/50"
                          >{formatPlays(track.popularity)}</span
                        >
                      {/if}
                    </div>
                  </div>
                </div>

                <!-- Timing / Tech (Right Aligned) -->
                <div class="flex flex-col items-end gap-1 text-right">
                  <span class="text-sm text-white/50 tabular-nums font-mono">
                    {formatDuration(track.duration_seconds)}
                  </span>
                  <div
                    class="flex items-center gap-2 text-xs text-white/30 uppercase tracking-wider font-medium min-h-[18px]"
                  >
                    {#if track.codec}
                      <span>{track.codec}</span>
                    {/if}
                    {#if track.bit_depth && track.sample_rate_hz}
                      <span>•</span>
                      <span
                        >{track.bit_depth}bit / {Math.round(
                          track.sample_rate_hz / 1000,
                        )}kHz</span
                      >
                    {/if}
                  </div>
                </div>

                <!-- Hover Actions (Floating) -->
                {#if track.id > 0}
                  <div
                    class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity absolute right-2 top-2 bg-black/50 backdrop-blur-sm rounded-lg p-1"
                  >
                    <button
                      class="p-1.5 hover:bg-white/20 rounded-md text-white/70 hover:text-white transition-colors"
                      title="Add to Playlist"
                      on:click={(e) => {
                        e.stopPropagation();
                        openPlaylistModal(track.id);
                      }}
                    >
                      <!-- List Plus Icon for Playlist -->
                      <svg
                        class="w-4 h-4"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          stroke-linecap="round"
                          stroke-linejoin="round"
                          stroke-width="2"
                          d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"
                        />
                      </svg>
                    </button>
                    <button
                      class="p-1.5 hover:bg-white/20 rounded-md text-white/70 hover:text-white transition-colors"
                      title="Add to Queue"
                      on:click={(e) => {
                        e.stopPropagation();
                        addTrackToQueue(track.id);
                      }}
                    >
                      <!-- Layers/Stack Plus Icon for Queue -->
                      <svg
                        class="w-4 h-4"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          stroke-linecap="round"
                          stroke-linejoin="round"
                          stroke-width="2"
                          d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
                        />
                      </svg>
                    </button>
                  </div>
                {/if}
              </div>
            {/each}
          </div>
        {:else if activeTab === "singles_list"}
          <!-- Singles List View -->
          <div class="flex items-center gap-4 mb-4">
            <button
              class="btn btn-sm variant-filled-primary"
              on:click={playAllSingles}
            >
              <svg class="w-4 h-4 mr-2" fill="currentColor" viewBox="0 0 24 24"
                ><path d="M8 5v14l11-7z" /></svg
              >
              Play All
            </button>
            <button
              class="btn btn-sm variant-ghost-surface"
              on:click={queueAllSingles}
            >
              Add All to Queue
            </button>
            <button
              class="btn btn-sm variant-ghost-surface"
              on:click={openPlaylistModalForSingles}
            >
              Add to Playlist
            </button>
          </div>

          <div class="space-y-0.5 max-w-5xl mx-auto">
            {#each displayedSingles as single}
              <div
                class="w-full grid grid-cols-[auto,auto,1fr,auto] items-center gap-4 px-3 py-2 rounded-xl hover:bg-white/5 group transition-colors text-left border border-transparent hover:border-white/5 relative"
              >
                <!-- Spacer for Alignment -->
                <span class="w-8 text-center text-sm text-white/40 font-mono"
                ></span>

                <!-- Artwork -->
                <div
                  class="relative w-14 h-14 rounded overflow-hidden bg-surface-800 shadow-lg"
                >
                  <img
                    src={single.art_sha1
                      ? `/art/file/${single.art_sha1}`
                      : single.art_id
                        ? `/art/${single.art_id}`
                        : "/assets/default-artist-placeholder.svg"}
                    class="w-full h-full object-cover"
                    alt="Art"
                  />
                  {#if single.localId}
                    <div
                      class="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity"
                    >
                      <button
                        class="text-white hover:scale-110 transition-transform"
                        on:click={() => {
                          if (
                            single.tracksToPlay &&
                            single.tracksToPlay.length > 0
                          )
                            setQueue(single.tracksToPlay, 0);
                        }}
                      >
                        <svg
                          class="w-6 h-6"
                          fill="currentColor"
                          viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg
                        >
                      </button>
                    </div>
                  {/if}
                </div>

                <!-- Info Block -->
                <div class="min-w-0 space-y-1">
                  <!-- Row 1: Title + Album + Plays -->
                  <div class="flex items-center gap-2 min-w-0">
                    <p
                      class={`truncate text-base font-medium ${single.localId ? "text-white" : "text-white/40 line-through"}`}
                    >
                      {single.title}
                    </p>
                    <span class="text-white/40">·</span>
                    <div
                      class="flex items-center gap-2 text-sm text-white/60 truncate"
                    >
                      <span class="truncate">{single.album || "—"}</span>
                      {#if single.popularity}
                        <span class="opacity-50">•</span>
                        <span class="text-white/50"
                          >{formatPlays(single.popularity)}</span
                        >
                      {/if}
                    </div>
                  </div>

                  <!-- Secondary Row Spacer -->
                  <div class="text-xs text-white/50 tabular-nums font-mono">
                    {single.date?.substring(0, 4) || "Unknown"}
                  </div>
                </div>

                <!-- Timing / Tech (Right Aligned) -->
                <div class="flex flex-col items-end gap-1 text-right">
                  <span class="text-sm text-white/50 tabular-nums font-mono">
                    {single.tracksToPlay?.[0]?.duration_seconds
                      ? formatDuration(single.tracksToPlay[0].duration_seconds)
                      : "—"}
                  </span>
                  <div
                    class="flex items-center gap-2 text-xs text-white/30 uppercase tracking-wider font-medium min-h-[18px]"
                  >
                    {#if single.codec}
                      <span>{single.codec}</span>
                    {/if}
                    {#if single.bit_depth && single.sample_rate_hz}
                      <span>•</span>
                      <span
                        >{single.bit_depth}bit / {Math.round(
                          single.sample_rate_hz / 1000,
                        )}kHz</span
                      >
                    {/if}
                  </div>
                </div>

                <!-- Hover Actions (Floating) -->
                {#if single.localId && single.tracksToPlay && single.tracksToPlay.length > 0}
                  <div
                    class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity absolute right-2 top-2 bg-black/50 backdrop-blur-sm rounded-lg p-1"
                  >
                    <button
                      class="p-1.5 hover:bg-white/20 rounded-md text-white/70 hover:text-white transition-colors"
                      title="Add to Playlist"
                      on:click={(e) => {
                        e.stopPropagation();
                        openPlaylistModal(single.tracksToPlay.map((t) => t.id));
                      }}
                    >
                      <!-- List Plus Icon for Playlist -->
                      <svg
                        class="w-4 h-4"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          stroke-linecap="round"
                          stroke-linejoin="round"
                          stroke-width="2"
                          d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"
                        />
                      </svg>
                    </button>
                    <button
                      class="p-1.5 hover:bg-white/20 rounded-md text-white/70 hover:text-white transition-colors"
                      title="Add to Queue"
                      on:click={(e) => {
                        e.stopPropagation();
                        addToQueue(single.tracksToPlay);
                      }}
                    >
                      <!-- Layers/Stack Plus Icon for Queue -->
                      <svg
                        class="w-4 h-4"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          stroke-linecap="round"
                          stroke-linejoin="round"
                          stroke-width="2"
                          d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
                        />
                      </svg>
                    </button>
                  </div>
                {/if}
              </div>
            {/each}
          </div>
        {/if}
      {/if}
    </div>

    <!-- Right Column: Info Rail -->
    <aside class="space-y-10 h-fit lg:sticky lg:top-8">
      <!-- Library Status -->
      <div class="space-y-4">
        <h3 class="text-xs font-bold text-white/40 uppercase tracking-widest">
          Library
        </h3>
        <div class="space-y-1">
          <p class="text-3xl font-medium text-white">
            {data.albums.length} releases
          </p>
          <p class="text-xl font-medium text-white/50">
            {tracks.length} tracks
          </p>
        </div>
      </div>

      <!-- External Links -->
      <div class="space-y-4">
        <h3 class="text-xs font-bold text-white/40 uppercase tracking-widest">
          Links
        </h3>
        <div class="flex flex-col gap-4 items-start">
          {#if artist?.homepage}
            <a
              href={artist.homepage}
              target="_blank"
              class="flex items-center gap-3 text-white/60 hover:text-white transition-colors group"
            >
              <svg
                class="h-5 w-5 opacity-70 group-hover:opacity-100"
                fill="currentColor"
                viewBox="0 0 24 24"
                ><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z" /></svg
              >
              <span
                class="text-sm font-medium border-b border-transparent group-hover:border-white/20"
                >Homepage</span
              >
            </a>
          {/if}
          {#if artist?.spotify_url}
            <a
              href={artist.spotify_url}
              target="_blank"
              class="flex items-center gap-3 text-white/60 hover:text-white transition-colors group"
            >
              <img
                src="/assets/logo-spotify.svg"
                class="w-5 h-5 opacity-70 group-hover:opacity-100"
                alt="Spotify"
              />
              <span
                class="text-sm font-medium border-b border-transparent group-hover:border-white/20"
                >Spotify</span
              >
            </a>
          {/if}
          {#if artist?.musicbrainz_url}
            <a
              href={artist.musicbrainz_url}
              target="_blank"
              class="flex items-center gap-3 text-white/60 hover:text-white transition-colors group"
            >
              <img
                src="/assets/logo-musicbrainz.svg"
                class="w-5 h-5 opacity-70 group-hover:opacity-100"
                alt="MB"
              />
              <span
                class="text-sm font-medium border-b border-transparent group-hover:border-white/20"
                >MusicBrainz</span
              >
            </a>
          {/if}
          {#if artist?.wikipedia_url}
            <a
              href={artist.wikipedia_url}
              target="_blank"
              class="flex items-center gap-3 text-white/60 hover:text-white transition-colors group"
            >
              <img
                src="/assets/logo-wikipedia.svg"
                class="w-5 h-5 opacity-70 group-hover:opacity-100 invert"
                alt="Wiki"
              />
              <span
                class="text-sm font-medium border-b border-transparent group-hover:border-white/20"
                >Wikipedia</span
              >
            </a>
          {/if}
          {#if artist?.tidal_url}
            <a
              href={artist.tidal_url}
              target="_blank"
              class="flex items-center gap-3 text-white/60 hover:text-white transition-colors group"
            >
              <img
                src="/assets/logo-tidal.png"
                class="w-5 h-5 opacity-70 group-hover:opacity-100"
                alt="Tidal"
              />
              <span
                class="text-sm font-medium border-b border-transparent group-hover:border-white/20"
                >Tidal</span
              >
            </a>
          {/if}
          {#if artist?.qobuz_url}
            <a
              href={artist.qobuz_url}
              target="_blank"
              class="flex items-center gap-3 text-white/60 hover:text-white transition-colors group"
            >
              <img
                src="/assets/logo-qobuz.png"
                class="w-5 h-5 opacity-70 group-hover:opacity-100"
                alt="Qobuz"
              />
              <span
                class="text-sm font-medium border-b border-transparent group-hover:border-white/20"
                >Qobuz</span
              >
            </a>
          {/if}
          {#if artist?.lastfm_url}
            <a
              href={artist.lastfm_url}
              target="_blank"
              class="flex items-center gap-3 text-white/60 hover:text-white transition-colors group"
            >
              <img
                src="/assets/logo-lastfm.png"
                class="w-5 h-5 opacity-70 group-hover:opacity-100"
                alt="Last.fm"
              />
              <span
                class="text-sm font-medium border-b border-transparent group-hover:border-white/20"
                >Last.fm</span
              >
            </a>
          {/if}
          {#if artist?.discogs_url}
            <a
              href={artist.discogs_url}
              target="_blank"
              class="flex items-center gap-3 text-white/60 hover:text-white transition-colors group"
            >
              <img
                src="/assets/logo-discogs.svg"
                class="w-5 h-5 opacity-70 group-hover:opacity-100 invert"
                alt="Discogs"
              />
              <span
                class="text-sm font-medium border-b border-transparent group-hover:border-white/20"
                >Discogs</span
              >
            </a>
          {/if}
        </div>
      </div>

      <!-- Actions -->
      <div class="space-y-4">
        <h3 class="text-xs font-bold text-white/40 uppercase tracking-widest">
          Actions
        </h3>
        <div class="flex flex-col gap-4">
          <button
            class="flex items-center gap-3 text-white/60 hover:text-white transition-colors text-left group"
            on:click={refreshMeta}
            disabled={refreshing}
          >
            <svg
              class="w-5 h-5 opacity-70 group-hover:opacity-100"
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
            <span
              class="text-sm font-medium border-b border-transparent group-hover:border-white/20"
              >{refreshing ? "Refreshing..." : "Refresh Metadata"}</span
            >
          </button>
          <button
            class="flex items-center gap-3 text-white/60 hover:text-white transition-colors text-left group"
            on:click={scanMissing}
            disabled={scanningMissing}
          >
            <svg
              class="w-5 h-5 opacity-70 group-hover:opacity-100"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              ><path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              /></svg
            >
            <span
              class="text-sm font-medium border-b border-transparent group-hover:border-white/20"
              >{scanningMissing ? "Scanning..." : "Check Missing"}</span
            >
          </button>
        </div>
      </div>
    </aside>

    {#if missingAlbums.length > 0}
      <section class="pb-10 col-span-full">
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

<AddToPlaylistModal bind:show={showPlaylistModal} trackIds={selectedTrackIds} />

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
