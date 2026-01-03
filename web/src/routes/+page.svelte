<script lang="ts">
    import type { Album, Artist } from "../lib/api";
    import { fetchTracks } from "../lib/api";
    import { setQueue, addToQueue } from "../lib/stores/player";
    import IconButton from "$components/IconButton.svelte";

    export let data: {
        newReleases: Album[];
        recentlyAddedAlbums: Album[];
        recentlyPlayedAlbums: Album[];
        recentlyPlayedArtists: Artist[];
        discoverArtists: Artist[];
    };

    const {
        newReleases,
        recentlyAddedAlbums,
        recentlyPlayedAlbums,
        recentlyPlayedArtists,
        discoverArtists,
    } = data;

    async function playAlbum(album: Album) {
        try {
            const tracks = await fetchTracks({
                album: album.album,
                artist: album.artist_name,
            });
            if (tracks.length > 0) {
                void setQueue(tracks, 0);
            }
        } catch (e) {
            console.error("Failed to play album", e);
        }
    }

    async function queueAlbum(album: Album) {
        try {
            const tracks = await fetchTracks({
                album: album.album,
                artist: album.artist_name,
            });
            if (tracks.length > 0) {
                addToQueue(tracks);
            }
        } catch (e) {
            console.error("Failed to queue album", e);
        }
    }

    function handleScroll(e: WheelEvent) {
        // Allow vertical scrolling if Shift key is pressed or if it's a touchpad vertical scroll?
        // But for mouse wheel, we want to map Y to X.
        if (e.deltaY !== 0) {
            e.preventDefault();
            const container = e.currentTarget as HTMLElement;
            container.scrollLeft += e.deltaY;
        }
    }
</script>

<section
    class="mx-auto flex w-full max-w-[1700px] flex-col gap-12 px-8 py-10 pb-32"
>
    <!-- New Releases -->
    {#if newReleases.length > 0}
        <div class="space-y-4">
            <div class="flex items-center justify-between">
                <h2 class="text-2xl font-semibold text-default">
                    New Releases
                </h2>
            </div>
            <div
                class="flex gap-6 overflow-x-auto py-6 -mx-8 px-8 scroll-pl-8 snap-x snap-mandatory flex-nowrap scrollbar-thin"
                on:wheel={handleScroll}
            >
                {#each newReleases as album}
                    <div
                        class="group relative min-w-[280px] w-[280px] snap-start"
                    >
                        <div
                            class="relative aspect-square w-full overflow-hidden rounded-md bg-surface-2 shadow-lg transition-transform duration-300 group-hover:scale-105"
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
                            <a
                                href={album.mbid || album.album_mbid
                                    ? `/album/${album.mbid || album.album_mbid}`
                                    : `/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`}
                                class="absolute inset-0 z-0"
                                aria-label="View Album"
                            ></a>
                            <div
                                class="absolute inset-0 opacity-0 transition-opacity group-hover:opacity-100 flex items-center justify-center gap-3 z-10 pointer-events-none"
                            >
                                <div
                                    class="pointer-events-auto flex items-center gap-3 text-white"
                                >
                                    <IconButton
                                        variant="primary"
                                        title="Play Album"
                                        onClick={() => playAlbum(album)}
                                        stopPropagation={true}
                                        className="shadow-lg transition-all"
                                    >
                                        <svg
                                            class="h-6 w-6"
                                            fill="currentColor"
                                            viewBox="0 0 24 24"
                                            ><path d="M8 5v14l11-7z" /></svg
                                        >
                                    </IconButton>
                                    <IconButton
                                        variant="primary"
                                        title="Add to Queue"
                                        onClick={() => queueAlbum(album)}
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
                            {#if album.is_hires}
                                <img
                                    src="/assets/logo-hires.png"
                                    alt="Hi-Res"
                                    class="absolute right-2 bottom-2 h-8 w-8 opacity-90 pointer-events-none"
                                />
                            {/if}
                        </div>
                        <div class="mt-3">
                            <a
                                href={album.mbid || album.album_mbid
                                    ? `/album/${album.mbid || album.album_mbid}`
                                    : `/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`}
                                class="block font-medium leading-tight truncate hover:underline text-default"
                                title={album.album}>{album.album}</a
                            >
                            <a
                                href={album.artist_mbid
                                    ? `/artist/${album.artist_mbid}`
                                    : `/artist/${encodeURIComponent(album.artist_name)}`}
                                class="block text-sm text-muted truncate hover:underline"
                                title={album.artist_name}>{album.artist_name}</a
                            >
                            <p class="text-xs text-subtle mt-0.5">
                                {album.year || "Unknown Year"}
                            </p>
                        </div>
                    </div>
                {/each}
                <!-- Spacer for right padding -->
                <div class="min-w-[1px]"></div>
            </div>
        </div>
    {/if}

    <!-- Recently Added Albums -->
    {#if recentlyAddedAlbums.length > 0}
        <div class="space-y-4">
            <h2 class="text-2xl font-semibold text-default">
                Recently Added Albums
            </h2>
            <div
                class="flex gap-6 overflow-x-auto py-6 -mx-8 px-8 scroll-pl-8 snap-x snap-mandatory flex-nowrap scrollbar-thin"
                on:wheel={handleScroll}
            >
                {#each recentlyAddedAlbums as album}
                    <div
                        class="group relative min-w-[280px] w-[280px] snap-start"
                    >
                        <div
                            class="relative aspect-square w-full overflow-hidden rounded-md bg-surface-2 shadow-lg transition-transform duration-300 group-hover:scale-105"
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
                            <a
                                href={album.mbid || album.album_mbid
                                    ? `/album/${album.mbid || album.album_mbid}`
                                    : `/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`}
                                class="absolute inset-0 z-0"
                                aria-label="View Album"
                            ></a>
                            <div
                                class="absolute inset-0 opacity-0 transition-opacity group-hover:opacity-100 flex items-center justify-center gap-3 z-10 pointer-events-none"
                            >
                                <div
                                    class="pointer-events-auto flex items-center gap-3 text-white"
                                >
                                    <IconButton
                                        variant="primary"
                                        title="Play Album"
                                        onClick={() => playAlbum(album)}
                                        stopPropagation={true}
                                        className="shadow-lg transition-all"
                                    >
                                        <svg
                                            class="h-6 w-6"
                                            fill="currentColor"
                                            viewBox="0 0 24 24"
                                            ><path d="M8 5v14l11-7z" /></svg
                                        >
                                    </IconButton>
                                    <IconButton
                                        variant="primary"
                                        title="Add to Queue"
                                        onClick={() => queueAlbum(album)}
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
                            {#if album.is_hires}
                                <img
                                    src="/assets/logo-hires.png"
                                    alt="Hi-Res"
                                    class="absolute right-2 bottom-2 h-8 w-8 opacity-90 pointer-events-none"
                                />
                            {/if}
                        </div>
                        <div class="mt-3">
                            <a
                                href={album.mbid || album.album_mbid
                                    ? `/album/${album.mbid || album.album_mbid}`
                                    : `/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`}
                                class="block font-medium leading-tight truncate hover:underline text-default"
                                title={album.album}>{album.album}</a
                            >
                            <a
                                href={album.artist_mbid
                                    ? `/artist/${album.artist_mbid}`
                                    : `/artist/${encodeURIComponent(album.artist_name)}`}
                                class="block text-sm text-muted truncate hover:underline"
                                title={album.artist_name}>{album.artist_name}</a
                            >
                        </div>
                    </div>
                {/each}
                <div class="min-w-[1px]"></div>
            </div>
        </div>
    {/if}

    <!-- Recently Played Albums -->
    {#if recentlyPlayedAlbums.length > 0}
        <div class="space-y-4">
            <h2 class="text-2xl font-semibold text-default">
                Recently Played Albums
            </h2>
            <div
                class="flex gap-6 overflow-x-auto pb-6 -mx-8 px-8 scroll-pl-8 snap-x snap-mandatory flex-nowrap scrollbar-thin"
                on:wheel={handleScroll}
            >
                {#each recentlyPlayedAlbums as album}
                    <div
                        class="group relative min-w-[280px] w-[280px] snap-start"
                    >
                        <div
                            class="relative aspect-square w-full overflow-hidden rounded-md bg-surface-2 relative shadow-lg transition-all duration-300 hover:shadow-primary-500/20 group-hover:scale-105"
                        >
                            <img
                                src={album.art_sha1
                                    ? `/art/file/${album.art_sha1}`
                                    : album.art_id
                                      ? `/art/${album.art_id}`
                                      : "/assets/default-album-placeholder.svg"}
                                alt={album.album}
                                class="h-full w-full object-cover opacity-90 group-hover:opacity-100 transition-opacity"
                                loading="lazy"
                            />
                            <a
                                href={album.mbid || album.album_mbid
                                    ? `/album/${album.mbid || album.album_mbid}`
                                    : `/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`}
                                class="absolute inset-0 z-0"
                                aria-label="View Album"
                            ></a>
                            <div
                                class="absolute inset-0 opacity-0 transition-opacity group-hover:opacity-100 flex items-center justify-center gap-3 z-10 pointer-events-none"
                            >
                                <div
                                    class="pointer-events-auto flex items-center gap-3 text-white"
                                >
                                    <IconButton
                                        variant="primary"
                                        title="Play Album"
                                        onClick={() => playAlbum(album)}
                                        stopPropagation={true}
                                        className="shadow-lg transition-all"
                                    >
                                        <svg
                                            class="h-6 w-6"
                                            fill="currentColor"
                                            viewBox="0 0 24 24"
                                            ><path d="M8 5v14l11-7z" /></svg
                                        >
                                    </IconButton>
                                    <IconButton
                                        variant="primary"
                                        title="Add to Queue"
                                        onClick={() => queueAlbum(album)}
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
                            {#if album.is_hires}
                                <img
                                    src="/assets/logo-hires.png"
                                    alt="Hi-Res"
                                    class="absolute right-2 bottom-2 h-8 w-8 opacity-90 pointer-events-none"
                                />
                            {/if}
                        </div>
                        <div class="mt-3">
                            <a
                                href={album.mbid || album.album_mbid
                                    ? `/album/${album.mbid || album.album_mbid}`
                                    : `/album/${encodeURIComponent(album.artist_name)}/${encodeURIComponent(album.album)}`}
                                class="block font-medium leading-tight truncate hover:underline text-default"
                                title={album.album}>{album.album}</a
                            >
                            <a
                                href={album.artist_mbid
                                    ? `/artist/${album.artist_mbid}`
                                    : `/artist/${encodeURIComponent(album.artist_name)}`}
                                class="block text-sm text-muted truncate hover:underline"
                                title={album.artist_name}>{album.artist_name}</a
                            >
                        </div>
                    </div>
                {/each}
                <div class="min-w-[1px]"></div>
            </div>
        </div>
    {/if}

    <!-- Discover - Newly Added Artists -->
    {#if discoverArtists.length > 0}
        <div class="space-y-4">
            <h2 class="text-2xl font-semibold text-default">
                Newly Added Artists
            </h2>
            <div
                class="flex gap-6 overflow-x-auto py-6 -mx-8 px-8 scroll-pl-8 snap-x snap-mandatory flex-nowrap scrollbar-thin"
                on:wheel={handleScroll}
            >
                {#each discoverArtists as artist}
                    <a
                        href={artist.mbid
                            ? `/artist/${artist.mbid}`
                            : `/artist/${encodeURIComponent(artist.name)}`}
                        class="group relative min-w-[280px] w-[280px] snap-start flex flex-col items-center text-center"
                    >
                        <div
                            class="aspect-square w-full overflow-hidden rounded-full bg-surface-2 relative shadow-lg border border-subtle transition-transform duration-300 group-hover:scale-105"
                        >
                            <img
                                src={artist.art_sha1
                                    ? `/art/file/${artist.art_sha1}`
                                    : artist.art_id
                                      ? `/art/${artist.art_id}`
                                      : "/assets/default-artist-placeholder.svg"}
                                alt={artist.name}
                                class="h-full w-full object-cover"
                                loading="lazy"
                            />
                        </div>
                        <div class="mt-3">
                            <h3
                                class="font-medium leading-tight truncate w-full text-default"
                                title={artist.name}
                            >
                                {artist.name}
                            </h3>
                        </div>
                    </a>
                {/each}
                <div class="min-w-[1px]"></div>
            </div>
        </div>
    {/if}

    <!-- Recently Played Artists -->
    {#if recentlyPlayedArtists.length > 0}
        <div class="space-y-4">
            <h2 class="text-2xl font-semibold text-default">
                Recently Played Artists
            </h2>
            <div
                class="flex gap-6 overflow-x-auto py-6 -mx-8 px-8 scroll-pl-8 snap-x snap-mandatory flex-nowrap scrollbar-thin"
                on:wheel={handleScroll}
            >
                {#each recentlyPlayedArtists as artist}
                    <a
                        href={artist.mbid
                            ? `/artist/${artist.mbid}`
                            : `/artist/${encodeURIComponent(artist.name)}`}
                        class="group relative min-w-[280px] w-[280px] snap-start flex flex-col items-center text-center"
                    >
                        <div
                            class="aspect-square w-full overflow-hidden rounded-full bg-surface-2 relative shadow-lg border border-subtle transition-transform duration-300 group-hover:scale-105"
                        >
                            <img
                                src={artist.art_sha1
                                    ? `/art/file/${artist.art_sha1}`
                                    : artist.art_id
                                      ? `/art/${artist.art_id}`
                                      : "/assets/default-artist-placeholder.svg"}
                                alt={artist.name}
                                class="h-full w-full object-cover transition-all duration-500"
                                loading="lazy"
                            />
                        </div>
                        <div class="mt-3">
                            <h3
                                class="font-medium leading-tight truncate w-full text-default"
                                title={artist.name}
                            >
                                {artist.name}
                            </h3>
                        </div>
                    </a>
                {/each}
                <div class="min-w-[1px]"></div>
            </div>
        </div>
    {/if}
</section>
