<script lang="ts">
  import type { Album, Track } from "$api";
  import { setQueue, addToQueue } from "$stores/player";
  import { goto } from "$app/navigation";
  import AddToPlaylistModal from "$components/AddToPlaylistModal.svelte";
  import IconButton from "$components/IconButton.svelte";
  import TrackCard from "$components/TrackCard.svelte";

  let showPlaylistModal = false;
  let selectedTrackIds: number[] = [];
  let isDescriptionExpanded = false;

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

  // Reactive album art URL - recalculates when data changes
  $: albumArtUrl = (() => {
    if (data.albumMeta?.art_sha1) return `/art/file/${data.albumMeta.art_sha1}`;
    const withArt = data.tracks.find((t) => t.art_sha1);
    if (withArt?.art_sha1) return `/art/file/${withArt.art_sha1}`;
    return "/assets/default-album-placeholder.svg";
  })();

  const getMusicBrainzUrl = () => {
    if (data.albumMeta?.musicbrainz_url) return data.albumMeta.musicbrainz_url;
    const track = data.tracks?.[0];
    const mbBase = "http://musicbrainz.org";
    if (track?.mb_release_id) return `${mbBase}/release/${track.mb_release_id}`;
    if (track?.mb_release_group_id)
      return `${mbBase}/release-group/${track.mb_release_group_id}`;
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
    class="absolute inset-0 bg-gradient-to-b from-surface-1/80 via-surface-1/95 to-surface-1"
  ></div>
</div>

<div class="relative z-10 w-full min-h-screen pb-20">
  <div class="max-w-[1700px] mx-auto px-6 md:px-12 pt-12 md:pt-20">
    <div
      class="grid lg:grid-cols-[500px,1fr] xl:grid-cols-[600px,1fr] gap-16 items-start"
    >
      <!-- Left Column: Hero (Fixed-ish feel) -->
      <div class="flex flex-col gap-8 sticky top-20">
        <!-- Artwork -->
        <div
          class="w-full aspect-square rounded shadow-2xl overflow-hidden relative group transition-transform duration-500 hover:scale-105"
        >
          <img
            src={albumArtUrl}
            alt={data.album}
            class="w-full h-full object-cover"
          />

          <!-- Hover Controls -->
          <div
            class="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-4"
          >
            <IconButton variant="primary" title="Play Album" onClick={playAll}>
              <svg class="h-6 w-6" fill="currentColor" viewBox="0 0 24 24"
                ><path d="M8 5v14l11-7z" /></svg
              >
            </IconButton>
            <IconButton
              variant="primary"
              title="Add to Queue"
              onClick={addAllToQueue}
            >
              <svg class="h-6 w-6" fill="currentColor" viewBox="0 0 24 24"
                ><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg
              >
            </IconButton>
          </div>
        </div>

        <!-- Album details -->
        <div class="space-y-4">
          <div>
            <h1
              class="text-4xl md:text-5xl font-bold tracking-tight text-default leading-tight"
            >
              {data.album}
            </h1>
            <div class="mt-2 text-2xl font-medium text-muted">
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
      <div class="flex-1 pt-4 pb-20 max-w-3xl">
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
                    class="flex items-center justify-between px-4 pb-2 border-b border-subtle mb-4 sticky top-[80px] z-20 backdrop-blur-md bg-surface-1/60 py-3 -mx-4 md:mx-0 md:rounded-t-lg"
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
/>
