<script lang="ts">
    import { goto } from "$app/navigation";
    import { onMount } from "svelte";
    import { fade, slide } from "svelte/transition";
    import AddToPlaylistModal from "$lib/components/AddToPlaylistModal.svelte";
    import IconButton from "$lib/components/IconButton.svelte";

    interface SearchResponse {
        artists: {
            name: string;
            mbid: string;
            image_url?: string;
            art_sha1?: string;
        }[];
        albums: {
            title: string;
            artist: string;
            mbid?: string;
            art_sha1?: string;
        }[];
        tracks: {
            id: number;
            title: string;
            artist: string;
            album: string;
            mb_release_id?: string;
            duration_seconds: number;
            art_sha1?: string;
        }[];
    }

    let query = "";
    let results: SearchResponse | null = null;
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

    function navigateToArtist(name: string, mbid?: string) {
        if (mbid) {
            goto(`/artist/${mbid}`);
        } else {
            goto(`/artist/${encodeURIComponent(name)}`);
        }
        clearSearch();
    }

    function navigateToAlbum(album: string, artist: string, mbid?: string) {
        if (mbid) {
            goto(`/album/${mbid}`);
        }
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
                aria-label="Clear search"
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
            class="absolute left-0 mt-2 w-full origin-top rounded-xl border border-white/10 backdrop-blur-xl py-2 shadow-2xl ring-1 ring-black/5"
            style="background-color: rgb(15 17 25 / 95%);"
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
                            on:click={() =>
                                navigateToArtist(artist.name, artist.mbid)}
                        >
                            {#if artist.art_sha1}
                                <img
                                    src={`/art/file/${artist.art_sha1}?max_size=100`}
                                    class="h-8 w-8 rounded-full object-cover"
                                    alt=""
                                />
                            {:else if artist.image_url}
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
                        <div
                            role="button"
                            tabindex="0"
                            class="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-white/10 cursor-pointer"
                            on:click={() =>
                                navigateToAlbum(
                                    album.title,
                                    album.artist,
                                    album.mbid,
                                )}
                            on:keydown={(e) => {
                                if (e.key === "Enter" || e.key === " ") {
                                    navigateToAlbum(
                                        album.title,
                                        album.artist,
                                        album.mbid,
                                    );
                                }
                            }}
                        >
                            <div
                                class="h-8 w-8 rounded bg-white/10 flex items-center justify-center text-xs text-white/40 overflow-hidden"
                            >
                                {#if album.art_sha1}
                                    <img
                                        src={album.art_sha1
                                            ? `/art/file/${album.art_sha1}?max_size=100`
                                            : ""}
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
                                <button
                                    type="button"
                                    class="truncate text-xs text-white/60 hover:text-white hover:underline block text-left w-full"
                                    on:click|stopPropagation={() =>
                                        navigateToArtist(album.artist)}
                                >
                                    {album.artist}
                                </button>
                            </div>
                        </div>
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
                                navigateToAlbum(
                                    track.album,
                                    track.artist,
                                    track.mb_release_id,
                                )}
                            on:keydown={(e) =>
                                e.key === "Enter" &&
                                navigateToAlbum(
                                    track.album,
                                    track.artist,
                                    track.mb_release_id,
                                )}
                        >
                            <div
                                class="h-8 w-8 rounded bg-white/10 flex items-center justify-center text-xs text-white/40 overflow-hidden flex-shrink-0"
                            >
                                {#if track.art_sha1}
                                    <img
                                        src={track.art_sha1
                                            ? `/art/file/${track.art_sha1}?max_size=100`
                                            : ""}
                                        alt=""
                                        class="h-full w-full object-cover"
                                        decoding="async"
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
                            <div class="flex-1 min-w-0 overflow-hidden">
                                <div
                                    class="truncate text-sm font-medium text-white"
                                >
                                    {track.title}
                                </div>
                                <div
                                    class="truncate text-xs text-white/60 flex items-center gap-1"
                                >
                                    <button
                                        class="truncate text-xs text-white/60 flex items-center gap-1 hover:text-white hover:underline cursor-pointer"
                                        on:click|stopPropagation={() =>
                                            navigateToArtist(track.artist)}
                                    >
                                        {track.artist}
                                    </button>
                                    <span>•</span>
                                    <button
                                        class="truncate text-xs text-white/60 flex items-center gap-1 hover:text-white hover:underline cursor-pointer"
                                        on:click|stopPropagation={() =>
                                            navigateToAlbum(
                                                track.album,
                                                track.artist,
                                                track.mb_release_id,
                                            )}
                                    >
                                        {track.album}
                                    </button>
                                </div>
                            </div>
                            <!-- Action Buttons - Right Justified -->
                            <div
                                class="flex items-center gap-1 ml-auto opacity-0 group-hover:opacity-100 transition-opacity"
                            >
                                <IconButton
                                    variant="outline"
                                    size="sm"
                                    title="Play"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        // TODO: Play track functionality
                                    }}
                                    stopPropagation={true}
                                >
                                    <svg
                                        class="w-4 h-4"
                                        fill="currentColor"
                                        viewBox="0 0 24 24"
                                    >
                                        <path d="M8 5v14l11-7z" />
                                    </svg>
                                </IconButton>
                                <IconButton
                                    variant="outline"
                                    size="sm"
                                    title="Add to Queue"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        // TODO: Add to queue functionality
                                    }}
                                    stopPropagation={true}
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
                                </IconButton>
                                <IconButton
                                    variant="outline"
                                    size="sm"
                                    title="Add to Playlist"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        openPlaylistModal(track.id, e);
                                    }}
                                    stopPropagation={true}
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
                                            d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"
                                        />
                                    </svg>
                                </IconButton>
                            </div>
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
        bind:visible={showPlaylistModal}
        trackIds={selectedTrackIds}
    />
</div>
