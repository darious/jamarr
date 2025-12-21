<script lang="ts">
  import type { Album, Track } from "$api";
  import { setQueue, addToQueue } from "$stores/player";
  import { goto } from "$app/navigation";

  export let data: {
    artist: string;
    album: string;
    tracks: Track[];
    albumMeta?: Album;
  };

  const getAlbumArtUrl = () => {
    if (data.albumMeta?.art_sha1) return `/art/file/${data.albumMeta.art_sha1}`;
    if (data.albumMeta?.art_id) return `/art/${data.albumMeta.art_id}`;
    const withArt = data.tracks.find((t) => t.art_sha1 || t.art_id);
    if (withArt?.art_sha1) return `/art/file/${withArt.art_sha1}`;
    return withArt?.art_id ? `/art/${withArt.art_id}` : "/assets/logo.png";
  };

  const getMusicBrainzUrl = () => {
    if (data.albumMeta?.musicbrainz_url) return data.albumMeta.musicbrainz_url;
    const track = data.tracks?.[0];
    const mbBase = "http://musicbrainz.org";
    if (track?.mb_release_id) return `${mbBase}/release/${track.mb_release_id}`;
    if (track?.mb_release_group_id) return `${mbBase}/release-group/${track.mb_release_group_id}`;
    return null;
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

  function addAllToQueue() {
    if (data.tracks?.length) {
      addToQueue(data.tracks);
    }
  }

  function playTrack(track: Track) {
    // Find index in the FULL list to ensure playback order is preserved across discs
    // But we probably want to play from this track onwards?
    // The current implementation of setQueue takes the full list and an index.
    // So we just need to find the index of this track in data.tracks
    const idx = data.tracks.findIndex((t) => t.id === track.id);
    if (idx !== -1) {
      void setQueue(data.tracks, idx);
    }
  }
</script>

<div class="fixed inset-0 z-0 overflow-hidden pointer-events-none">
  <div
    class="absolute inset-0 bg-cover bg-center blur-3xl opacity-30 scale-110"
    style={`background-image: url('${getAlbumArtUrl()}')`}
  ></div>
  <div
    class="absolute inset-0 bg-gradient-to-b from-surface-900/50 via-surface-900/80 to-surface-900"
  ></div>
</div>

<section
  class="relative z-10 mx-auto flex w-full max-w-[1700px] flex-col gap-10 px-8 py-10"
>
  <div class="grid gap-8 md:grid-cols-[300px,1fr] items-end">
    <div
      class="relative aspect-square w-full max-w-[300px] group rounded-2xl overflow-hidden shadow-2xl"
    >
      <img
        class="h-full w-full object-cover"
        src={getAlbumArtUrl()}
        alt={data.album}
      />

      <!-- Overlay Controls -->
      <div
        class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-4 backdrop-blur-sm"
      >
        <button
          class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-lg scale-90 hover:scale-100 transition-transform"
          title="Play Album"
          on:click={playAll}
        >
          <svg class="h-8 w-8" fill="currentColor" viewBox="0 0 24 24"
            ><path d="M8 5v14l11-7z" /></svg
          >
        </button>
        <button
          class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-lg scale-90 hover:scale-100 transition-transform"
          title="Add to Queue"
          on:click={addAllToQueue}
        >
          <svg class="h-8 w-8" fill="currentColor" viewBox="0 0 24 24"
            ><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg
          >
        </button>
      </div>

      {#if data.albumMeta?.is_hires}
        <img
          src="/assets/logo-hires.png"
          alt="Hi-res"
          class="absolute left-3 bottom-3 h-8 w-8 opacity-90"
        />
      {/if}
    </div>

    <div class="space-y-4 pb-2">
      <div class="flex items-center gap-3">
        <p class="pill w-max bg-white/10 text-white/70 backdrop-blur-md">
          Album
        </p>
        {#if getMusicBrainzUrl()}
          <a
            class="pill hover:bg-white/15"
            target="_blank"
            href={getMusicBrainzUrl()}
          >
            <img
              src="/assets/logo-musicbrainz.svg"
              alt="MusicBrainz"
              class="h-4 w-4"
            /> MusicBrainz
          </a>
        {/if}
      </div>

      <h1 class="text-4xl md:text-6xl font-bold tracking-tight">
        {data.album}
      </h1>
      <div class="flex items-center gap-2 text-xl">
        <button
          class="font-medium hover:underline"
          on:click={() => goto(`/artist/${encodeURIComponent(data.artist)}`)}
        >
          {data.artist}
        </button>
        <span class="text-white/40">•</span>
        <span class="text-white/60"
          >{data.albumMeta?.year
            ? data.albumMeta.year.substring(0, 4)
            : "—"}</span
        >
        <span class="text-white/40">•</span>
        <span class="text-white/60"
          >{data.tracks.length} tracks, {totalDuration()} min</span
        >
      </div>
    </div>
  </div>

  <div class="glass-panel mt-4">
    {#if data.tracks.length === 0}
      <p class="p-6 text-white/60">No tracks found.</p>
    {:else}
      {#each groupedTracks as group}
        {#if groupedTracks.length > 1}
          <div
            class="px-4 py-3 bg-white/5 border-b border-white/5 flex items-center gap-2"
          >
            <img
              src="/assets/logo-disk.svg"
              alt="Disc"
              class="h-4 w-4 opacity-50"
            />
            <span class="text-sm font-semibold text-white/70"
              >Disc {group.disc}</span
            >
          </div>
        {/if}

        <div class="divide-y divide-white/5">
          {#each group.tracks as track, idx}
            <button
              class="w-full group flex items-center gap-4 px-4 py-3 hover:bg-white/5 transition-colors text-left"
              on:dblclick={() => playTrack(track)}
            >
              <div class="w-8 text-center text-xs text-white/50">
                {track.track_no}
              </div>

              <div
                class="h-12 w-12 flex-shrink-0 rounded bg-white/10 overflow-hidden relative"
              >
                <img
                  src={track.art_sha1
                    ? `/art/file/${track.art_sha1}`
                    : track.art_id
                      ? `/art/${track.art_id}`
                      : "/assets/logo.png"}
                  alt="Art"
                  class="h-full w-full object-cover"
                  on:error={(e) => {
                    const img = e.currentTarget;
                    if (img instanceof HTMLImageElement)
                      img.src = "/assets/logo.png";
                  }}
                />
                <div
                  class="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <button
                    class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-sm hover:scale-110 transition-transform"
                    on:click|stopPropagation={() => playTrack(track)}
                  >
                    <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24"
                      ><path d="M8 5v14l11-7z" /></svg
                    >
                  </button>
                </div>
              </div>

              <div class="flex-1 min-w-0">
                <p
                  class="truncate text-sm font-semibold text-white/90 group-hover:text-white"
                >
                  {track.title}
                </p>
                <div
                  class="flex items-center gap-2 text-xs text-white/50 mt-0.5"
                >
                  <span>{track.artist}</span>
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
                <button
                  class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-xs opacity-0 group-hover:opacity-100 transition-opacity"
                  title="Add to Queue"
                  on:click|stopPropagation={() => addToQueue([track])}
                >
                  <svg class="h-4 w-4" fill="currentColor" viewBox="0 0 24 24"
                    ><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg
                  >
                </button>
                <div
                  class="w-14 text-right text-xs text-white/60 font-medium tabular-nums"
                >
                  {formatDuration(track.duration_seconds)}
                </div>
              </div>
            </button>
          {/each}
        </div>
      {/each}
    {/if}
  </div>
</section>
