<script lang="ts">
  import type { Album } from "$api";
  import { goto } from "$app/navigation";
  import { setQueue } from "$stores/player";
  import { fetchTracks } from "$api";

  export let data: { albums: Album[] };
  let search = "";
  let busyAlbum: string | null = null;

  const filtered = () =>
    data.albums.filter((a) =>
      `${a.album} ${a.artist_name}`
        .toLowerCase()
        .includes(search.trim().toLowerCase()),
    );

  async function quickPlay(album: Album) {
    busyAlbum = `${album.artist_name}-${album.album}`;
    try {
      const tracks = await fetchTracks({
        album: album.album,
        artist: album.artist_name,
      });
      if (tracks.length) {
        await setQueue(tracks, 0);
      } else {
        goto(
          `/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`,
        );
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

  <div
    class="grid gap-5 [grid-template-columns:repeat(auto-fill,minmax(240px,1fr))]"
  >
    {#each filtered() as album}
      <article class="grid-card flex flex-col gap-3">
        <button
          class="group relative aspect-square"
          on:click={() =>
            goto(
              `/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`,
            )}
        >
          <img
            src={album.art_id ? `/art/${album.art_id}` : "/assets/logo.png"}
            alt={album.album}
            class="h-full w-full rounded-2xl object-cover transition-transform duration-200 group-hover:scale-[1.03]"
          />
          {#if album.is_hires}
            <img
              src="/assets/logo-hires.png"
              class="absolute right-3 top-3 h-10 w-10"
              alt="Hi-res"
            />
          {/if}

          <div
            class="absolute right-2 top-2 flex gap-2 opacity-0 transition-opacity group-hover:opacity-100"
          >
            <button
              class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-sm hover:scale-110 transition-transform"
              title="Play"
              on:click|stopPropagation={() => quickPlay(album)}
            >
              {#if busyAlbum === `${album.artist_name}-${album.album}`}
                <span class="loading loading-spinner loading-xs"></span>
              {:else}
                <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24"
                  ><path d="M8 5v14l11-7z" /></svg
                >
              {/if}
            </button>
            <button
              class="btn btn-circle bg-black/60 hover:bg-black/80 text-white border-none btn-sm hover:scale-110 transition-transform"
              title="Details"
              on:click|stopPropagation={() =>
                goto(
                  `/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`,
                )}
            >
              <svg
                class="h-5 w-5"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                ><path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                /></svg
              >
            </button>
          </div>
        </button>
        <div class="space-y-1">
          <a
            href={`/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`}
            class="text-lg font-semibold truncate hover:underline cursor-pointer block"
          >
            {album.album}
          </a>
          <a
            href={`/artist/${encodeURIComponent(album.artist_name)}`}
            class="text-sm text-white/60 truncate hover:text-white cursor-pointer block"
          >
            {album.artist_name}
          </a>
          <p class="text-xs text-white/60">
            {album.year ? album.year.substring(0, 4) : "—"} • {album.track_count ||
              0} tracks
          </p>
        </div>
      </article>
    {/each}
  </div>
</section>
