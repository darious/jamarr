<script lang="ts">
    import { fade, scale } from "svelte/transition";
    import { createEventDispatcher, onMount } from "svelte";
    import {
        fetchPlaylists,
        createPlaylist,
        addTracksToPlaylist,
        type Playlist,
    } from "$lib/api";
    import TabButton from "$lib/components/TabButton.svelte";

    export let trackIds: number[] = [];
    export let show = false;

    const dispatch = createEventDispatcher();

    let playlists: Playlist[] = [];
    let loading = true;
    let searchTerm = "";
    let creatingNew = false;
    let newPlaylistName = "";

    $: filteredPlaylists = playlists.filter((p) =>
        p.name.toLowerCase().includes(searchTerm.toLowerCase()),
    );

    onMount(async () => {
        loadPlaylists();
    });

    async function loadPlaylists() {
        loading = true;
        try {
            playlists = await fetchPlaylists();
        } catch (e) {
            console.error(e);
        } finally {
            loading = false;
        }
    }

    function close() {
        show = false;
        dispatch("close");
    }

    async function addToPlaylist(playlist: Playlist) {
        try {
            await addTracksToPlaylist(playlist.id, trackIds);
            dispatch("added", { playlist });
            close();
        } catch (e) {
            console.error(e);
            // TODO: Show toast
        }
    }

    async function createAndAdd() {
        if (!newPlaylistName) return;
        try {
            const p = await createPlaylist({ name: newPlaylistName });
            await addTracksToPlaylist(p.id, trackIds);
            dispatch("added", { playlist: p });
            close();
        } catch (e) {
            console.error(e);
        }
    }
</script>

{#if show}
    <div
        class="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 cursor-pointer"
        transition:fade
        on:click|self={close}
        role="button"
        tabindex="0"
        on:keydown={(e) => e.key === "Escape" && close()}
    >
        <div
            class="bg-surface-900 border border-white/10 rounded-2xl w-full max-w-md shadow-2xl overflow-hidden flex flex-col max-h-[80vh]"
            transition:scale
        >
            <div
                class="p-4 border-b border-white/10 flex justify-between items-center"
            >
                <h2 class="text-lg font-bold">Add to Playlist</h2>
                <button
                    class="btn btn-ghost btn-sm btn-circle"
                    on:click={close}
                >
                    <svg
                        class="w-5 h-5"
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
            </div>

            <div class="p-4 border-b border-white/10">
                <input
                    type="text"
                    class="input input-sm w-full bg-white/5 border-white/10 focus:border-primary-500"
                    placeholder="Search playlists..."
                    bind:value={searchTerm}
                />
            </div>

            <div class="flex-1 overflow-y-auto p-2">
                {#if loading}
                    <div class="flex justify-center p-4">
                        <span class="loading loading-spinner"></span>
                    </div>
                {:else if filteredPlaylists.length === 0 && !creatingNew}
                    <div class="text-center p-4 text-white/50 text-sm">
                        {#if searchTerm}
                            No matching playlists.
                        {:else}
                            No playlists found.
                        {/if}
                    </div>
                {:else}
                    <div class="space-y-1">
                        {#each filteredPlaylists as p}
                            <button
                                class="w-full text-left px-4 py-3 rounded-lg hover:bg-white/10 flex items-center gap-3 group"
                                on:click={() => addToPlaylist(p)}
                            >
                                <div
                                    class="w-10 h-10 bg-white/5 rounded flex items-center justify-center text-white/20 group-hover:bg-white/10"
                                >
                                    <svg
                                        class="w-5 h-5"
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
                                <div>
                                    <div
                                        class="font-medium text-white group-hover:text-primary-400"
                                    >
                                        {p.name}
                                    </div>
                                    <div class="text-xs text-white/50">
                                        {p.track_count} tracks
                                    </div>
                                </div>
                            </button>
                        {/each}
                    </div>
                {/if}
            </div>

            <div class="p-4 border-t border-white/10 bg-white/5">
                {#if creatingNew}
                    <div class="flex gap-2">
                        <input
                            type="text"
                            class="input input-sm flex-1 bg-black/20 border-white/10"
                            placeholder="New Playlist Name"
                            bind:value={newPlaylistName}
                            on:keydown={(e) =>
                                e.key === "Enter" && createAndAdd()}
                        />
                        <TabButton
                            active={true}
                            onClick={createAndAdd}
                            className="disabled:opacity-50 disabled:cursor-not-allowed"
                            {...!newPlaylistName && { disabled: true }}
                        >
                            Create
                        </TabButton>
                        <TabButton
                            onClick={() => {
                                creatingNew = false;
                            }}
                        >
                            Cancel
                        </TabButton>
                    </div>
                {:else}
                    <button
                        class="btn btn-sm btn-ghost w-full justify-start gap-2 text-white/70 hover:text-white"
                        on:click={() => (creatingNew = true)}
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
                        Create New Playlist
                    </button>
                {/if}
            </div>
        </div>
    </div>
{/if}
