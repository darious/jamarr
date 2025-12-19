<script lang="ts">
  import type { Album } from '$api';
  import { goto } from '$app/navigation';
  import { setQueue } from '$stores/player';
  import { fetchTracks } from '$api';

  export let data: { albums: Album[] };
  let search = '';
  let busyAlbum: string | null = null;

  const filtered = () =>
    data.albums.filter((a) =>
      `${a.album} ${a.artist_name}`.toLowerCase().includes(search.trim().toLowerCase())
    );

  async function quickPlay(album: Album) {
    busyAlbum = `${album.artist_name}-${album.album}`;
    try {
      const tracks = await fetchTracks({ album: album.album, artist: album.artist_name });
      if (tracks.length) {
        await setQueue(tracks, 0);
      } else {
        goto(`/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`);
      }
    } finally {
      busyAlbum = null;
    }
  }
</script>

<section class="mx-auto flex w-full max-w-[1700px] flex-col gap-6 px-8 py-10">
  <div class="section-head">
    <div>
      <p class="text-sm uppercase tracking-wide text-white/60">Browse</p>
      <h1 class="text-2xl font-semibold">Albums</h1>
    </div>
    <input
      class="input input-lg w-72 border border-white/10 bg-white/5"
      placeholder="Search albums"
      bind:value={search}
    />
  </div>

  <div class="grid gap-5 [grid-template-columns:repeat(auto-fill,minmax(240px,1fr))]">
    {#each filtered() as album}
      <article class="grid-card flex flex-col gap-3">
        <div class="relative aspect-square">
          <img
            src={album.art_id ? `/art/${album.art_id}` : '/assets/logo.png'}
            alt={album.album}
            class="h-full w-full rounded-2xl object-cover"
          />
          {#if album.is_hires}
            <img src="/assets/logo-hires.png" class="absolute right-3 top-3 h-10 w-10" alt="Hi-res" />
          {/if}
        </div>
        <div class="space-y-1">
          <p class="text-lg font-semibold truncate">{album.album}</p>
          <p class="text-sm text-white/60 truncate">{album.artist_name}</p>
          <p class="text-xs text-white/60">
            {album.year ? album.year.substring(0, 4) : '—'} • {album.track_count || 0} tracks
          </p>
        </div>
        <div class="mt-auto flex gap-2">
          <button class="btn btn-primary btn-sm flex-1" on:click={() => quickPlay(album)} disabled={busyAlbum === `${album.artist_name}-${album.album}`}>
            {busyAlbum === `${album.artist_name}-${album.album}` ? 'Loading…' : 'Play'}
          </button>
          <button
            class="btn btn-ghost btn-sm"
            on:click={() => goto(`/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`)}
          >
            Details
          </button>
        </div>
      </article>
    {/each}
  </div>
</section>
