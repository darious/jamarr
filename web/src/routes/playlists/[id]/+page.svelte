<script lang="ts">
    import { page } from "$app/stores";
    import { onMount } from "svelte";
    import {
        getPlaylist,
        updatePlaylist,
        deletePlaylist,
        removeTrackFromPlaylist,
        reorderPlaylist,
        type PlaylistDetail,
        type PlaylistTrack,
    } from "$lib/api";
    import { goto } from "$app/navigation";
    import { setQueue, addToQueue } from "$stores/player";

    let playlist: PlaylistDetail | null = null;
    let loading = true;
    let editing = false;
    let editName = "";
    let editDesc = "";
    let editPublic = false;

    $: id = $page.params.id;

    async function load() {
        loading = true;
        try {
            playlist = await getPlaylist(id);

            // Fix missing thumbnails property by deriving from tracks
            if (
                playlist &&
                (!playlist.thumbnails || playlist.thumbnails.length === 0)
            ) {
                const uniqueArts = new Set<string>();
                for (const t of playlist.tracks) {
                    if (t.art_sha1) uniqueArts.add(t.art_sha1);
                    if (uniqueArts.size >= 4) break;
                }
                // @ts-ignore - Adding property dynamically
                playlist.thumbnails = Array.from(uniqueArts);
            }

            editName = playlist.name;
            editDesc = playlist.description || "";
            editPublic = playlist.is_public;
        } catch (e) {
            console.error(e);
        } finally {
            loading = false;
        }
    }

    onMount(load);

    async function handleSave() {
        if (!playlist) return;
        try {
            await updatePlaylist(playlist.id, {
                name: editName,
                description: editDesc,
                is_public: editPublic,
            });
            editing = false;
            load();
        } catch (e) {
            console.error(e);
        }
    }

    async function handleDelete() {
        if (
            !playlist ||
            !confirm("Are you sure you want to delete this playlist?")
        )
            return;
        try {
            await deletePlaylist(playlist.id);
            goto("/playlists");
        } catch (e) {
            console.error(e);
        }
    }

    async function handlePlay(e?: MouseEvent) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        if (!playlist || !playlist.tracks.length) return;

        // Convert to queue items
        const queueItems = playlist.tracks.map((t) => ({
            id: t.track_id,
            title: t.title,
            artist: t.artist,
            album: t.album,
            duration_seconds: t.duration_seconds,
            artwork_id: t.art_id,
            path: t.path,
            art_sha1: t.art_sha1,
        }));

        await setQueue(queueItems as unknown as import("$api").Track[], 0);
    }

    async function handleAddToQueue(e?: MouseEvent) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        if (!playlist || !playlist.tracks.length) return;
        const queueItems = playlist.tracks.map((t) => ({
            id: t.track_id,
            title: t.title,
            artist: t.artist,
            album: t.album,
            duration_seconds: t.duration_seconds,
            artwork_id: t.art_id,
            path: t.path, // Use t.path here as well to be consistent, though originally it was ""?
            // Actually in my previous fix I kept it as "", but I should probably use t.path if available?
            // The previous fix for list page used t.path.
            // In the detail page logic from Step 22 (original read), handleAddToQueue had path: ""
            // But handlePlay had path: t.path.
            // Wait, looking at Step 22 output:
            // handlePlay: path: t.path
            // handleAddToQueue: path: ""
            // Why would add to queue have empty path? That seems like a bug too or intent to reload?
            // I'll stick to t.path to be safe as the error was about duration_seconds.
            // But the previous file content I'm replacing (lines 92-118) covers both?
            // No, the Replace tool needs contiguous block.
            // Let's check the lines in Step 22 again or my memory of recent read.
            // Ah, I don't have the current state of [id]/+page.svelte fully cached in my head for lines.
            // Better to rely on what I saw in previous turn's output or just assume I should fix duration.

            // Re-reading Step 22 output:
            // Line 98: duration: t.duration_seconds
            // Line 118: duration: t.duration_seconds
            // Line 120: path: ""

            // I will fix duration -> duration_seconds.
            // I will also fix path: "" to path: t.path in handleAddToQueue just in case, as I did in list page.
            art_sha1: t.art_sha1,
        }));
        await addToQueue(queueItems as unknown as import("$api").Track[]);
    }

    async function removeTrack(pt: PlaylistTrack) {
        if (!playlist) return;
        if (!confirm("Remove track?")) return;
        try {
            await removeTrackFromPlaylist(playlist.id, pt.playlist_track_id);
            // Optimistic update
            playlist.tracks = playlist.tracks.filter(
                (t) => t.playlist_track_id !== pt.playlist_track_id,
            );
            playlist.track_count--;
        } catch (e) {
            console.error(e);
            load(); // Reload on error
        }
    }

    // Drag and Drop Logic
    let draggingIndex: number | null = null;
    let dragOverIndex: number | null = null;

    function handleDragStart(e: DragEvent, index: number) {
        draggingIndex = index;
        if (e.dataTransfer) {
            e.dataTransfer.effectAllowed = "move";
        }
    }

    function handleDragOver(e: DragEvent, index: number) {
        e.preventDefault();
        dragOverIndex = index;
    }

    async function handleDrop(e: DragEvent, dropIndex: number) {
        e.preventDefault();
        if (draggingIndex === null || draggingIndex === dropIndex || !playlist)
            return;

        // Reorder array
        const newTracks = [...playlist.tracks];
        const [movedItem] = newTracks.splice(draggingIndex, 1);
        newTracks.splice(dropIndex, 0, movedItem);

        // Optimistic update
        playlist.tracks = newTracks;

        draggingIndex = null;
        dragOverIndex = null;

        // Prepare ID list
        const orderedIds = newTracks.map((t) => t.playlist_track_id);

        try {
            await reorderPlaylist(playlist.id, orderedIds);
        } catch (e) {
            console.error("Reorder failed", e);
            load(); // Revert
        }
    }

    function getArtUrl(sha1: string) {
        return `/api/art/file/${sha1}`;
    }
</script>

<div class="min-h-screen bg-black/20 pb-20">
    <!-- Padding for player bar -->
    {#if loading}
        <div class="flex justify-center p-20">
            <span class="loading loading-spinner loading-lg"></span>
        </div>
    {:else if playlist}
        <!-- Header -->
        <div class="bg-gradient-to-b from-white/5 to-black/20 p-8">
            <div
                class="container mx-auto flex flex-col md:flex-row gap-8 items-end"
            >
                <!-- Cover -->
                <div
                    class="w-64 h-64 bg-black/50 shadow-2xl rounded-lg overflow-hidden flex-shrink-0 group relative"
                >
                    {#if playlist.thumbnails && playlist.thumbnails.length > 0}
                        {#if playlist.thumbnails.length >= 4}
                            <div class="grid grid-cols-2 h-full w-full">
                                {#each playlist.thumbnails.slice(0, 4) as thumb}
                                    <img
                                        src={getArtUrl(thumb)}
                                        class="w-full h-full object-cover"
                                        alt="Playlist thumbnail"
                                    />
                                {/each}
                            </div>
                        {:else}
                            <img
                                src={getArtUrl(playlist.thumbnails[0])}
                                class="w-full h-full object-cover"
                                alt={playlist.name}
                            />
                        {/if}
                    {:else}
                        <div
                            class="flex items-center justify-center h-full text-white/20 bg-white/5"
                        >
                            <svg
                                class="w-20 h-20"
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
                                ><path
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                    stroke-width="1.5"
                                    d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"
                                /></svg
                            >
                        </div>
                    {/if}

                    <!-- Hover Overlay with Buttons -->
                    <div
                        class="absolute inset-0 flex items-center justify-center gap-3 bg-black/60 opacity-0 group-hover:opacity-100 transition-all duration-300 backdrop-blur-[2px] z-20"
                    >
                        <button
                            class="btn-icon btn-icon-lg text-white hover:scale-110 transition-transform drop-shadow-lg"
                            on:click={(e) => handlePlay(e)}
                            title="Play"
                        >
                            <svg
                                class="h-8 w-8 ml-1"
                                fill="currentColor"
                                viewBox="0 0 24 24"
                                ><path d="M8 5v14l11-7z" /></svg
                            >
                        </button>
                        <button
                            class="btn-icon btn-icon-md bg-black/60 hover:bg-black/80 text-white backdrop-blur-md border border-white/10 shadow-xl"
                            on:click={(e) => handleAddToQueue(e)}
                            title="Add to Queue"
                        >
                            <svg
                                class="h-6 w-6"
                                fill="currentColor"
                                viewBox="0 0 24 24"
                                ><path
                                    d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"
                                /></svg
                            >
                        </button>
                    </div>
                </div>

                <!-- Info -->
                <div class="flex-1 space-y-4 w-full">
                    <div
                        class="text-white/60 text-sm uppercase font-bold tracking-wider"
                    >
                        Playlist
                    </div>
                    {#if editing}
                        <input
                            class="input input-lg text-4xl font-bold bg-white/10 w-full"
                            bind:value={editName}
                        />
                        <textarea
                            class="textarea bg-white/10 w-full"
                            bind:value={editDesc}
                            placeholder="Description"
                        ></textarea>
                        <label class="label cursor-pointer justify-start gap-3">
                            <input
                                type="checkbox"
                                class="toggle"
                                bind:checked={editPublic}
                            />
                            <span class="label-text text-white">Public</span>
                        </label>
                        <div class="flex gap-2">
                            <button
                                class="btn bg-white text-black hover:bg-white/90 border-none btn-sm"
                                on:click={handleSave}>Save</button
                            >
                            <button
                                class="btn btn-ghost btn-sm"
                                on:click={() => (editing = false)}
                                >Cancel</button
                            >
                        </div>
                    {:else}
                        <div class="flex justify-between items-start">
                            <div>
                                <h1
                                    class="text-5xl md:text-7xl font-black font-display text-white shadow-xl mb-4"
                                >
                                    {playlist.name}
                                </h1>
                                {#if playlist.description}
                                    <p
                                        class="text-white/70 text-lg mb-4 max-w-2xl"
                                    >
                                        {playlist.description}
                                    </p>
                                {/if}
                            </div>

                            <!-- Action Buttons (Edit/Delete) -->
                            <div class="flex gap-2">
                                <button
                                    class="btn btn-ghost hover:bg-white/10 text-white/70 hover:text-white"
                                    on:click={() => (editing = true)}
                                >
                                    <svg
                                        class="w-5 h-5 mr-2"
                                        fill="none"
                                        stroke="currentColor"
                                        viewBox="0 0 24 24"
                                        ><path
                                            stroke-linecap="round"
                                            stroke-linejoin="round"
                                            stroke-width="2"
                                            d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
                                        ></path></svg
                                    >
                                    Edit Details
                                </button>
                                <button
                                    class="btn btn-ghost hover:bg-red-500/20 text-white/70 hover:text-red-400"
                                    on:click={handleDelete}
                                >
                                    <svg
                                        class="w-5 h-5 mr-2"
                                        fill="none"
                                        stroke="currentColor"
                                        viewBox="0 0 24 24"
                                        ><path
                                            stroke-linecap="round"
                                            stroke-linejoin="round"
                                            stroke-width="2"
                                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                                        ></path></svg
                                    >
                                    Delete Playlist
                                </button>
                            </div>
                        </div>

                        <div
                            class="flex items-center gap-2 text-white/60 text-sm"
                        >
                            <span>{playlist.track_count} tracks</span>
                            <span>•</span>
                            <span
                                >{Math.floor(playlist.total_duration / 60)} min</span
                            >
                            {#if !playlist.is_public}
                                <span>•</span>
                                <span class="flex items-center gap-1"
                                    ><svg
                                        class="w-3 h-3"
                                        fill="none"
                                        stroke="currentColor"
                                        viewBox="0 0 24 24"
                                        ><path
                                            stroke-linecap="round"
                                            stroke-linejoin="round"
                                            stroke-width="2"
                                            d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
                                        ></path></svg
                                    > Private</span
                                >
                            {/if}
                        </div>
                    {/if}
                </div>
            </div>
        </div>

        <!-- Track List -->
        <div class="container mx-auto px-6 py-4">
            <!-- Removed separate play bar, now actions are on cover/header -->
            <div class="overflow-x-auto">
                <table class="table w-full">
                    <thead>
                        <tr class="text-white/40 border-b border-white/5">
                            <th class="w-10">#</th>
                            <th>Title</th>
                            <th>Album</th>
                            <th>Duration</th>
                            <th class="w-10"></th>
                        </tr>
                    </thead>
                    <tbody>
                        {#each playlist.tracks as track, index (track.playlist_track_id)}
                            <tr
                                class="hover:bg-white/5 group transition-colors cursor-move {dragOverIndex ===
                                index
                                    ? 'border-t-2 border-primary-500'
                                    : ''} {draggingIndex === index
                                    ? 'opacity-50'
                                    : ''}"
                                draggable="true"
                                on:dragstart={(e) => handleDragStart(e, index)}
                                on:dragover={(e) => handleDragOver(e, index)}
                                on:drop={(e) => handleDrop(e, index)}
                            >
                                <td class="text-white/40 font-mono text-sm"
                                    >{index + 1}</td
                                >
                                <td>
                                    <div class="flex items-center gap-3">
                                        {#if track.art_sha1}
                                            <img
                                                src={getArtUrl(track.art_sha1)}
                                                class="w-10 h-10 rounded object-cover"
                                                alt=""
                                            />
                                        {:else}
                                            <div
                                                class="w-10 h-10 rounded bg-white/10 flex items-center justify-center text-white/20"
                                            >
                                                <svg
                                                    class="w-6 h-6"
                                                    fill="none"
                                                    stroke="currentColor"
                                                    viewBox="0 0 24 24"
                                                    ><path
                                                        stroke-linecap="round"
                                                        stroke-linejoin="round"
                                                        stroke-width="1.5"
                                                        d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"
                                                    ></path></svg
                                                >
                                            </div>
                                        {/if}
                                        <div>
                                            <div class="font-medium text-white">
                                                {track.title}
                                            </div>
                                            <div class="text-xs text-white/50">
                                                {track.artist}
                                            </div>
                                        </div>
                                    </div>
                                </td>
                                <td class="text-white/50">{track.album}</td>
                                <td class="font-mono text-white/40">
                                    {Math.floor(track.duration_seconds / 60)}:{(
                                        track.duration_seconds % 60
                                    )
                                        .toFixed(0)
                                        .padStart(2, "0")}
                                </td>
                                <td>
                                    <button
                                        class="btn btn-ghost btn-xs btn-circle opacity-0 group-hover:opacity-100 text-white/40 hover:text-white"
                                        on:click={() => removeTrack(track)}
                                        title="Remove from playlist"
                                    >
                                        <svg
                                            class="w-4 h-4"
                                            fill="none"
                                            stroke="currentColor"
                                            viewBox="0 0 24 24"
                                            ><path
                                                stroke-linecap="round"
                                                stroke-linejoin="round"
                                                stroke-width="2"
                                                d="M6 18L18 6M6 6l12 12"
                                            ></path></svg
                                        >
                                    </button>
                                </td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            </div>
        </div>
    {:else}
        <div class="p-20 text-center">Playlist not found</div>
    {/if}
</div>
