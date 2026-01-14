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
    import IconButton from "$lib/components/IconButton.svelte";
    import TabButton from "$lib/components/TabButton.svelte";
    import Checkbox from "$lib/components/Checkbox.svelte";
    import TrackCard from "$lib/components/TrackCard.svelte";
    import AddToPlaylistModal from "$components/AddToPlaylistModal.svelte";
    import { downloadTracks } from "$lib/helpers/downloader";

    let playlist: PlaylistDetail | null = null;
    let loading = true;
    let editing = false;
    let editName = "";
    let editDesc = "";
    let editPublic = false;

    // Helper for adding single track to playlist (different from adding WHOLE playlist to queue)
    function handleAddToPlaylistInternal(trackId: number) {
        // This typically opens the modal. We need to check if openPlaylistModal is available or import it.
        // Looking at previous artist page, it had `openPlaylistModal`.
        // I need to find where that is or how to trigger it.
        // Wait, checking imports... AddToPlaylistModal is not imported here.
        // I need to import AddToPlaylistModal and set up the state.
        showPlaylistModal = true;
        selectedTrackIds = [trackId];
    }

    let showPlaylistModal = false;
    let selectedTrackIds: number[] = [];

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
            path: t.path,
            art_sha1: t.art_sha1,
            codec: t.codec,
            bit_depth: t.bit_depth,
            sample_rate_hz: t.sample_rate_hz,
            artist_mbid: t.artist_mbid,
            album_mbid: t.album_mbid,
            mb_release_id: t.mb_release_id,
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
            path: t.path,
            art_sha1: t.art_sha1,
            codec: t.codec,
            bit_depth: t.bit_depth,
            sample_rate_hz: t.sample_rate_hz,
            artist_mbid: t.artist_mbid,
            album_mbid: t.album_mbid,
            mb_release_id: t.mb_release_id,
        }));
        await addToQueue(queueItems as unknown as import("$api").Track[]);
    }

    function handleDownload() {
        if (!playlist || !playlist.tracks.length) return;

        const tracks = playlist.tracks.map((t) => ({
            id: t.track_id,
            path: t.path,
            title: t.title,
            artist: t.artist,
            album: t.album,
            duration_seconds: t.duration_seconds,
            art_sha1: t.art_sha1,
            codec: t.codec,
            bit_depth: t.bit_depth,
            sample_rate_hz: t.sample_rate_hz,
        }));

        void downloadTracks({
            mode: "playlist",
            folderName: playlist.name,
            tracks: tracks as unknown as import("$api").Track[],
        });
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

    // Auto-scroll logic
    let autoScrollSpeed = 0;
    let animationFrameId: number | null = null;

    function stopAutoScroll() {
        if (animationFrameId) {
            cancelAnimationFrame(animationFrameId);
            animationFrameId = null;
        }
        autoScrollSpeed = 0;
    }

    function startAutoScroll() {
        if (animationFrameId) return;
        const scroll = () => {
            if (autoScrollSpeed !== 0) {
                window.scrollBy(0, autoScrollSpeed);
                animationFrameId = requestAnimationFrame(scroll);
            } else {
                animationFrameId = null;
            }
        };
        animationFrameId = requestAnimationFrame(scroll);
    }

    function checkAutoScroll(y: number) {
        const threshold = 100;
        const maxSpeed = 15;
        const windowHeight = window.innerHeight;

        if (y < threshold) {
            const dist = Math.max(0, threshold - y);
            const ratio = Math.min(1, dist / threshold);
            autoScrollSpeed = -maxSpeed * ratio; // Scroll up
            startAutoScroll();
        } else if (y > windowHeight - threshold) {
            const dist = Math.max(0, y - (windowHeight - threshold));
            const ratio = Math.min(1, dist / threshold);
            autoScrollSpeed = maxSpeed * ratio; // Scroll down
            startAutoScroll();
        } else {
            autoScrollSpeed = 0;
        }
    }

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
        stopAutoScroll();

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

    function handleDragEnd() {
        stopAutoScroll();
        draggingIndex = null;
        dragOverIndex = null;
    }

    function formatTime(seconds: number) {
        if (!seconds || isNaN(seconds)) return "0:00";
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${s.toString().padStart(2, "0")}`;
    }

    function getArtUrl(sha1: string) {
        return `/api/art/file/${sha1}`;
    }
</script>

<svelte:window
    on:dragover={(e) => {
        if (draggingIndex !== null) {
            e.preventDefault();
            checkAutoScroll(e.clientY);
        }
    }}
    on:dragend={handleDragEnd}
/>

<div class="min-h-screen bg-surface-1 pb-20">
    <!-- Padding for player bar -->
    {#if loading}
        <div class="flex justify-center p-20">
            <span class="loading loading-spinner loading-lg"></span>
        </div>
    {:else if playlist}
        <!-- Header -->
        <div class="bg-gradient-to-b from-surface-2 to-surface-1 p-8">
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
                            class="flex items-center justify-center h-full text-subtle bg-surface-1"
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
                    <!-- Hover Overlay with Buttons -->
                    <div
                        class="absolute inset-0 flex items-center justify-center gap-3 opacity-0 group-hover:opacity-100 transition-opacity duration-300 z-20 pointer-events-none bg-black/40 backdrop-blur-[2px]"
                    >
                        <div
                            class="pointer-events-auto flex items-center gap-3 text-white"
                        >
                            <IconButton
                                variant="primary"
                                title="Play"
                                onClick={(e) => handlePlay(e)}
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
                                onClick={(e) => handleAddToQueue(e)}
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
                            <IconButton
                                variant="primary"
                                title="Download Playlist"
                                onClick={(e) => {
                                    e.stopPropagation();
                                    handleDownload();
                                }}
                                stopPropagation={true}
                                className="shadow-lg transition-all"
                            >
                                <svg
                                    class="h-6 w-6"
                                    fill="currentColor"
                                    viewBox="0 0 24 24"
                                    ><path
                                        d="M5 20h14v-2H5v2zM19 9h-4V3H9v6H5l7 7 7-7z"
                                    /></svg
                                >
                            </IconButton>
                        </div>
                    </div>
                </div>

                <!-- Info -->
                <div class="flex-1 space-y-4 w-full">
                    <div
                        class="text-muted text-sm uppercase font-bold tracking-wider"
                    >
                        Playlist
                    </div>
                    {#if editing}
                        <input
                            class="input input-lg text-4xl font-bold bg-surface-2 w-full text-default"
                            bind:value={editName}
                        />
                        <textarea
                            class="textarea bg-surface-2 w-full text-default"
                            bind:value={editDesc}
                            placeholder="Description"
                        ></textarea>
                        <div class="form-control">
                            <Checkbox
                                bind:checked={editPublic}
                                label="Public"
                            />
                        </div>
                        <div class="flex gap-2">
                            <TabButton active={false} onClick={handleSave}
                                >Save</TabButton
                            >
                            <TabButton
                                onClick={() => {
                                    editing = false;
                                }}>Cancel</TabButton
                            >
                        </div>
                    {:else}
                        <div class="flex justify-between items-start">
                            <div>
                                <h1
                                    class="text-5xl md:text-7xl font-black font-display text-default shadow-xl mb-4"
                                >
                                    {playlist.name}
                                </h1>
                                {#if playlist.description}
                                    <p
                                        class="text-muted text-lg mb-4 max-w-2xl"
                                    >
                                        {playlist.description}
                                    </p>
                                {/if}
                            </div>

                            <!-- Action Buttons (Edit/Delete) -->
                            <!-- Action Buttons (Edit/Delete) -->
                            <div class="flex gap-2">
                                <TabButton
                                    className="whitespace-nowrap"
                                    onClick={() => {
                                        editing = true;
                                    }}
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
                                </TabButton>
                                <TabButton
                                    className="hover:text-red-400 hover:border-red-400 whitespace-nowrap"
                                    onClick={handleDelete}
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
                                </TabButton>
                            </div>
                        </div>

                        <div class="flex items-center gap-2 text-muted text-sm">
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
            <!-- Track List (Queue Style) -->
            <div class="space-y-1">
                {#each playlist.tracks as track, index (track.playlist_track_id)}
                    {#if draggingIndex !== null && dragOverIndex === index}
                        <div
                            class="h-[2px] w-full bg-accent drag-indicator-shadow rounded-full my-1 transition-all"
                        ></div>
                    {/if}
                    <!-- Track Card Wrapper for Drag and Drop -->
                    <div
                        role="listitem"
                        class="relative group"
                        draggable="true"
                        on:dragstart={(e) => handleDragStart(e, index)}
                        on:dragover={(e) => handleDragOver(e, index)}
                        on:drop={(e) => handleDrop(e, index)}
                        on:dragend={handleDragEnd}
                    >
                        <TrackCard
                            track={{
                                id: track.track_id,
                                title: track.title,
                                duration_seconds: track.duration_seconds,
                                codec: track.codec,
                                bit_depth: track.bit_depth,
                                sample_rate_hz: track.sample_rate_hz,
                                plays: track.plays,
                            }}
                            artists={track.artists}
                            artist={{
                                name: track.artist,
                                mbid: track.artist_mbid,
                            }}
                            album={{
                                name: track.album,
                                mbid: track.mb_release_id,
                                mb_release_id: track.mb_release_id,
                            }}
                            artwork={{
                                sha1: track.art_sha1,
                            }}
                            showIndex={true}
                            index={index + 1}
                            showArtwork={true}
                            showAlbum={true}
                            showArtist={true}
                            showTechDetails={true}
                            isDragging={draggingIndex === index}
                            onPlay={() => handlePlay()}
                            onQueue={() => handleAddToQueue()}
                            onAddToPlaylist={() =>
                                handleAddToPlaylistInternal(track.track_id)}
                            onRemove={() => removeTrack(track)}
                            onClick={() => handlePlay()}
                        />
                    </div>
                {/each}
                {#if draggingIndex !== null && dragOverIndex === playlist.tracks.length}
                    <div
                        class="h-[2px] w-full bg-accent drag-indicator-shadow rounded-full my-1 transition-all"
                    ></div>
                    <div
                        role="listitem"
                        class="h-12 w-full flex items-center justify-center text-transparent"
                        on:dragover={(e) => {
                            e.preventDefault();
                            dragOverIndex = playlist.tracks.length;
                        }}
                    ></div>
                {/if}
            </div>
        </div>
    {:else}
        <div class="p-20 text-center">Playlist not found</div>
    {/if}

    <AddToPlaylistModal
        bind:visible={showPlaylistModal}
        trackIds={selectedTrackIds}
    />
</div>
