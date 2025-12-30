<script lang="ts">
    import { goto } from "$app/navigation";
    import { onMount } from "svelte";
    import { fade, slide } from "svelte/transition";
    import AddToPlaylistModal from "$lib/components/AddToPlaylistModal.svelte";

    let query = "";
    let results: any = null;
    let timer: any;
    let inputElement: HTMLInputElement;
    let showResults = false;

    // Playlist Modal
    let showPlaylistModal = false;
    let selectedTrackIds: number[] = [];

    const openPlaylistModal = (trackId: number, e: MouseEvent) => {
        e.stopPropagation();
        selectedTrackIds = [trackId];
        showPlaylistModal = true;
    };

    interface SearchResponse {
        artists: { name: string; mbid: string; image_url?: string }[];
        albums: {
            title: string;
            artist: string;
            art_id?: number;
            art_sha1?: string;
        }[];
        tracks: {
            id: number;
            title: string;
            artist: string;
            album: string;
            duration_seconds: number;
            art_id?: number;
            art_sha1?: string;
        }[];
    }

    const handleInput = () => {
        clearTimeout(timer);
        if (query.length < 2) {
            results = null;
            showResults = false;
            return;
        }
        timer = setTimeout(async () => {
            try {
                const res = await fetch(
                    `/api/search?q=${encodeURIComponent(query)}`,
                );
                if (res.ok) {
                    results = await res.json();
                    showResults = true;
                }
            } catch (e) {
                console.error("Search failed", e);
            }
        }, 300);
    };

    const clearSearch = () => {
        query = "";
        results = null;
        showResults = false;
    };

    const handleBlur = (e: FocusEvent) => {
        // Allow click on result to register before closing
        setTimeout(() => {
            showResults = false;
        }, 200);
    };

    const handleFocus = () => {
        if (query.length >= 2 && results) {
            showResults = true;
        }
    };

    function navigateToArtist(name: string) {
        goto(`/artist/${encodeURIComponent(name)}`);
        clearSearch();
    }

    // Note: Album navigation depends on routes. Assuming /album/[artist]/[album] based on typical patterns or just /album/[name] if strictly name based.
    // Looking at file list earlier: web/src/routes/album/[album_id] or similar maybe?
    // User context implied album pages exist. "selecting anything... should take us to the artist, or album pages"
    // I will check generic album route later. validating simply goto for now.
    // Update: existing schema suggests albums are identified by name + artist often, but UI usually prefers IDs if available.
    // The API returns title/artist.
    // Let's assume a search query param or hash for now if exact route unknown, OR just /albums?filter=...
    // ACTUALLY, looking at `web/src/routes/album` dir in `list_dir` output earlier...
    // `web/src/routes/album` has children.
    // `web/src/routes/albums` has children.
    // I'll take a safe bet and just use /albums for now if I can't resolve specific album ID from search result (API only returned title/artist).
    // Wait, I should update API to return ID matching what the frontend expects for album links?
    // The DB `tracks` table has `album` string. There is no `albums` table with IDs.
    // So album routes likely use query params or path encoding of name.
    // Let's check `web/src/routes/album` content to be sure.

    function navigateToAlbum(album: string, artist: string) {
        // Encode components for URL
        goto(
            `/album/${encodeURIComponent(artist)}/${encodeURIComponent(album)}`,
        );
        clearSearch();
    }
</script>

<div class="relative w-full max-w-md mx-4 hidden md:block">
    <div class="relative flex items-center">
        <svg
            class="pointer-events-none absolute left-3 h-4 w-4 text-white/40"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
        >
            <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
        </svg>
        <input
            bind:this={inputElement}
            type="text"
            placeholder="Search..."
            class="w-full rounded-full border border-white/10 bg-white/5 py-1.5 pl-9 pr-3 text-sm text-white placeholder-white/40 focus:border-white/20 focus:bg-white/10 focus:outline-none"
            bind:value={query}
            on:input={handleInput}
            on:blur={handleBlur}
            on:focus={handleFocus}
        />
        {#if query}
            <button
                class="absolute right-3 text-white/40 hover:text-white"
                on:click={clearSearch}
            >
                <svg
                    class="h-4 w-4"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                    ><path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M6 18L18 6M6 6l12 12"
                    /></svg
                >
            </button>
        {/if}
    </div>

    {#if showResults && results}
        <div
            transition:fade={{ duration: 100 }}
            class="absolute left-0 mt-2 w-full origin-top rounded-xl border border-white/10 bg-[#121212] py-2 shadow-2xl backdrop-blur-3xl ring-1 ring-black/5"
        >
            {#if results.artists.length > 0}
                <div class="px-2 py-1">
                    <h3
                        class="px-2 text-xs font-semibold uppercase tracking-wider text-white/40"
                    >
                        Artists
                    </h3>
                    {#each results.artists as artist}
                        <button
                            class="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-white/10"
                            on:click={() => navigateToArtist(artist.name)}
                        >
                            {#if artist.image_url}
                                <img
                                    src={artist.image_url}
                                    class="h-8 w-8 rounded-full object-cover"
                                    alt=""
                                />
                            {:else}
                                <div
                                    class="h-8 w-8 rounded-full bg-white/10 flex items-center justify-center text-xs"
                                >
                                    ?
                                </div>
                            {/if}
                            <div
                                class="truncate text-sm font-medium text-white"
                            >
                                {artist.name}
                            </div>
                        </button>
                    {/each}
                </div>
            {/if}

            {#if results.albums.length > 0}
                <div class="px-2 py-1">
                    <h3
                        class="px-2 text-xs font-semibold uppercase tracking-wider text-white/40"
                    >
                        Albums
                    </h3>
                    {#each results.albums as album}
                        <button
                            class="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-white/10"
                            on:click={() =>
                                navigateToAlbum(album.title, album.artist)}
                        >
                            <div
                                class="h-8 w-8 rounded bg-white/10 flex items-center justify-center text-xs text-white/40 overflow-hidden"
                            >
                                {#if album.art_sha1 || album.art_id}
                                    <img
                                        src={album.art_sha1
                                            ? `/art/file/${album.art_sha1}`
                                            : `/art/${album.art_id}`}
                                        alt=""
                                        class="h-full w-full object-cover"
                                    />
                                {:else}
                                    <svg
                                        class="h-4 w-4"
                                        fill="none"
                                        stroke="currentColor"
                                        viewBox="0 0 24 24"
                                        ><path
                                            stroke-linecap="round"
                                            stroke-linejoin="round"
                                            stroke-width="2"
                                            d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"
                                        /></svg
                                    >
                                {/if}
                            </div>
                            <div class="overflow-hidden">
                                <div
                                    class="truncate text-sm font-medium text-white"
                                >
                                    {album.title}
                                </div>
                                <a
                                    href={`/artist/${encodeURIComponent(album.artist)}`}
                                    class="truncate text-xs text-white/60 hover:text-white hover:underline block"
                                    on:click|stopPropagation={clearSearch}
                                >
                                    {album.artist}
                                </a>
                            </div>
                        </button>
                    {/each}
                </div>
            {/if}

            {#if results.tracks.length > 0}
                <div class="px-2 py-1">
                    <h3
                        class="px-2 text-xs font-semibold uppercase tracking-wider text-white/40"
                    >
                        Tracks
                    </h3>
                    {#each results.tracks as track}
                        <div
                            role="button"
                            tabindex="0"
                            class="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-white/10 cursor-pointer group"
                            on:click={() =>
                                navigateToAlbum(track.album, track.artist)}
                            on:keydown={(e) =>
                                e.key === "Enter" &&
                                navigateToAlbum(track.album, track.artist)}
                        >
                            <div
                                class="h-8 w-8 rounded bg-white/10 flex items-center justify-center text-xs text-white/40 overflow-hidden"
                            >
                                {#if track.art_sha1 || track.art_id}
                                    <img
                                        src={track.art_sha1
                                            ? `/art/file/${track.art_sha1}`
                                            : `/art/${track.art_id}`}
                                        alt=""
                                        class="h-full w-full object-cover"
                                    />
                                {:else}
                                    <svg
                                        class="h-4 w-4"
                                        fill="none"
                                        stroke="currentColor"
                                        viewBox="0 0 24 24"
                                        ><path
                                            stroke-linecap="round"
                                            stroke-linejoin="round"
                                            stroke-width="2"
                                            d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"
                                        /></svg
                                    >
                                {/if}
                            </div>
                            <div class="overflow-hidden">
                                <div
                                    class="truncate text-sm font-medium text-white"
                                >
                                    {track.title}
                                </div>
                                <div
                                    class="truncate text-xs text-white/60 flex items-center gap-1"
                                >
                                    <a
                                        href={`/artist/${encodeURIComponent(track.artist)}`}
                                        class="hover:text-white hover:underline"
                                        on:click|stopPropagation={clearSearch}
                                    >
                                        {track.artist}
                                    </a>
                                    <span>•</span>
                                    <a
                                        href={`/album/${encodeURIComponent(track.artist)}/${encodeURIComponent(track.album)}`}
                                        class="hover:text-white hover:underline"
                                        on:click|stopPropagation={clearSearch}
                                    >
                                        {track.album}
                                    </a>
                                </div>
                            </div>
                            <!-- Add to Playlist Action -->
                            <button
                                class="p-1.5 hover:bg-white/20 rounded-md text-white/40 group-hover:text-white/70 hover:text-white transition-colors opacity-0 group-hover:opacity-100"
                                title="Add to playlist"
                                on:click={(e) => openPlaylistModal(track.id, e)}
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
                            </button>
                        </div>
                    {/each}
                </div>
            {/if}

            {#if !results.artists.length && !results.albums.length && !results.tracks.length}
                <div class="px-4 py-3 text-sm text-white/40">
                    No results found
                </div>
            {/if}
        </div>
    {/if}

    <AddToPlaylistModal
        bind:show={showPlaylistModal}
        trackIds={selectedTrackIds}
    />
</div>
