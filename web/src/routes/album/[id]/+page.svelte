<script lang="ts">
  import type { Album, Track } from "$api";
  import { setQueue, addToQueue } from "$stores/player";
  import { goto } from "$app/navigation";
  import AddToPlaylistModal from "$components/AddToPlaylistModal.svelte";
  import IconButton from "$components/IconButton.svelte";
  import TrackCard from "$components/TrackCard.svelte";
  import { downloadTracks } from "$lib/helpers/downloader";
  import { getArtUrl, setReleaseFavorite } from "$lib/api";

  let showPlaylistModal = false;
  let selectedTrackIds: number[] = [];
  let isDescriptionExpanded = false;
  let favoritePending = false;

  function openPlaylistModal(trackId: number) {
    selectedTrackIds = [trackId];
    showPlaylistModal = true;
  }

  export let data: {
    artist: string;
    album: string;
    tracks: Track[];
    albumMeta?: Album;
  };

  async function toggleAlbumFavorite() {
    const albumMbid = data.albumMeta?.album_mbid || data.albumMeta?.mb_release_id;
    if (!albumMbid || favoritePending || !data.albumMeta) return;

    const nextFavorite = !data.albumMeta.is_favorite;
    favoritePending = true;
    data = {
      ...data,
      albumMeta: {
        ...data.albumMeta,
        is_favorite: nextFavorite,
      },
    };

    try {
      await setReleaseFavorite(albumMbid, nextFavorite);
    } catch (e) {
      console.error("Failed to update release favorite", e);
      data = {
        ...data,
        albumMeta: {
          ...data.albumMeta,
          is_favorite: !nextFavorite,
        },
      };
    } finally {
      favoritePending = false;
    }
  }

  // Reactive album art URL - recalculates when data changes
  $: albumArtUrl = (() => {
    if (data.albumMeta?.art_sha1) return getArtUrl(data.albumMeta.art_sha1);
    const withArt = data.tracks.find((t) => t.art_sha1);
    if (withArt?.art_sha1) return getArtUrl(withArt.art_sha1);
    return "/assets/default-album-placeholder.svg";
  })();

  const getMusicBrainzUrl = () => {
    if (data.albumMeta?.musicbrainz_url) return data.albumMeta.musicbrainz_url;
    const track = data.tracks?.[0];
    const mbBase = "http://musicbrainz.org";
    if (track?.mb_release_id) return `${mbBase}/release/${track.mb_release_id}`;
    return null;
  };

  const getLinkIcon = (type: string) => {
    switch (type) {
      case "spotify":
        return { src: "/assets/logo-spotify.svg", alt: "Spotify" };
      case "musicbrainz":
        return { src: "/assets/logo-musicbrainz.svg", alt: "MusicBrainz" };
      case "tidal":
        return { src: "/assets/logo-tidal.png", alt: "Tidal" };
      case "qobuz":
        return { src: "/assets/logo-qobuz.png", alt: "Qobuz" };
      case "lastfm":
        return { src: "/assets/logo-lastfm.png", alt: "Last.fm" };
      case "discogs":
        return {
          src: "/assets/logo-discogs.svg",
          alt: "Discogs",
          invert: true,
        };
      case "wikipedia":
        return {
          src: "/assets/logo-wikipedia.svg",
          alt: "Wikipedia",
          invert: true,
        };
      default:
        return null;
    }
  };

  const getExternalLinks = () => {
    const links = data.albumMeta?.external_links || [];
    const priority = ["musicbrainz", "wikipedia", "discogs"];

    return [...links].sort((a, b) => {
      const idxA = priority.indexOf(a.type);
      const idxB = priority.indexOf(b.type);

      // If both are in priority list, sort by index
      if (idxA !== -1 && idxB !== -1) return idxA - idxB;
      // If only A is in priority, it comes first
      if (idxA !== -1) return -1;
      // If only B is in priority, it comes first
      if (idxB !== -1) return 1;
      // Otherwise sort alphabetically
      return a.type.localeCompare(b.type);
    });
  };

  const totalDuration = () =>
    Math.round(
      (data.tracks || []).reduce(
        (acc, t) => acc + (t.duration_seconds || 0),
        0,
      ) / 60,
    );

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

  $: groupedTracks = (() => {
    const groups: { [key: number]: Track[] } = {};
    for (const track of data.tracks) {
      const disc = track.disc_no || 1;
      if (!groups[disc]) groups[disc] = [];
      groups[disc].push(track);
    }
    // Sort by disc number
    return Object.entries(groups)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([disc, tracks]) => ({
        disc: Number(disc),
        tracks: tracks.sort((a, b) => (a.track_no || 0) - (b.track_no || 0)),
      }));
  })();

  function playAll() {
    if (data.tracks?.length) {
      void setQueue(data.tracks, 0);
    }
  }

  function playDisc(tracks: Track[]) {
    void setQueue(tracks, 0);
  }

  function addAllToQueue() {
    if (data.tracks?.length) {
      addToQueue(data.tracks);
    }
  }

  function handleDownload() {
    // Use sort_name if available for better folder sorting (e.g. "Kennedy, Dermot")
    let artistName = data.artist;

    if (data.albumMeta?.artists?.[0]?.sort_name) {
      artistName = data.albumMeta.artists[0].sort_name;
    }

    void downloadTracks({
      mode: "album",
      folderName: artistName,
      subFolderName: data.album,
      tracks: data.tracks,
    });
  }

  function playTrack(track: Track) {
    // Play just the selected track
    void setQueue([track], 0);
  }
</script>

<div class="fixed inset-0 z-0 overflow-hidden pointer-events-none">
  <!-- Blurred Background -->
  <div
    class="absolute inset-0 bg-cover bg-center blur-3xl opacity-40 scale-105"
    style={`background-image: url('${albumArtUrl}')`}
  ></div>
  <!-- Gradient Overlay -->
  <div
    class="absolute inset-0 bg-gradient-to-b from-surface-50/80 via-surface-50/95 to-surface-50"
  ></div>
</div>

<div class="relative z-10 w-full min-h-screen pb-20">
  <div class="max-w-[1700px] mx-auto px-4 pt-6 md:px-12 md:pt-20">
    <div
      class="grid items-start gap-8 lg:[grid-template-columns:500px_1fr] lg:gap-16 xl:[grid-template-columns:600px_1fr]"
    >
      <!-- Left Column: Hero (Fixed-ish feel) -->
      <div class="flex flex-col gap-6 lg:sticky lg:top-20 lg:gap-8">
        <!-- Artwork -->
        <div
          class="group relative mx-auto aspect-square w-full max-w-[420px] overflow-hidden rounded-2xl shadow-2xl transition-transform duration-500 hover:scale-105 lg:max-w-none lg:rounded-sm"
        >
          <img
            src={albumArtUrl}
            alt={data.album}
            class="w-full h-full object-cover"
          />

          <!-- Hover Controls -->
          <div
            class="absolute inset-0 flex items-end justify-center gap-3 bg-gradient-to-t from-black/85 via-black/15 to-transparent p-4 opacity-100 transition-opacity lg:items-center lg:bg-black/35 lg:p-0 lg:opacity-0 group-hover:opacity-100"
          >
            <IconButton
              variant="primary"
              title="Play Album"
              onClick={playAll}
              stopPropagation={true}
            >
              <svg class="h-6 w-6" fill="currentColor" viewBox="0 0 24 24"
                ><path d="M8 5v14l11-7z" /></svg
              >
            </IconButton>
            <IconButton
              variant="primary"
              title="Add to Queue"
              onClick={addAllToQueue}
              stopPropagation={true}
            >
              <svg class="h-6 w-6" fill="currentColor" viewBox="0 0 24 24"
                ><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg
              >
            </IconButton>
            <IconButton
              variant="primary"
              title="Download Album"
              onClick={handleDownload}
              stopPropagation={true}
            >
              <svg class="h-6 w-6" fill="currentColor" viewBox="0 0 24 24"
                ><path d="M5 20h14v-2H5v2zM19 9h-4V3H9v6H5l7 7 7-7z" /></svg
              >
            </IconButton>
          </div>
        </div>

        <!-- Album details -->
        <div class="space-y-4">
          <div>
            <div class="flex items-start gap-3">
              <h1
                class="min-w-0 text-3xl font-bold tracking-tight text-default leading-tight sm:text-4xl md:text-5xl"
              >
                {data.album}
              </h1>
              {#if data.albumMeta?.album_mbid || data.albumMeta?.mb_release_id}
                <IconButton
                  variant={data.albumMeta?.is_favorite ? "primary" : "outline"}
                  title={data.albumMeta?.is_favorite ? "Remove release favorite" : "Favorite release"}
                  onClick={toggleAlbumFavorite}
                  className={`shrink-0 ${
                    data.albumMeta?.is_favorite
                      ? "border-rose-500 bg-rose-500 text-white hover:bg-rose-400"
                      : "border-subtle bg-surface-2 text-default hover:bg-surface-3"
                  } ${favoritePending ? "opacity-70" : ""}`}
                >
                  <svg
                    class={`h-5 w-5 ${data.albumMeta?.is_favorite ? "fill-current" : "fill-none"}`}
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    stroke-width="1.8"
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      d="M12 21s-6.716-4.31-9.193-8.115C1.09 10.25 1.81 6.91 4.68 5.526c1.9-.916 4.154-.468 5.78 1.147L12 8.213l1.54-1.54c1.626-1.615 3.88-2.063 5.78-1.147 2.87 1.384 3.59 4.724 1.873 7.359C18.716 16.69 12 21 12 21z"
                    />
                  </svg>
                </IconButton>
              {/if}
            </div>
            <div class="mt-2 text-lg font-medium text-muted sm:text-xl md:text-2xl">
              {#if data.albumMeta?.artists && data.albumMeta.artists.length > 0}
                {#each data.albumMeta.artists as artist, i}
                  <button
                    class="hover:underline hover:text-default transition-colors"
                    on:click={() => goto(`/artist/${artist.mbid}`)}
                  >
                    {artist.name}
                  </button>
                  {#if i < data.albumMeta.artists.length - 1}
                    <span class="text-subtle"> & </span>
                  {/if}
                {/each}
              {:else}
                <button
                  class="hover:underline hover:text-default transition-colors"
                  on:click={() =>
                    goto(`/artist/${encodeURIComponent(data.artist)}`)}
                >
                  {data.artist}
                </button>
              {/if}
            </div>
            {#if data.albumMeta?.mb_release_id}
              <div class="mt-2 text-base font-medium text-muted">
                <a
                  class="underline underline-offset-4 hover:text-default transition-colors"
                  href={`/history?album_mbid=${encodeURIComponent(
                    data.albumMeta.mb_release_id,
                  )}&album_name=${encodeURIComponent(data.album)}`}
                >
                  {formatListens(data.albumMeta.listens)}
                </a>
              </div>
            {:else if data.albumMeta?.album_mbid}
              <div class="mt-2 text-base font-medium text-muted">
                <a
                  class="underline underline-offset-4 hover:text-default transition-colors"
                  href={`/history?album_mbid=${encodeURIComponent(
                    data.albumMeta.album_mbid,
                  )}&album_name=${encodeURIComponent(data.album)}`}
                >
                  {formatListens(data.albumMeta.listens)}
                </a>
              </div>
            {:else}
              <div class="mt-2 text-base font-medium text-muted">
                {formatListens(data.albumMeta?.listens)}
              </div>
            {/if}
          </div>

          <div class="space-y-2">
            <!-- Line 1: Year • Tracks • Duration • Peak -->
            <div
              class="flex flex-wrap items-center gap-3 text-sm text-subtle font-medium"
            >
              <span
                >{data.albumMeta?.year
                  ? data.albumMeta.year.substring(0, 4)
                  : "—"}</span
              >
              <span class="w-1 h-1 rounded-full bg-subtle"></span>
              <span>{data.tracks.length} tracks</span>
              <span class="w-1 h-1 rounded-full bg-subtle"></span>
              <span>{totalDuration()} min</span>

              {#if data.albumMeta?.peak_chart_position}
                <span class="w-1 h-1 rounded-full bg-subtle"></span>
                <span class="flex items-center gap-1 text-yellow-500">
                  <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 24 24"
                    ><path
                      d="M16 6l2.29 2.29-4.88 4.88-4-4L2 16.59 3.41 18l6-6 4 4 6.3-6.29L22 12V6z"
                    /></svg
                  >
                  Peak #{data.albumMeta.peak_chart_position}
                </span>
              {/if}
            </div>

            <!-- Line 2: Label (Truncated) -->
            {#if data.albumMeta?.label}
              <div
                class="text-sm text-subtle font-medium truncate max-w-full"
                title={data.albumMeta.label}
              >
                {data.albumMeta.label}
              </div>
            {/if}
          </div>

          <!-- Description / Liner Notes -->
          {#if data.albumMeta?.description}
            <div class="pt-4 border-t border-subtle">
              <div class="prose prose-sm max-w-none text-muted leading-relaxed">
                {#if isDescriptionExpanded}
                  <p class="whitespace-pre-line">
                    {data.albumMeta.description}
                  </p>
                  <button
                    class="text-default underline text-xs font-bold mt-2 hover:text-default/80"
                    on:click={() => (isDescriptionExpanded = false)}
                    >Read less</button
                  >
                {:else}
                  <p class="line-clamp-3 whitespace-pre-line">
                    {data.albumMeta.description}
                  </p>
                  {#if data.albumMeta.description.length > 200}
                    <button
                      class="text-default underline text-xs font-bold mt-1 hover:text-default/80"
                      on:click={() => (isDescriptionExpanded = true)}
                      >Read more</button
                    >
                  {/if}
                {/if}
              </div>
            </div>
          {/if}

          <!-- External Links -->
          <div class="flex flex-wrap gap-2 pt-2">
            {#each getExternalLinks() as link}
              {@const icon = getLinkIcon(link.type)}
              <a
                href={link.url}
                target="_blank"
                class="px-3 py-1.5 rounded-full bg-surface-2 hover:bg-surface-3 text-xs font-medium text-muted transition-colors flex items-center gap-2 capitalize"
                title={link.type.replace(/_/g, " ")}
              >
                {#if icon}
                  <img
                    src={icon.src}
                    alt={icon.alt}
                    class={`w-4 h-4 opacity-70 ${icon.invert ? "invert" : ""}`}
                  />
                {:else}
                  <!-- Generic Link Icon -->
                  <svg
                    class="h-4 w-4 opacity-70"
                    fill="currentColor"
                    viewBox="0 0 24 24"
                    ><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z" /></svg
                  >
                {/if}
                <span class="hidden group-hover:block"
                  >{link.type.replace(/_/g, " ")}</span
                >
              </a>
            {/each}
          </div>
        </div>
      </div>

      <!-- Right Column: Tracklist -->
      <div class="flex-1 max-w-3xl pb-20 pt-2 lg:pt-4">
        {#if data.tracks.length === 0}
          <div
            class="p-10 text-center text-muted bg-surface-2 rounded-xl border border-subtle"
          >
            No tracks found for this album.
          </div>
        {:else}
          <div class="space-y-8">
            {#each groupedTracks as group}
              <div class="space-y-2">
                {#if groupedTracks.length > 1}
                  <div
                    class="sticky z-20 -mx-2 mb-4 flex items-center justify-between border-b border-subtle bg-surface-50/75 px-3 py-3 backdrop-blur-md top-[64px] sm:-mx-4 sm:px-4 md:mx-0 md:rounded-t-lg md:top-[80px]"
                  >
                    <div class="flex items-center gap-3">
                      <img
                        src="/assets/logo-disk.svg"
                        alt="Disc"
                        class="w-4 h-4 opacity-50 filter grayscale invert dark:invert-0"
                      />
                      <span class="font-bold text-sm tracking-wide text-default"
                        >DISC {group.disc}</span
                      >
                    </div>
                    <button
                      class="text-xs font-medium text-muted hover:text-default transition-colors"
                      on:click={() => playDisc(group.tracks)}
                    >
                      Play Disc
                    </button>
                  </div>
                {/if}

                <div class="space-y-1">
                  {#each group.tracks as track, idx}
                    <TrackCard
                      {track}
                      artists={track.artists}
                      artist={{ name: track.artist || data.artist }}
                      showIndex={true}
                      index={track.track_no}
                      showArtwork={false}
                      showAlbum={false}
                      showArtist={track.artist && track.artist !== data.artist}
                      showYear={false}
                      showTechDetails={true}
                      onPlay={() => playTrack(track)}
                      onQueue={() => addToQueue([track])}
                      onAddToPlaylist={() => openPlaylistModal(track.id)}
                    />
                  {/each}
                </div>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    </div>
  </div>
</div>

<AddToPlaylistModal
  bind:visible={showPlaylistModal}
  trackIds={selectedTrackIds}
  on:close={() => {
    selectedTrackIds = [];
  }}
/>
