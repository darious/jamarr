<script lang="ts">
  import type { Album, Artist, Track } from '$api';
  import { fetchTracks, refreshArtistMetadata } from '$api';
  import { goto } from '$app/navigation';
  import { addToQueue, loadQueueFromServer, setQueue } from '$stores/player';
  import { browser } from '$app/environment';

  export let data: { name: string; canonicalName: string; artist?: Artist; albums: Album[]; similarArtists: { name: string; image_url?: string | null }[] };

  let artist: Artist | undefined = data.artist;
  let tracks: Track[] = [];
  let loadingTracks = true;
  let refreshing = false;
  let message = '';
  let lastKey = '';

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
        console.warn('Queue sync failed', e);
      }
      tracks = await fetchTracks({ artist: data.canonicalName || data.name });
    } catch (e) {
      console.error('Track load failed', e);
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
    if (!seconds) return '—';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60)
      .toString()
      .padStart(2, '0');
    return `${mins}:${secs}`;
  };

  const topTracks = () => {
    const fromMeta = artist?.top_tracks || [];
    return fromMeta.slice(0, 8).map((t) => {
      const local = tracks.find((lt) => lt.title.toLowerCase() === (t.name || '').toLowerCase());
      return local || {
        id: -1,
        title: t.name,
        album: t.album || '',
        artist: t.artist || artist?.name || '',
        duration_seconds: t.duration_ms ? Math.round(t.duration_ms / 1000) : null
      };
    });
  };

  async function refreshMeta() {
    refreshing = true;
    message = 'Requesting fresh metadata...';
    try {
      await refreshArtistMetadata(data.canonicalName || data.name);
      message = 'Refresh started. Check back in a few seconds.';
    } catch (e) {
      message = 'Failed to refresh metadata.';
    } finally {
      refreshing = false;
    }
  }

  async function playAlbum(album: Album) {
    const albumTracks = tracks.filter((t) => t.album === album.album);
    if (albumTracks.length) {
      await setQueue(albumTracks, 0);
    } else {
      goto(`/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`);
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
      await addToQueue(track);
    }
  }
</script>

<section class="mx-auto flex w-full max-w-[1700px] flex-col gap-10 px-8 py-10">
  <div class="glass-panel overflow-hidden p-0 shadow-2xl">
    <div
      class="hero-gradient relative h-56 w-full bg-cover bg-center"
      style={`background-image:url('${artist?.image_url || '/assets/default-artist.svg'}')`}
    >
      <div class="absolute inset-0 bg-gradient-to-t from-black via-black/30 to-transparent"></div>
      <div class="absolute bottom-0 left-0 right-0 px-8 pb-8">
        <p class="pill mb-2 bg-white/10 text-white/80">Artist</p>
        <h1 class="text-4xl font-semibold md:text-5xl">{artist?.name ?? data.name}</h1>
        <div class="mt-3 flex flex-wrap gap-2">
          {#if artist?.spotify_url}
            <a class="pill hover:bg-white/15" target="_blank" href={artist.spotify_url}>
              <img src="/assets/logo-spotify.svg" alt="Spotify" class="h-4 w-4" /> Spotify
            </a>
          {/if}
          {#if artist?.wikipedia_url}
            <a class="pill hover:bg-white/15" target="_blank" href={artist.wikipedia_url}>
              <img src="/assets/logo-wikipedia.svg" alt="Wikipedia" class="h-4 w-4" /> Wiki
            </a>
          {/if}
          {#if artist?.musicbrainz_url}
            <a class="pill hover:bg-white/15" target="_blank" href={artist.musicbrainz_url}>
              <img src="/assets/logo-musicbrainz.svg" alt="MusicBrainz" class="h-4 w-4" /> MusicBrainz
            </a>
          {/if}
          {#if artist?.qobuz_url}
            <a class="pill hover:bg-white/15" target="_blank" href={artist.qobuz_url}>
              <img src="/assets/logo-qobuz.png" alt="Qobuz" class="h-4 w-4" /> Qobuz
            </a>
          {/if}
        </div>
      </div>
    </div>
    <div class="grid gap-8 p-8 md:grid-cols-3">
      <div class="md:col-span-2 space-y-4 text-white/80 leading-relaxed">
        <div class="flex items-center justify-between">
          <h2 class="text-xl font-semibold">About</h2>
          <button class="btn btn-ghost btn-sm" on:click={refreshMeta} disabled={refreshing}>
            {refreshing ? 'Refreshing…' : 'Refresh metadata'}
          </button>
        </div>
        <p class="whitespace-pre-line">{artist?.bio || 'No biography available yet.'}</p>
        {#if message}
          <p class="text-sm text-white/60">{message}</p>
        {/if}
      </div>
      <div class="space-y-3 rounded-2xl bg-white/5 p-4 text-sm text-white/70">
        <div class="flex items-center justify-between">
          <span>Albums</span>
          <span class="pill bg-white/10 text-white/80">{data.albums.length}</span>
        </div>
        <div class="flex items-center justify-between">
          <span>Tracks cached</span>
          <span class="pill bg-white/10 text-white/80">{loadingTracks ? 'Loading…' : tracks.length}</span>
        </div>
      </div>
    </div>
  </div>

  <div class="grid gap-8 md:grid-cols-3">
    <div class="md:col-span-2 space-y-4">
      <div class="section-head">
        <div>
          <p class="text-sm uppercase tracking-wide text-white/60">Essential</p>
          <h3 class="text-xl font-semibold">Top tracks</h3>
        </div>
        <a class="btn btn-ghost btn-sm" href={`/album/${encodeURIComponent(data.name)}`}>View albums</a>
      </div>
      <div class="space-y-2">
        {#if loadingTracks}
          <div class="glass-panel h-24 animate-pulse"></div>
        {:else if topTracks().length === 0}
          <p class="text-white/60">No tracks yet.</p>
        {:else}
          {#each topTracks() as track}
            <div class="glass-panel flex items-center justify-between gap-3 px-4 py-3">
              <div class="min-w-0">
                <p class="truncate text-sm font-semibold">{track.title}</p>
                <p class="text-xs text-white/60">{track.album}</p>
              </div>
              <div class="flex items-center gap-3 text-xs text-white/60">
                <span>{formatDuration(track.duration_seconds ?? 0)}</span>
                {#if track.id && track.id > 0}
                  <div class="flex items-center gap-2">
                    <button class="btn btn-primary btn-xs" title="Play" on:click={() => playTrackById(track.id)}>▶</button>
                    <button class="btn btn-ghost btn-xs" title="Add to queue" on:click={() => addTrackToQueue(track.id)}>＋</button>
                  </div>
                {/if}
              </div>
            </div>
          {/each}
        {/if}
      </div>
    </div>

    <div class="space-y-4">
      <div class="section-head">
        <div>
          <p class="text-sm uppercase tracking-wide text-white/60">Discovery</p>
          <h3 class="text-xl font-semibold">Similar artists</h3>
        </div>
      </div>
      <div class="grid gap-3">
        {#if data.similarArtists?.length}
          {#each data.similarArtists.slice(0, 8) as sim}
            <button
              class="grid-card flex items-center gap-3 text-left"
              on:click={() => goto(`/artist/${encodeURIComponent(sim.name)}`)}
            >
              {#if sim.image_url}
                <img src={sim.image_url} alt={sim.name} class="h-10 w-10 rounded-full object-cover" />
              {:else}
                <div class="h-10 w-10 rounded-full bg-white/10 text-center text-sm font-semibold leading-10">
                  {sim.name.charAt(0).toUpperCase()}
                </div>
              {/if}
              <div class="truncate text-sm font-semibold">{sim.name}</div>
            </button>
          {/each}
        {:else}
          <p class="text-white/60">No similar artists recorded.</p>
        {/if}
      </div>
    </div>
  </div>

  <div class="section-head">
    <div>
      <p class="text-sm uppercase tracking-wide text-white/60">Library</p>
      <h3 class="text-xl font-semibold">Albums</h3>
    </div>
  </div>
  <div class="grid gap-5 [grid-template-columns:repeat(auto-fill,minmax(240px,1fr))]">
    {#each data.albums as album}
      <article class="grid-card flex flex-col gap-3">
        <button
          class="relative aspect-square overflow-hidden rounded-2xl"
          on:click={() => goto(`/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`)}
        >
          <img
            src={album.art_id ? `/art/${album.art_id}` : '/assets/logo.png'}
            alt={album.album}
            class="h-full w-full object-cover transition-transform duration-200 hover:scale-[1.03]"
          />
          {#if album.is_hires}
            <img src="/assets/logo-hires.png" class="absolute right-3 top-3 h-10 w-10" alt="Hi-res" />
          {/if}
        </button>
        <div class="space-y-1">
          <p class="text-lg font-semibold">{album.album}</p>
          <p class="text-sm text-white/60">{album.artist_name}</p>
          <p class="text-xs text-white/60">
            {album.year ? album.year.substring(0, 4) : '—'} • {album.track_count || 0} tracks
          </p>
        </div>
        <div class="mt-auto flex gap-2">
          <button class="btn btn-primary btn-sm flex-1" on:click={() => playAlbum(album)}>Play</button>
        </div>
      </article>
    {/each}
  </div>
</section>
