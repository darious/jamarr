<script lang="ts">
  import type { Album, Artist, Track, MissingAlbum, Playlist } from "$lib/api";
  import {
    fetchTracks,
    fetchMissingAlbums,
    triggerMissingAlbumsScan,
    triggerMetadataScan,
    triggerPearlarrDownload,
    getArtUrl,
    getPlaylist,
  } from "$lib/api";
  import { goto, invalidateAll } from "$app/navigation";
  import IconButton from "$components/IconButton.svelte";
  import TrackCard from "$components/TrackCard.svelte";
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
    playlists: Playlist[];
    similarArtists: {
      name: string;
      mbid?: string | null;
      art_sha1?: string | null;
      in_library?: boolean;
      external_url?: string | null;
    }[];
  };

  let artist: Artist | undefined = data.artist;
  let playlists: Playlist[] = data.playlists || [];
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
  // Pearlarr State
  let downloadingMbids = new Set<string>();

  async function downloadAlbum(mbid: string) {
    if (downloadingMbids.has(mbid)) return;
    downloadingMbids.add(mbid);
    downloadingMbids = downloadingMbids; // Reactivity

    try {
      await triggerPearlarrDownload(mbid);
      message = "Download queued in Pearlarr";
      setTimeout(() => {
        if (message.includes("Pearlarr")) message = "";
      }, 3000);
    } catch (e) {
      console.error(e);
      downloadingMbids.delete(mbid);
      downloadingMbids = downloadingMbids;
      message = "Failed to queue download";
    }
  }

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
  $: if (data.playlists !== playlists) {
    playlists = data.playlists || [];
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
      ? getArtUrl(artist.background_sha1, 600)
      : artist.art_sha1
        ? getArtUrl(artist.art_sha1, 300)
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

  const formatListens = (listens?: number) => {
    if (!listens) return "0 listens";
    if (listens >= 1000000) return `${(listens / 1000000).toFixed(1)}M listens`;
    if (listens >= 1000) return `${(listens / 1000).toFixed(1)}K listens`;
    return `${listens} listens`;
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

  const getArtistArtUrl = (sha1: string) => {
    return getArtUrl(sha1, 300);
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
          // Local track provides: path, codec, bitrate, sample_rate, bit_depth, art_sha1
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
            art_sha1: t.art_sha1 || local.art_sha1,
            mb_release_id: t.mb_release_id || local.mb_release_id,
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
            art_sha1: t.art_sha1 || null,
            mb_release_id: t.mb_release_id, // Use API data directly
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

  $: displayedMostListened = (() => {
    const fromMeta = artist?.most_listened || [];
    return fromMeta.map((t) => {
      let result: Track;
      if (t.local_track_id) {
        const local = tracks.find((lt) => lt.id === t.local_track_id);
        if (local) {
          result = {
            ...local,
            title: t.name || local.title,
            album: t.album || local.album,
            date: t.date || local.date,
            duration_seconds: t.duration_seconds || local.duration_seconds,
            art_sha1: t.art_sha1 || local.art_sha1,
            mb_release_id: t.mb_release_id || local.mb_release_id,
            plays: t.plays ?? local.plays,
          };
        } else {
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
            duration_seconds: t.duration_seconds || 0,
            art_sha1: t.art_sha1 || null,
            mb_release_id: t.mb_release_id,
            codec: t.codec || null,
            bitrate: null,
            sample_rate_hz: t.sample_rate_hz || null,
            bit_depth: t.bit_depth || null,
            plays: t.plays ?? undefined,
          };
        }
      } else {
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
          duration_seconds: t.duration_seconds || 0,
          art_sha1: t.art_sha1 || null,
          codec: t.codec || null,
          bitrate: null,
          sample_rate_hz: null,
          bit_depth: null,
          plays: t.plays ?? undefined,
        };
      }
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
        let art_sha1 = null;
        let artists: { name: string; mbid?: string }[] | undefined;

        if (s.local_track_id) {
          // Single is in library - find the track
          const localTrack = tracks.find((t) => t.id === s.local_track_id);
          if (localTrack) {
            localId = s.title; // Use title as ID
            navAlbum = localTrack.album;
            tracksToPlay = [localTrack];
            artists = localTrack.artists;
            techData = {
              codec: s.codec || localTrack.codec,
              bit_depth: s.bit_depth || localTrack.bit_depth,
              sample_rate_hz: s.sample_rate_hz || localTrack.sample_rate_hz,
            };

            // Get artwork - prioritize from Singles API data, then from local track, then from album
            art_sha1 = s.art_sha1 || localTrack.art_sha1;

            // Fallback to album artwork if still not found
            if (!art_sha1) {
              const album = data.albums.find(
                (a) => a.album === localTrack.album,
              );
              if (album) {
                art_sha1 = album.art_sha1;
              }
            }
          }
        }

        return {
          ...s,
          localId,
          art_sha1,
          navAlbum,
          mb_release_id: s.mb_release_id,
          ...techData,
          tracksToPlay,
          artists,
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

  async function playAllMostListened() {
    const playableTracks: Track[] = displayedMostListened
      .map((t) => {
        if (!t.id || t.id <= 0) return null;
        return tracks.find((lt) => lt.id === t.id) || t;
      })
      .filter((t): t is Track => Boolean(t));
    if (playableTracks.length > 0) {
      await setQueue(playableTracks, 0);
    }
  }

  async function queueAllMostListened() {
    const playableTracks: Track[] = displayedMostListened
      .map((t) => {
        if (!t.id || t.id <= 0) return null;
        return tracks.find((lt) => lt.id === t.id) || t;
      })
      .filter((t): t is Track => Boolean(t));
    if (playableTracks.length > 0) {
      await addToQueue(playableTracks);
    }
  }

  async function openPlaylistModalForMostListened() {
    const ids = displayedMostListened
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
      const albumId = album.mb_release_id;
      if (albumId) {
        goto(`/album/${albumId}`);
      } else {
        console.error("No album ID available for navigation", album);
      }
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

  async function playPlaylist(e: MouseEvent, playlistId: number) {
    e.stopPropagation();
    try {
      const playlist = await getPlaylist(playlistId);
      if (playlist && playlist.tracks.length > 0) {
        const queueItems = playlist.tracks.map((t) => ({
          ...t,
          id: t.track_id,
        }));
        await setQueue(queueItems as unknown as Track[], 0);
      }
    } catch (error) {
      console.error("Failed to play playlist:", error);
    }
  }

  async function queuePlaylist(e: MouseEvent, playlistId: number) {
    e.stopPropagation();
    try {
      const playlist = await getPlaylist(playlistId);
      if (playlist && playlist.tracks.length > 0) {
        const queueItems = playlist.tracks.map((t) => ({
          ...t,
          id: t.track_id,
        }));
        await addToQueue(queueItems as unknown as Track[]);
      }
    } catch (error) {
      console.error("Failed to queue playlist:", error);
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
    {
      label: "Playlists",
      value: "playlists",
      count: playlists.length,
    },
  ]
    .filter((t) => t.count > 0)
    .map((t) => ({ ...t, label: `${t.label} (${t.count})` }));

  // Track Tabs (Right Side)
  $: trackTabs = [
    {
      label: "Most Scrobbled",
      value: "top_tracks",
      count: displayedTopTracks.length,
    },
    {
      label: "Most Listened",
      value: "most_listened",
      count: displayedMostListened.length,
    },
    {
      label: "Singles",
      value: "singles_list", // Distinction from release-type singles
      count: displayedSingles.length,
    },
  ]
    .filter((t) => t.count > 0)
    .map((t) => ({ ...t, label: `${t.label} (${t.count})` }));

  $: allTabs = [
    ...releaseTabs,
    ...(missingAlbums.length > 0
      ? [{ value: "missing_albums", label: "Missing" }]
      : []),
    ...trackTabs,
  ];

  // Ensure activeTab is valid
  $: if (allTabs.length > 0 && !allTabs.find((t) => t.value === activeTab)) {
    // Default to first available release tab, or first track tab
    if (releaseTabs.length > 0) activeTab = releaseTabs[0].value;
    else if (trackTabs.length > 0) activeTab = trackTabs[0].value;
    else if (missingAlbums.length > 0) activeTab = "missing_albums";
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
          ? getArtUrl(artist.background_sha1, 600)
          : artist?.art_sha1
            ? getArtUrl(artist.art_sha1, 300)
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
      style="mask-image: linear-gradient(to bottom, black 50%, transparent 100%);"
    >
      <!-- Sharp Top Layer (Fades into Global Background) -->
      <div
        class="absolute inset-0 bg-cover bg-top transition-transform duration-1000 scale-105 group-hover:scale-100"
        style={`background-image:url('${
          artist?.background_sha1
            ? getArtUrl(artist.background_sha1, 600)
            : artist?.art_sha1
              ? getArtUrl(artist.art_sha1, 300)
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
    <div class="space-y-8 min-w-0">
      <!-- Bio Section -->
      {#if artist?.bio}
        <section>
          <div class="relative group">
            <p
              class={`text-lg md:text-xl leading-relaxed text-default/90 font-medium max-w-4xl transition-all duration-500 ${
                isBioExpanded ? "" : "line-clamp-3"
              }`}
            >
              {artist.bio}
            </p>
            {#if artist.bio.length > 300}
              <button
                on:click={() => (isBioExpanded = !isBioExpanded)}
                class="mt-3 text-sm font-bold text-muted uppercase tracking-widest hover:text-default transition-colors"
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
            class="text-xs font-bold text-muted uppercase tracking-widest mb-6"
          >
            Similar Artists
          </h3>
          <div class="flex flex-wrap gap-4">
            {#each displayedSimilarArtists.slice(0, 10) as sim}
              <button
                class="group w-24 text-center space-y-2"
                on:click|stopPropagation={() => {
                  if (sim.in_library && sim.mbid) {
                    goto(`/artist/${sim.mbid}`);
                  } else if (sim.external_url) {
                    window.open(sim.external_url, "_blank");
                  }
                }}
              >
                <div
                  class="relative aspect-square rounded-full overflow-hidden bg-surface-2 ring-1 ring-subtle group-hover:ring-primary-500 transition-all shadow-lg"
                >
                  {#if sim.art_sha1}
                    <img
                      src={sim.art_sha1 ? getArtUrl(sim.art_sha1, 300) : ""}
                      class="w-full h-full object-cover opacity-90 group-hover:opacity-100 transition-opacity"
                      alt={sim.name}
                    />
                  {:else}
                    <div
                      class="w-full h-full flex items-center justify-center text-xs font-bold text-muted bg-surface-3"
                    >
                      {getInitials(sim.name)}
                    </div>
                  {/if}
                </div>
                <p
                  class="text-xs font-medium text-muted group-hover:text-default truncate"
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
        <div class="relative" style="margin-bottom: 24px !important;">
          <div
            class="flex flex-wrap items-center gap-8 border-b border-subtle pb-0"
          >
            <!-- Left Group: Releases -->
            <div class="relative">
              <div class="flex gap-4">
                {#each releaseTabs as tab}
                  <button
                    class={`relative px-2 py-3 text-sm font-medium transition-all duration-200 border-b-2 -mb-[1.5px] ${
                      activeTab === tab.value
                        ? "text-default border-accent"
                        : "text-muted border-transparent hover:text-default hover:border-accent"
                    }`}
                    on:click={() => (activeTab = tab.value)}
                  >
                    {tab.label}
                  </button>
                {/each}
              </div>
            </div>

            <!-- Spacer -->
            <div class="flex-1"></div>

            {#if missingAlbums.length > 0}
              <div class="relative">
                <div class="flex gap-4">
                  <button
                    class={`relative px-2 py-3 text-sm font-medium transition-all duration-200 border-b-2 -mb-[1.5px] ${
                      activeTab === "missing_albums"
                        ? "text-default border-accent"
                        : "text-muted border-transparent hover:text-default hover:border-accent"
                    }`}
                    on:click={() => (activeTab = "missing_albums")}
                  >
                    Missing
                  </button>
                </div>
              </div>
            {/if}

            <!-- Right Group: Tracks -->
            <div class="relative">
              <div class="flex gap-4">
                {#each trackTabs as tab}
                  <button
                    class={`relative px-2 py-3 text-sm font-medium transition-all duration-200 border-b-2 -mb-[1.5px] ${
                      activeTab === tab.value
                        ? "text-default border-accent"
                        : "text-muted border-transparent hover:text-default hover:border-accent"
                    }`}
                    on:click={() => (activeTab = tab.value)}
                  >
                    {tab.label}
                  </button>
                {/each}
              </div>
            </div>
          </div>
        </div>

        <!-- Albums Grid -->
        {#if ["album", "ep", "single", "compilation", "live", "appears_on"].includes(activeTab)}
          {#if displayedAlbums.length > 0}
            <div
              class="grid gap-8 grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
            >
              {#each displayedAlbums as album, index (album.mb_release_id ?? `${album.album}-${album.artist_name}-${index}`)}
                <article class="group flex flex-col gap-4">
                  <button
                    class="relative aspect-square overflow-hidden rounded-lg shadow-2xl bg-surface-800 transition-transform duration-300 hover:scale-105"
                    on:click={() => {
                      const albumId = album.mb_release_id;
                      if (albumId) goto(`/album/${albumId}`);
                    }}
                  >
                    <img
                      src={album.art_sha1
                        ? getArtUrl(album.art_sha1, 300)
                        : "/assets/default-album-placeholder.svg"}
                      alt={album.album}
                      class="h-full w-full object-cover"
                      loading="lazy"
                    />
                    <!-- Play Overlay -->
                    <div
                      class="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-3"
                    >
                      <IconButton
                        variant="primary"
                        title="Play"
                        onClick={() => playAlbum(album)}
                        stopPropagation={true}
                      >
                        <svg
                          class="h-6 w-6"
                          fill="currentColor"
                          viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg
                        >
                      </IconButton>
                      <IconButton
                        variant="primary"
                        title="Add to Queue"
                        onClick={() => addAlbumToQueue(album)}
                        stopPropagation={true}
                      >
                        <svg
                          class="h-6 w-6"
                          fill="currentColor"
                          viewBox="0 0 24 24"
                          ><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg
                        >
                      </IconButton>
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
                      class="text-base font-bold text-default leading-tight line-clamp-2 group-hover:text-primary-400 transition-colors"
                      title={album.album}
                    >
                      {album.album}
                    </h3>
                    <p class="text-sm text-muted font-medium">
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
        {:else if activeTab === "playlists"}
          {#if playlists.length > 0}
            <div
              class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-6"
            >
              {#each playlists as p (p.id)}
                <div
                  class="group relative block surface-glass-panel rounded-xl overflow-hidden hover:bg-surface-2 transition-all duration-300 hover:scale-105 hover:z-10 hover:shadow-xl"
                >
                  <div
                    class="aspect-square w-full bg-surface-3 relative transition-transform duration-300"
                  >
                    <a href="/playlists/{p.id}" class="block w-full h-full">
                      {#if p.thumbnails && p.thumbnails.length > 0}
                        {#if p.thumbnails.length >= 4}
                          <div class="grid grid-cols-2 h-full w-full">
                            {#each p.thumbnails.slice(0, 4) as thumb}
                              <img
                                src={getArtistArtUrl(thumb)}
                                alt=""
                                class="w-full h-full object-cover"
                                loading="lazy"
                              />
                            {/each}
                          </div>
                        {:else}
                          <img
                            src={getArtistArtUrl(p.thumbnails[0])}
                            alt={p.name}
                            class="w-full h-full object-cover"
                            loading="lazy"
                          />
                        {/if}
                      {:else}
                        <div
                          class="flex items-center justify-center w-full h-full text-subtle bg-surface-2"
                        >
                          <svg
                            class="w-12 h-12"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              stroke-linecap="round"
                              stroke-linejoin="round"
                              stroke-width="1.5"
                              d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 3-.895 3-2 3 .895 3 2zM9 10l12-3"
                            />
                          </svg>
                        </div>
                      {/if}

                      {#if !p.is_public}
                        <div
                          class="absolute top-2 right-2 bg-surface-3 p-1 rounded-full backdrop-blur-sm z-10"
                        >
                          <svg
                            class="w-3 h-3 text-muted"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              stroke-linecap="round"
                              stroke-linejoin="round"
                              stroke-width="2"
                              d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
                            ></path>
                          </svg>
                        </div>
                      {/if}
                    </a>

                    <!-- Hover Overlay -->
                    <div
                      class="absolute inset-0 opacity-0 transition-opacity group-hover:opacity-100 flex items-center justify-center gap-3 z-10 pointer-events-none"
                    >
                      <div
                        class="pointer-events-auto flex items-center gap-3 text-white"
                      >
                        <IconButton
                          variant="primary"
                          title="Play"
                          onClick={(e) => playPlaylist(e, p.id)}
                          stopPropagation={true}
                          className="shadow-lg transition-all"
                        >
                          <svg
                            class="h-6 w-6 ml-0.5"
                            fill="currentColor"
                            viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg
                          >
                        </IconButton>
                        <IconButton
                          variant="primary"
                          title="Add to Queue"
                          onClick={(e) => queuePlaylist(e, p.id)}
                          stopPropagation={true}
                          className="shadow-lg transition-all"
                        >
                          <svg
                            class="h-6 w-6"
                            fill="currentColor"
                            viewBox="0 0 24 24"
                            ><path
                              d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"
                            /></svg
                          >
                        </IconButton>
                      </div>
                    </div>
                  </div>

                  <div class="p-4">
                    <a href="/playlists/{p.id}" class="block">
                      <div
                        class="font-bold text-default truncate text-lg hover:underline decoration-subtle underline-offset-4"
                      >
                        {p.name}
                      </div>
                    </a>
                    <div class="text-muted text-xs mt-1">
                      {p.track_count} tracks • {p.is_public
                        ? "Shared"
                        : "Private"}
                    </div>
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        {:else if activeTab === "top_tracks"}
          <!-- Top Tracks List View -->
          <div class="space-y-1 max-w-5xl mx-auto">
            {#each displayedTopTracks as track, i}
              <TrackCard
                {track}
                artists={track.artists}
                artist={{ name: artist?.name || "", mbid: artist?.mbid }}
                album={{
                  name: track.album || "",
                  mbid: track.mb_release_id,
                  mb_release_id: track.mb_release_id,
                }}
                artwork={{
                  sha1: track.art_sha1,
                }}
                showIndex={true}
                index={i + 1}
                showArtwork={true}
                showAlbum={true}
                showArtist={false}
                showYear={false}
                showTechDetails={true}
                showPopularity={true}
                onPlay={() => track.id > 0 && playTrackById(track.id)}
                onQueue={() => addTrackToQueue(track.id)}
                onAddToPlaylist={() => openPlaylistModal(track.id)}
              />
            {/each}
          </div>
        {:else if activeTab === "most_listened"}
          <!-- Most Listened Tracks List View -->
          <div class="space-y-1 max-w-5xl mx-auto">
            {#each displayedMostListened as track, i}
              <TrackCard
                {track}
                artists={track.artists}
                artist={{ name: artist?.name || "", mbid: artist?.mbid }}
                album={{
                  name: track.album || "",
                  mbid: track.mb_release_id,
                  mb_release_id: track.mb_release_id,
                }}
                artwork={{
                  sha1: track.art_sha1,
                }}
                showIndex={true}
                index={i + 1}
                showArtwork={true}
                showAlbum={true}
                showArtist={false}
                showYear={false}
                showTechDetails={true}
                showPopularity={false}
                onPlay={() => track.id > 0 && playTrackById(track.id)}
                onQueue={() => addTrackToQueue(track.id)}
                onAddToPlaylist={() => openPlaylistModal(track.id)}
              />
            {/each}
          </div>
        {:else if activeTab === "singles_list"}
          <!-- Singles List View -->
          <div class="space-y-1 max-w-5xl mx-auto">
            {#each displayedSingles as single}
              <TrackCard
                track={{
                  id: single.localId || 0,
                  title: single.title,
                  duration_seconds: single.tracksToPlay?.[0]?.duration_seconds,
                  codec: single.codec,
                  bit_depth: single.bit_depth,
                  sample_rate_hz: single.sample_rate_hz,
                  popularity: single.popularity,
                  plays: single.tracksToPlay?.[0]?.plays,
                }}
                artists={single.artists}
                artist={{ name: artist?.name || "", mbid: artist?.mbid }}
                album={{
                  name: single.album || "",
                  mbid: single.mb_release_id,
                  mb_release_id: single.mb_release_id,
                  year: single.date,
                }}
                artwork={{
                  sha1: single.art_sha1,
                }}
                showIndex={false}
                showArtwork={true}
                showAlbum={true}
                showArtist={false}
                showYear={true}
                showTechDetails={true}
                showPopularity={true}
                onPlay={() => {
                  if (single.tracksToPlay && single.tracksToPlay.length > 0)
                    setQueue(single.tracksToPlay, 0);
                }}
                onQueue={() => {
                  if (single.tracksToPlay) addToQueue(single.tracksToPlay);
                }}
                onAddToPlaylist={() => {
                  if (single.tracksToPlay)
                    openPlaylistModal(single.tracksToPlay.map((t) => t.id));
                }}
              />
            {/each}
          </div>
        {:else if activeTab === "missing_albums"}
          <!-- Missing Albums Table -->
          <div
            class="glass-surface rounded-2xl overflow-hidden border border-subtle bg-surface-2 backdrop-blur-xl"
          >
            <table class="w-full text-left text-sm whitespace-nowrap">
              <thead
                class="uppercase tracking-wider border-b border-subtle text-muted text-xs bg-surface-3"
              >
                <tr>
                  <th class="px-6 py-4">Released</th>
                  <th class="px-6 py-4">Album</th>
                  <th class="px-6 py-4 text-center w-24">Download</th>
                  <th class="px-6 py-4 text-center w-24">Link</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-subtle">
                {#each missingAlbums as album}
                  <tr class="hover:bg-surface-3 transition-colors">
                    <td class="px-6 py-4 text-default font-mono tabular-nums"
                      >{album.release_date || "—"}</td
                    >
                    <td class="px-6 py-4 font-medium text-default"
                      >{album.title}</td
                    >
                    <td class="px-6 py-4 text-center">
                      <button
                        class="opacity-50 hover:opacity-100 transition-opacity hover:scale-110 transform disabled:opacity-20 disabled:cursor-not-allowed"
                        on:click={() => downloadAlbum(album.mbid)}
                        disabled={downloadingMbids.has(album.mbid)}
                        title="Download with Pearlarr"
                      >
                        <img
                          src="/assets/icon-pearlarr.svg"
                          class="w-5 h-5"
                          alt="Download"
                        />
                      </button>
                    </td>
                    <td class="px-6 py-4">
                      <div class="flex items-center justify-center">
                        {#if album.musicbrainz_url}
                          <a
                            href={album.musicbrainz_url}
                            target="_blank"
                            class="opacity-50 hover:opacity-100 transition-opacity hover:scale-110 transform"
                            title="View on MusicBrainz"
                            ><img
                              src="/assets/logo-musicbrainz.svg"
                              class="w-5 h-5"
                              alt="MB"
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
        {/if}
      {/if}
    </div>

    <!-- Right Column: Info Rail -->
    <aside class="space-y-10 h-fit lg:sticky lg:top-8">
      <!-- Library Status -->
      <div class="space-y-4">
        <h3 class="text-xs font-bold text-subtle uppercase tracking-widest">
          Library
        </h3>
        <div class="space-y-1">
          <p class="text-3xl font-medium text-default">
            {data.albums.length} releases
          </p>
          <p class="text-xl font-medium text-default">
            {tracks.length} tracks
          </p>
          {#if artist?.mbid}
            <a
              class="text-xl font-medium text-default underline underline-offset-4 hover:text-primary transition-colors"
              href={`/history?artist_mbid=${encodeURIComponent(
                artist.mbid,
              )}&artist_name=${encodeURIComponent(artist?.name || data.name)}`}
            >
              {formatListens(artist?.listens)}
            </a>
          {:else}
            <p class="text-xl font-medium text-default">
              {formatListens(artist?.listens)}
            </p>
          {/if}
        </div>
      </div>

      <!-- External Links -->
      <div class="space-y-4">
        <h3 class="text-xs font-bold text-muted uppercase tracking-widest">
          Links
        </h3>
        <div class="flex flex-col gap-4 items-start">
          {#if artist?.homepage}
            <a
              href={artist.homepage}
              target="_blank"
              class="flex items-center gap-3 text-default hover:text-primary transition-colors group"
            >
              <svg
                class="h-5 w-5 opacity-70 group-hover:opacity-100"
                fill="currentColor"
                viewBox="0 0 24 24"
                ><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z" /></svg
              >
              <span
                class="text-sm font-medium border-b border-transparent group-hover:border-subtle"
                >Homepage</span
              >
            </a>
          {/if}
          {#if artist?.spotify_url}
            <a
              href={artist.spotify_url}
              target="_blank"
              class="flex items-center gap-3 text-default hover:text-primary transition-colors group"
            >
              <img
                src="/assets/logo-spotify.svg"
                class="w-5 h-5 opacity-70 group-hover:opacity-100"
                alt="Spotify"
              />
              <span
                class="text-sm font-medium border-b border-transparent group-hover:border-subtle"
                >Spotify</span
              >
            </a>
          {/if}
          {#if artist?.musicbrainz_url}
            <a
              href={artist.musicbrainz_url}
              target="_blank"
              class="flex items-center gap-3 text-default hover:text-primary transition-colors group"
            >
              <img
                src="/assets/logo-musicbrainz.svg"
                class="w-5 h-5 opacity-70 group-hover:opacity-100"
                alt="MB"
              />
              <span
                class="text-sm font-medium border-b border-transparent group-hover:border-subtle"
                >MusicBrainz</span
              >
            </a>
          {/if}
          {#if artist?.wikipedia_url}
            <a
              href={artist.wikipedia_url}
              target="_blank"
              class="flex items-center gap-3 text-default hover:text-primary transition-colors group"
            >
              <img
                src="/assets/logo-wikipedia.svg"
                class="w-5 h-5 opacity-70 group-hover:opacity-100 invert"
                alt="Wiki"
              />
              <span
                class="text-sm font-medium border-b border-transparent group-hover:border-subtle"
                >Wikipedia</span
              >
            </a>
          {/if}
          {#if artist?.tidal_url}
            <a
              href={artist.tidal_url}
              target="_blank"
              class="flex items-center gap-3 text-default hover:text-primary transition-colors group"
            >
              <img
                src="/assets/logo-tidal.png"
                class="w-5 h-5 opacity-70 group-hover:opacity-100"
                alt="Tidal"
              />
              <span
                class="text-sm font-medium border-b border-transparent group-hover:border-subtle"
                >Tidal</span
              >
            </a>
          {/if}
          {#if artist?.qobuz_url}
            <a
              href={artist.qobuz_url}
              target="_blank"
              class="flex items-center gap-3 text-default hover:text-primary transition-colors group"
            >
              <img
                src="/assets/logo-qobuz.png"
                class="w-5 h-5 opacity-70 group-hover:opacity-100"
                alt="Qobuz"
              />
              <span
                class="text-sm font-medium border-b border-transparent group-hover:border-subtle"
                >Qobuz</span
              >
            </a>
          {/if}
          {#if artist?.lastfm_url}
            <a
              href={artist.lastfm_url}
              target="_blank"
              class="flex items-center gap-3 text-default hover:text-primary transition-colors group"
            >
              <img
                src="/assets/logo-lastfm.png"
                class="w-5 h-5 opacity-70 group-hover:opacity-100"
                alt="Last.fm"
              />
              <span
                class="text-sm font-medium border-b border-transparent group-hover:border-subtle"
                >Last.fm</span
              >
            </a>
          {/if}
          {#if artist?.discogs_url}
            <a
              href={artist.discogs_url}
              target="_blank"
              class="flex items-center gap-3 text-default hover:text-primary transition-colors group"
            >
              <img
                src="/assets/logo-discogs.svg"
                class="w-5 h-5 opacity-70 group-hover:opacity-100 invert"
                alt="Discogs"
              />
              <span
                class="text-sm font-medium border-b border-transparent group-hover:border-subtle"
                >Discogs</span
              >
            </a>
          {/if}
        </div>
      </div>

      <!-- Actions -->
      <div class="space-y-4">
        <h3 class="text-xs font-bold text-muted uppercase tracking-widest">
          Actions
        </h3>
        <div class="flex flex-col gap-2">
          <button
            class="flex items-center gap-3 px-3 py-2 text-default hover:text-primary transition-all text-left w-full border-b border-transparent hover:border-accent group hover:bg-transparent"
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
            <span class="text-sm font-medium"
              >{refreshing ? "Refreshing..." : "Refresh Metadata"}</span
            >
          </button>
          <button
            class="flex items-center gap-3 px-3 py-2 text-default hover:text-primary transition-all text-left w-full border-b border-transparent hover:border-accent group hover:bg-transparent"
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
            <span class="text-sm font-medium"
              >{scanningMissing ? "Scanning..." : "Check Missing"}</span
            >
          </button>

          <!-- Track Actions (only show for track tabs) -->
          {#if activeTab === "top_tracks" || activeTab === "singles_list" || activeTab === "most_listened"}
            <div class="mt-6 pt-6 border-t border-subtle">
              <h3
                class="text-xs font-semibold text-muted uppercase tracking-wider mb-3"
              >
                Track Actions
              </h3>
              <div class="flex flex-col gap-2">
                <button
                  class="w-full px-3 py-2 text-left text-sm text-default hover:text-primary transition-all border-b border-transparent hover:border-accent flex items-center gap-2 font-normal"
                  on:click={activeTab === "top_tracks"
                    ? playAllTopTracks
                    : activeTab === "most_listened"
                      ? playAllMostListened
                      : playAllSingles}
                >
                  <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M8 5v14l11-7z" />
                  </svg>
                  Play All
                </button>
                <button
                  class="w-full px-3 py-2 text-left text-sm text-default hover:text-primary transition-all border-b border-transparent hover:border-accent flex items-center gap-2 font-normal"
                  on:click={activeTab === "top_tracks"
                    ? queueAllTopTracks
                    : activeTab === "most_listened"
                      ? queueAllMostListened
                      : queueAllSingles}
                >
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
                      d="M12 4v16m8-8H4"
                    />
                  </svg>
                  Add All to Queue
                </button>
                <button
                  class="w-full px-3 py-2 text-left text-sm text-default hover:text-primary transition-all border-b border-transparent hover:border-accent flex items-center gap-2 font-normal"
                  on:click={activeTab === "top_tracks"
                    ? openPlaylistModalForTopTracks
                    : activeTab === "most_listened"
                      ? openPlaylistModalForMostListened
                      : openPlaylistModalForSingles}
                >
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
                      d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
                    />
                  </svg>
                  Add to Playlist
                </button>
              </div>
            </div>
          {/if}
        </div>
      </div>
    </aside>
  </main>
</div>

<AddToPlaylistModal
  bind:visible={showPlaylistModal}
  trackIds={selectedTrackIds}
/>

<style>
  .custom-scrollbar::-webkit-scrollbar {
    width: 6px;
  }

  .custom-scrollbar::-webkit-scrollbar-track {
    background: transparent;
  }

  .custom-scrollbar::-webkit-scrollbar-thumb {
    background: rgb(255 255 255 / 10%);
    border-radius: 10px;
  }

  .custom-scrollbar::-webkit-scrollbar-thumb:hover {
    background: rgb(255 255 255 / 20%);
  }

  /* Tab hover effect matching button style */
  .tab-hover:hover {
    background: color-mix(
      in srgb,
      var(--accent) 25%,
      rgb(0 0 0 / 40%)
    ) !important;
  }
</style>
