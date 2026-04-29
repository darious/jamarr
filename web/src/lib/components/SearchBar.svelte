<script lang="ts">
    import { goto } from "$app/navigation";
    import { onMount } from "svelte";
    import { fade } from "svelte/transition";
    import { fetchWithAuth, getArtUrl } from "$lib/api";
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

    export let mobile = false;
    export let autoFocus = false;
    export let className = "";
    export let onClose: (() => void) | undefined = undefined;

    let query = "";
    let results: SearchResponse | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let inputElement: HTMLInputElement;
    let showResults = false;

    let showPlaylistModal = false;
    let selectedTrackIds: number[] = [];

    const openPlaylistModal = (trackId: number, e: MouseEvent) => {
        e.stopPropagation();
        selectedTrackIds = [trackId];
        showPlaylistModal = true;
    };

    onMount(() => {
        if (autoFocus) {
            setTimeout(() => inputElement?.focus(), 0);
        }
    });

    const handleInput = () => {
        if (timer) clearTimeout(timer);
        if (query.length < 2) {
            results = null;
            showResults = false;
            return;
        }
        timer = setTimeout(async () => {
            try {
                const res = await fetchWithAuth(
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

    const handleBlur = () => {
        if (mobile) return;
        setTimeout(() => {
            showResults = false;
        }, 200);
    };

    const handleFocus = () => {
        if (query.length >= 2 && results) {
            showResults = true;
        }
    };

    function closeSearch() {
        showResults = false;
        onClose?.();
    }

    function navigateToArtist(name: string, mbid?: string) {
        if (mbid) {
            goto(`/artist/${mbid}`);
        } else {
            goto(`/artist/${encodeURIComponent(name)}`);
        }
        clearSearch();
        closeSearch();
    }

    function navigateToAlbum(album: string, artist: string, mbid?: string) {
        if (mbid) {
            goto(`/album/${mbid}`);
        } else {
            goto(`/album/${encodeURIComponent(artist)}/${encodeURIComponent(album)}`);
        }
        clearSearch();
        closeSearch();
    }

    function handleKeyDown(event: KeyboardEvent) {
        if (event.key === "Escape") {
            if (query) {
                clearSearch();
                return;
            }
            closeSearch();
        }
    }
</script>

<div class={`relative ${mobile ? "w-full" : "w-full max-w-md"} ${className}`}>
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
            placeholder={mobile ? "Search artists, albums, tracks..." : "Search..."}
            class={`w-full border border-white/10 bg-white/5 text-sm text-white placeholder-white/40 focus:border-white/20 focus:bg-white/10 focus:outline-hidden ${
                mobile
                    ? "rounded-2xl py-3 pl-10 pr-20"
                    : "rounded-full py-1.5 pl-9 pr-10"
            }`}
            bind:value={query}
            on:input={handleInput}
            on:blur={handleBlur}
            on:focus={handleFocus}
            on:keydown={handleKeyDown}
        />
        {#if query}
            <button
                class={`absolute text-white/40 hover:text-white ${
                    mobile ? "right-12" : "right-3"
                }`}
                aria-label="Clear search"
                on:click={clearSearch}
            >
                <svg
                    class="h-4 w-4"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                >
                    <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M6 18L18 6M6 6l12 12"
                    />
                </svg>
            </button>
        {/if}
        {#if mobile}
            <button
                class="absolute right-3 text-xs font-medium uppercase tracking-wide text-white/60 hover:text-white"
                aria-label="Close search"
                on:click={closeSearch}
            >
                Close
            </button>
        {/if}
    </div>

    {#if showResults && results}
        <div
            transition:fade={{ duration: 100 }}
            class={`left-0 origin-top border border-white/10 shadow-2xl ring-1 ring-black/5 ${
                mobile
                    ? "mt-3 overflow-y-auto rounded-2xl bg-[rgb(15_17_25_/_92%)]"
                    : "absolute mt-2 w-full rounded-xl backdrop-blur-xl py-2"
            }`}
            style={mobile ? "max-height: calc(100vh - 12rem);" : "background-color: rgb(15 17 25 / 95%);"}
        >
            {#if results.artists.length > 0}
                <div class="px-2 py-1">
                    <h3 class="px-2 text-xs font-semibold uppercase tracking-wider text-white/40">
                        Artists
                    </h3>
                    {#each results.artists as artist}
                        <button
                            class={`flex w-full items-center gap-3 rounded-lg text-left transition-colors hover:bg-white/10 ${
                                mobile ? "px-3 py-3" : "px-2 py-2"
                            }`}
                            on:click={() => navigateToArtist(artist.name, artist.mbid)}
                        >
                            {#if artist.art_sha1}
                                <img
                                    src={getArtUrl(artist.art_sha1, 100)}
                                    class="h-10 w-10 rounded-full object-cover"
                                    alt=""
                                />
                            {:else if artist.image_url}
                                <img
                                    src={artist.image_url}
                                    class="h-10 w-10 rounded-full object-cover"
                                    alt=""
                                />
                            {:else}
                                <div class="flex h-10 w-10 items-center justify-center rounded-full bg-white/10 text-xs">
                                    ?
                                </div>
                            {/if}
                            <div class="truncate text-sm font-medium text-white">
                                {artist.name}
                            </div>
                        </button>
                    {/each}
                </div>
            {/if}

            {#if results.albums.length > 0}
                <div class="px-2 py-1">
                    <h3 class="px-2 text-xs font-semibold uppercase tracking-wider text-white/40">
                        Albums
                    </h3>
                    {#each results.albums as album}
                        <div
                            role="button"
                            tabindex="0"
                            class={`flex w-full cursor-pointer items-center gap-3 rounded-lg text-left transition-colors hover:bg-white/10 ${
                                mobile ? "px-3 py-3" : "px-2 py-2"
                            }`}
                            on:click={() => navigateToAlbum(album.title, album.artist, album.mbid)}
                            on:keydown={(e) => {
                                if (e.key === "Enter" || e.key === " ") {
                                    navigateToAlbum(album.title, album.artist, album.mbid);
                                }
                            }}
                        >
                            <div class="flex h-10 w-10 items-center justify-center overflow-hidden rounded-sm bg-white/10 text-xs text-white/40">
                                {#if album.art_sha1}
                                    <img
                                        src={getArtUrl(album.art_sha1, 100)}
                                        alt=""
                                        class="h-full w-full object-cover"
                                    />
                                {:else}
                                    <svg
                                        class="h-4 w-4"
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
                                {/if}
                            </div>
                            <div class="overflow-hidden">
                                <div class="truncate text-sm font-medium text-white">
                                    {album.title}
                                </div>
                                <button
                                    type="button"
                                    class="block w-full truncate text-left text-xs text-white/60 hover:text-white hover:underline"
                                    on:click|stopPropagation={() => navigateToArtist(album.artist)}
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
                    <h3 class="px-2 text-xs font-semibold uppercase tracking-wider text-white/40">
                        Tracks
                    </h3>
                    {#each results.tracks as track}
                        <div
                            role="button"
                            tabindex="0"
                            class={`group flex w-full cursor-pointer items-center gap-3 rounded-lg text-left transition-colors hover:bg-white/10 ${
                                mobile ? "px-3 py-3" : "px-2 py-2"
                            }`}
                            on:click={() => navigateToAlbum(track.album, track.artist, track.mb_release_id)}
                            on:keydown={(e) =>
                                e.key === "Enter" &&
                                navigateToAlbum(track.album, track.artist, track.mb_release_id)}
                        >
                            <div class="flex h-10 w-10 flex-shrink-0 items-center justify-center overflow-hidden rounded-sm bg-white/10 text-xs text-white/40">
                                {#if track.art_sha1}
                                    <img
                                        src={getArtUrl(track.art_sha1, 100)}
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
                                    >
                                        <path
                                            stroke-linecap="round"
                                            stroke-linejoin="round"
                                            stroke-width="2"
                                            d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"
                                        />
                                    </svg>
                                {/if}
                            </div>
                            <div class="min-w-0 flex-1 overflow-hidden">
                                <div class="truncate text-sm font-medium text-white">
                                    {track.title}
                                </div>
                                <div class="flex items-center gap-1 truncate text-xs text-white/60">
                                    <button
                                        class="truncate hover:text-white hover:underline"
                                        on:click|stopPropagation={() => navigateToArtist(track.artist)}
                                    >
                                        {track.artist}
                                    </button>
                                    <span>•</span>
                                    <button
                                        class="truncate hover:text-white hover:underline"
                                        on:click|stopPropagation={() =>
                                            navigateToAlbum(track.album, track.artist, track.mb_release_id)}
                                    >
                                        {track.album}
                                    </button>
                                </div>
                            </div>
                            <div class={`ml-auto items-center gap-1 transition-opacity ${
                                mobile ? "hidden" : "opacity-0 group-hover:opacity-100 flex"
                            }`}>
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
                                        class="h-4 w-4"
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
