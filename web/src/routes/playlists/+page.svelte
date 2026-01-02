<script lang="ts">
    import { onMount } from "svelte";
    import { fade } from "svelte/transition";
    import {
        fetchPlaylists,
        createPlaylist,
        getPlaylist,
        type Playlist,
    } from "$lib/api";
    import { goto } from "$app/navigation";
    import { setQueue, addToQueue } from "$stores/player";
    import IconButton from "$lib/components/IconButton.svelte";
    import TabButton from "$lib/components/TabButton.svelte";
    import Checkbox from "$lib/components/Checkbox.svelte";

    let playlists: Playlist[] = [];
    let loading = true;
    let showCreateModal = false;
    let newName = "";
    let newDesc = "";
    let newPublic = false;
    let creating = false;
    let showSortDropdown = false;

    // Sorting
    let sortBy: "updated" | "name" = "updated";

    $: sortedPlaylists = [...playlists].sort((a, b) => {
        if (sortBy === "name") {
            return a.name.localeCompare(b.name);
        } else {
            // Updated desc
            return (
                new Date(b.updated_at).getTime() -
                new Date(a.updated_at).getTime()
            );
        }
    });

    onMount(async () => {
        try {
            playlists = await fetchPlaylists();
        } catch (e) {
            console.error(e);
        } finally {
            loading = false;
        }
    });

    async function handleCreate() {
        if (!newName) return;
        creating = true;
        try {
            const p = await createPlaylist({
                name: newName,
                description: newDesc,
                is_public: newPublic,
            });
            playlists = [p, ...playlists];
            showCreateModal = false;
            newName = "";
            newDesc = "";
            newPublic = false;
            goto(`/playlists/${p.id}`);
        } catch (e) {
            console.error(e);
        } finally {
            creating = false;
        }
    }

    async function handlePlay(e: MouseEvent, playlistId: number) {
        // e.preventDefault(); // Not needed if button is properly isolated
        // e.stopPropagation();
        try {
            // We need to fetch tracks to play
            const detail = await getPlaylist(playlistId.toString());
            if (detail.tracks.length) {
                const queueItems = detail.tracks.map((t) => ({
                    id: t.track_id,
                    title: t.title,
                    artist: t.artist,
                    album: t.album,
                    duration_seconds: t.duration_seconds,
                    artwork_id: t.art_id,
                    path: t.path,
                    art_sha1: t.art_sha1,
                    codec: t.codec,
                    bit_depth: t.bit_depth,
                    sample_rate_hz: t.sample_rate_hz,
                }));
                await setQueue(
                    queueItems as unknown as import("$api").Track[],
                    0,
                );
            }
        } catch (err) {
            console.error(err);
        }
    }

    async function handleAddToQueue(e: MouseEvent, playlistId: number) {
        // e.preventDefault();
        // e.stopPropagation();
        try {
            const detail = await getPlaylist(playlistId.toString());
            if (detail.tracks.length) {
                const queueItems = detail.tracks.map((t) => ({
                    id: t.track_id,
                    title: t.title,
                    artist: t.artist,
                    album: t.album,
                    duration_seconds: t.duration_seconds,
                    artwork_id: t.art_id,
                    path: t.path,
                    art_sha1: t.art_sha1,
                    codec: t.codec,
                    bit_depth: t.bit_depth,
                    sample_rate_hz: t.sample_rate_hz,
                }));
                await addToQueue(
                    queueItems as unknown as import("$api").Track[],
                );
            }
        } catch (err) {
            console.error(err);
        }
    }

    function getArtUrl(sha1: string) {
        return `/api/art/file/${sha1}`;
    }
</script>

<div class="container mx-auto px-6 py-8">
    <div class="flex items-center justify-between mb-8">
        <h1 class="text-3xl font-bold font-display">Playlists</h1>

        <div class="flex items-center gap-4">
            <div class="relative">
                <TabButton
                    onClick={() => {
                        showSortDropdown = !showSortDropdown;
                    }}
                    active={showSortDropdown}
                    className="min-w-[160px] justify-between flex items-center gap-2"
                >
                    <span>
                        {sortBy === "updated" ? "Last Updated" : "Name (A-Z)"}
                    </span>
                    <svg
                        class="h-4 w-4 opacity-50"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                    >
                        <path
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            stroke-width="2"
                            d="M19 9l-7 7-7-7"
                        />
                    </svg>
                </TabButton>

                {#if showSortDropdown}
                    <div
                        class="surface-glass-popover absolute right-0 mt-2 w-48 rounded-lg z-50 overflow-hidden"
                    >
                        <div class="p-1 space-y-1">
                            <TabButton
                                className="w-full text-left justify-between"
                                active={sortBy === "updated"}
                                onClick={() => {
                                    sortBy = "updated";
                                    showSortDropdown = false;
                                }}
                            >
                                Last Updated
                            </TabButton>
                            <TabButton
                                className="w-full text-left justify-between"
                                active={sortBy === "name"}
                                onClick={() => {
                                    sortBy = "name";
                                    showSortDropdown = false;
                                }}
                            >
                                Name (A-Z)
                            </TabButton>
                        </div>
                    </div>
                {/if}
            </div>

            <TabButton
                onClick={() => {
                    showCreateModal = true;
                }}
                active={false}
                style="border-bottom-color: transparent;"
                className="hover:!border-accent"
            >
                Create Playlist
            </TabButton>
        </div>
    </div>

    {#if loading}
        <div class="flex justify-center p-12">
            <span class="loading loading-spinner loading-lg"></span>
        </div>
    {:else if playlists.length === 0}
        <div
            class="flex flex-col items-center justify-center p-12 text-center text-white/50"
        >
            <p class="text-lg">No playlists yet</p>
            <div class="mt-4">
                <TabButton
                    onClick={() => {
                        showCreateModal = true;
                    }}
                    active={false}
                    style="border-bottom-color: transparent;"
                    className="hover:!border-accent"
                >
                    Create your first one
                </TabButton>
            </div>
        </div>
    {:else}
        <div
            class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-6"
        >
            {#each sortedPlaylists as p (p.id)}
                <div
                    class="group relative block bg-white/5 rounded-xl overflow-hidden hover:bg-white/10 transition-colors duration-200"
                    in:fade
                >
                    <!-- Artwork Grid -->
                    <div class="aspect-square w-full bg-black/50 relative">
                        <!-- Link for the image itself -->
                        <a href="/playlists/{p.id}" class="block w-full h-full">
                            {#if p.thumbnails && p.thumbnails.length > 0}
                                {#if p.thumbnails.length >= 4}
                                    <div class="grid grid-cols-2 h-full w-full">
                                        {#each p.thumbnails.slice(0, 4) as thumb}
                                            <img
                                                src={getArtUrl(thumb)}
                                                alt=""
                                                class="w-full h-full object-cover"
                                            />
                                        {/each}
                                    </div>
                                {:else}
                                    <img
                                        src={getArtUrl(p.thumbnails[0])}
                                        alt={p.name}
                                        class="w-full h-full object-cover"
                                    />
                                {/if}
                            {:else}
                                <div
                                    class="flex items-center justify-center w-full h-full text-white/20"
                                >
                                    <svg
                                        class="w-12 h-12"
                                        fill="none"
                                        stroke="currentColor"
                                        viewBox="0 0 24 24"
                                    >
                                        <path
                                            stroke-linecap="round"
                                            stroke-linejoin="round"
                                            stroke-width="1.5"
                                            d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"
                                        />
                                    </svg>
                                </div>
                            {/if}

                            <!-- Private Indicator -->
                            {#if !p.is_public}
                                <div
                                    class="absolute top-2 right-2 bg-black/60 p-1 rounded-full backdrop-blur-sm z-10"
                                >
                                    <svg
                                        class="w-3 h-3 text-white/70"
                                        fill="none"
                                        stroke="currentColor"
                                        viewBox="0 0 24 24"
                                        ><path
                                            stroke-linecap="round"
                                            stroke-linejoin="round"
                                            stroke-width="2"
                                            d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
                                        ></path></svg
                                    >
                                </div>
                            {/if}
                        </a>

                        <!-- Hover Overlay with Buttons -->
                        <!-- Position absolute on top of the link, intercepting clicks -->
                        <div
                            class="absolute inset-0 flex items-center justify-center gap-3 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity duration-300 backdrop-blur-[2px] z-20 pointer-events-none"
                        >
                            <IconButton
                                variant="outline"
                                title="Play"
                                className="pointer-events-auto"
                                onClick={(e) => handlePlay(e, p.id)}
                            >
                                <svg
                                    class="h-6 w-6 ml-0.5"
                                    fill="currentColor"
                                    viewBox="0 0 24 24"
                                    ><path d="M8 5v14l11-7z" /></svg
                                >
                            </IconButton>
                            <IconButton
                                variant="outline"
                                title="Add to Queue"
                                className="pointer-events-auto"
                                onClick={(e) => handleAddToQueue(e, p.id)}
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

                    <div class="p-4">
                        <!-- Heading link -->
                        <a href="/playlists/{p.id}" class="block">
                            <div
                                class="font-bold text-white truncate text-lg hover:underline decoration-white/50 underline-offset-4"
                            >
                                {p.name}
                            </div>
                        </a>
                        <div class="text-white/50 text-xs mt-1">
                            {p.track_count} tracks • {p.is_public
                                ? "Shared"
                                : "Private"}
                        </div>
                    </div>
                </div>
            {/each}
        </div>
    {/if}

    <!-- Create Modal -->
    {#if showCreateModal}
        <div
            class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm"
        >
            <div
                class="surface-glass-popover rounded-2xl w-full max-w-md p-6 shadow-2xl scale-100 transition-all"
            >
                <h2 class="text-2xl font-bold mb-6 font-display">
                    Create Playlist
                </h2>
                <div class="space-y-4">
                    <div class="form-control">
                        <label class="label" for="playlist-name">
                            <span class="label-text">Name</span>
                        </label>
                        <input
                            id="playlist-name"
                            type="text"
                            bind:value={newName}
                            placeholder="My Awesome Playlist"
                            class="input input-bordered bg-white/5 border-white/10 focus:border-primary-500 w-full"
                        />
                    </div>
                    <div class="form-control">
                        <label class="label" for="playlist-desc">
                            <span class="label-text"
                                >Description (Optional)</span
                            >
                        </label>
                        <textarea
                            id="playlist-desc"
                            bind:value={newDesc}
                            placeholder="Songs for coding..."
                            class="textarea textarea-bordered bg-white/5 border-white/10 focus:border-primary-500 w-full"
                        ></textarea>
                    </div>
                    <div class="form-control">
                        <Checkbox
                            bind:checked={newPublic}
                            label="Public Playlist"
                        />
                        <p class="text-xs text-white/40 ml-7 mt-1">
                            Only visible to you.
                        </p>
                    </div>
                </div>
                <div class="modal-action mt-8 flex gap-3">
                    <TabButton
                        onClick={() => {
                            showCreateModal = false;
                        }}>Cancel</TabButton
                    >
                    <TabButton onClick={handleCreate}>
                        {creating ? "Creating..." : "Create"}
                    </TabButton>
                </div>
            </div>
        </div>
    {/if}
</div>
