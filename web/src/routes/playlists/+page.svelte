<script lang="ts">
    import { onMount } from "svelte";
    import { fade } from "svelte/transition";
    import {
        fetchPlaylists,
        createPlaylist,
        getPlaylist,
        getArtUrl,
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
    let chartFile: File | null = null;
    let chartFileName = "";
    let parseError = "";

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

    async function handleFileSelect(event: Event) {
        const input = event.target as HTMLInputElement;
        const file = input.files?.[0];
        parseError = "";
        
        if (file) {
            chartFile = file;
            chartFileName = file.name;
        } else {
            chartFile = null;
            chartFileName = "";
        }
    }

    function parseChartFile(content: string): number[] {
        const lines = content.trim().split('\n');
        
        if (lines.length === 0) {
            throw new Error("File is empty");
        }
        
        // Check header
        const header = lines[0].trim();
        if (header !== "track_id,position") {
            throw new Error("Invalid file format. Expected header: track_id,position");
        }
        
        const trackIds: number[] = [];
        const trackData: { id: number; position: number }[] = [];
        
        for (let i = 1; i < lines.length; i++) {
            const line = lines[i].trim();
            if (!line) continue; // Skip empty lines
            
            const parts = line.split(',');
            if (parts.length !== 2) {
                throw new Error(`Invalid format on line ${i + 1}: ${line}`);
            }
            
            const trackId = parseInt(parts[0].trim());
            const position = parseInt(parts[1].trim());
            
            if (isNaN(trackId) || isNaN(position)) {
                throw new Error(`Invalid numbers on line ${i + 1}: ${line}`);
            }
            
            trackData.push({ id: trackId, position });
        }
        
        // Sort by position and extract track IDs (renumbering to remove gaps)
        trackData.sort((a, b) => a.position - b.position);
        return trackData.map(t => t.id);
    }

    async function handleCreate() {
        if (!newName) return;
        
        parseError = "";
        let trackIds: number[] = [];
        
        // Parse chart file if provided
        if (chartFile) {
            try {
                const content = await chartFile.text();
                trackIds = parseChartFile(content);
            } catch (e) {
                parseError = e instanceof Error ? e.message : "Failed to parse file";
                return;
            }
        }
        
        creating = true;
        try {
            const p = await createPlaylist({
                name: newName,
                description: newDesc,
                is_public: newPublic,
                track_ids: trackIds.length > 0 ? trackIds : undefined,
            });
            playlists = [p, ...playlists];
            showCreateModal = false;
            newName = "";
            newDesc = "";
            newPublic = false;
            chartFile = null;
            chartFileName = "";
            parseError = "";
            goto(`/playlists/${p.id}`);
        } catch (e) {
            console.error(e);
            parseError = e instanceof Error ? e.message : "Failed to create playlist";
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

    function getPlaylistArtUrl(sha1: string, size: number = 300) {
        return getArtUrl(sha1, size);
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
            class="flex flex-col items-center justify-center p-12 text-center text-muted"
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
                    class="group relative block surface-glass-panel rounded-xl overflow-hidden hover:bg-surface-2 transition-all duration-300 hover:scale-105 hover:z-10 hover:shadow-xl"
                    in:fade
                >
                    <!-- Artwork Grid -->
                    <div
                        class="aspect-square w-full bg-surface-3 relative transition-transform duration-300"
                    >
                        <!-- Link for the image itself -->
                        <a href="/playlists/{p.id}" class="block w-full h-full">
                            {#if p.thumbnails && p.thumbnails.length > 0}
                                {#if p.thumbnails.length >= 4}
                                    <div class="grid grid-cols-2 h-full w-full">
                                        {#each p.thumbnails.slice(0, 4) as thumb}
                                            <img
                                                src={getPlaylistArtUrl(thumb, 300)}
                                                alt=""
                                                class="w-full h-full object-cover"
                                                loading="lazy"
                                                decoding="async"
                                            />
                                        {/each}
                                    </div>
                                {:else}
                                    <img
                                        src={getPlaylistArtUrl(p.thumbnails[0], 600)}
                                        alt={p.name}
                                        class="w-full h-full object-cover"
                                        loading="lazy"
                                        decoding="async"
                                    />
                                {/if}
                            {:else}
                                <div
                                    class="flex items-center justify-center w-full h-full text-subtle bg-surface-2"
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
                                    class="absolute top-2 right-2 bg-surface-3 p-1 rounded-full backdrop-blur-sm z-10"
                                >
                                    <svg
                                        class="w-3 h-3 text-muted"
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

                        <div
                            class="absolute inset-0 opacity-0 transition-opacity group-hover:opacity-100 flex items-center justify-center gap-3 z-10 pointer-events-none"
                        >
                            <div
                                class="pointer-events-auto flex items-center gap-3 text-white"
                            >
                                <IconButton
                                    variant="primary"
                                    title="Play"
                                    onClick={(e) => handlePlay(e, p.id)}
                                    stopPropagation={true}
                                    className="shadow-lg transition-all"
                                >
                                    <svg
                                        class="h-6 w-6 ml-0.5"
                                        fill="currentColor"
                                        viewBox="0 0 24 24"
                                        ><path d="M8 5v14l11-7z" /></svg
                                    >
                                </IconButton>
                                <IconButton
                                    variant="primary"
                                    title="Add to Queue"
                                    onClick={(e) => handleAddToQueue(e, p.id)}
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
                    </div>

                    <div class="p-4">
                        <!-- Heading link -->
                        <a href="/playlists/{p.id}" class="block">
                            <div
                                class="font-bold text-default truncate text-lg hover:underline decoration-subtle underline-offset-4"
                            >
                                {p.name}
                            </div>
                        </a>
                        <div class="text-muted text-xs mt-1">
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
                <h2 class="text-2xl font-bold mb-6 font-display text-default">
                    Create Playlist
                </h2>
                <div class="space-y-4">
                    <div class="form-control">
                        <label class="label" for="playlist-name">
                            <span class="label-text text-default">Name</span>
                        </label>
                        <input
                            id="playlist-name"
                            type="text"
                            bind:value={newName}
                            placeholder="My Awesome Playlist"
                            class="input bg-surface-2 border-subtle focus:border-accent w-full text-default"
                        />
                    </div>
                    <div class="form-control">
                        <label class="label" for="playlist-desc">
                            <span class="label-text text-default"
                                >Description (Optional)</span
                            >
                        </label>
                        <textarea
                            id="playlist-desc"
                            bind:value={newDesc}
                            placeholder="Songs for coding..."
                            class="textarea textarea-bordered bg-surface-2 border-subtle focus:border-accent w-full text-default"
                        ></textarea>
                    </div>
                    <div class="form-control">
                        <label class="label" for="chart-file">
                            <span class="label-text text-default"
                                >Import from Chart File (Optional)</span
                            >
                        </label>
                        <div class="flex items-center gap-3">
                            <input
                                id="chart-file"
                                type="file"
                                accept=".txt,.csv"
                                on:change={handleFileSelect}
                                class="hidden"
                            />
                            <label
                                for="chart-file"
                                class="btn btn-sm bg-surface-3 border-subtle hover:border-accent text-default cursor-pointer"
                            >
                                <svg
                                    class="w-4 h-4 mr-2"
                                    fill="none"
                                    stroke="currentColor"
                                    viewBox="0 0 24 24"
                                >
                                    <path
                                        stroke-linecap="round"
                                        stroke-linejoin="round"
                                        stroke-width="2"
                                        d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                                    />
                                </svg>
                                Choose File
                            </label>
                            {#if chartFileName}
                                <span class="text-sm text-default truncate flex-1">
                                    {chartFileName}
                                </span>
                                <button
                                    type="button"
                                    class="btn btn-sm btn-ghost text-subtle hover:text-default"
                                    aria-label="Clear file"
                                    on:click={() => {
                                        chartFile = null;
                                        chartFileName = "";
                                        parseError = "";
                                        // Reset file input
                                        const input = document.getElementById('chart-file') as HTMLInputElement;
                                        if (input) input.value = '';
                                    }}
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
                                            d="M6 18L18 6M6 6l12 12"
                                        />
                                    </svg>
                                </button>
                            {:else}
                                <span class="text-xs text-subtle">
                                    Format: track_id,position
                                </span>
                            {/if}
                        </div>
                    </div>
                    {#if parseError}
                        <div class="alert alert-error bg-red-500/10 border border-red-500/20 text-red-400 text-sm p-3 rounded-lg">
                            <svg
                                class="w-5 h-5 flex-shrink-0"
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
                            >
                                <path
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                    stroke-width="2"
                                    d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                                />
                            </svg>
                            <span>{parseError}</span>
                        </div>
                    {/if}
                    <div class="form-control">
                        <Checkbox
                            bind:checked={newPublic}
                            label="Public Playlist"
                        />
                        <p class="text-xs text-subtle ml-7 mt-1">
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
