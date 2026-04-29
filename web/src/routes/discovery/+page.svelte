<script lang="ts">
    import { page } from "$app/stores";
    import { goto, invalidateAll } from "$app/navigation";
    import { fade } from "svelte/transition";
    import TrackCard from "$components/TrackCard.svelte";
    import IconButton from "$components/IconButton.svelte";
    import { setQueue, addToQueue } from "$stores/player";
    import {
        fetchTracks,
        getArtUrl,
        type SeedArtist,
        type RecommendedArtist,
        type RecommendedAlbum,
        type RecommendedTrack,
    } from "$lib/api";

    export let data: {
        seeds: SeedArtist[];
        artists: RecommendedArtist[];
        albums: RecommendedAlbum[];
        tracks: RecommendedTrack[];
        days: number;
    };

    $: ({ seeds, artists, albums, tracks, days } = data);

    let daysOptions = [
        { value: 7, label: "Last 7 Days" },
        { value: 14, label: "Last 14 Days" },
        { value: 30, label: "Last 30 Days" },
        { value: 90, label: "Last 90 Days" },
        { value: 365, label: "Last Year" },
        { value: 0, label: "All Time" },
    ];

    async function changeDays(newDays: number) {
        const url = new URL($page.url);
        url.searchParams.set("days", newDays.toString());
        await goto(url, { keepFocus: true });
    }

    async function refresh() {
        await invalidateAll();
    }

    async function playAlbum(album: RecommendedAlbum) {
        try {
            const tracks = await fetchTracks({
                album: album.title,
                artist: album.artist,
                albumMbid: album.mbid,
            });
            if (tracks.length > 0) {
                void setQueue(tracks, 0);
            }
        } catch (e) {
            console.error("Failed to play album", e);
        }
    }

    async function queueAlbum(album: RecommendedAlbum) {
        try {
            const tracks = await fetchTracks({
                album: album.title,
                artist: album.artist,
                albumMbid: album.mbid,
            });
            if (tracks.length > 0) {
                addToQueue(tracks);
            }
        } catch (e) {
            console.error("Failed to queue album", e);
        }
    }

    function mapToTrack(rt: RecommendedTrack): any {
        return {
            ...rt,
            artist: rt.artist.name, // Convert object to string
            artists: [rt.artist], // Keep object in array
            album: rt.album.name, // Convert object to string
            album_mbid: rt.album.mbid,
            mb_release_id: rt.album.mb_release_id,
            art_sha1: rt.artwork?.sha1,
        };
    }

    function playAllTracks() {
        if (tracks.length > 0) {
            setQueue(tracks.map(mapToTrack), 0);
        }
    }

    function queueAllTracks() {
        if (tracks.length > 0) {
            addToQueue(tracks.map(mapToTrack));
        }
    }

    function handleScroll(e: WheelEvent) {
        if (e.deltaY !== 0) {
            e.preventDefault();
            const container = e.currentTarget as HTMLElement;
            container.scrollLeft += e.deltaY;
        }
    }
</script>

<div
    class="mx-auto flex w-full max-w-[1700px] flex-col gap-8 px-4 py-6 pb-32 md:gap-10 md:px-8 md:py-10"
>
    <!-- Header Controls -->
    <div
        class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between"
    >
        <div>
            <h1 class="text-3xl font-bold tracking-tight text-default">
                Discovery
            </h1>
            <p class="text-muted mt-1">
                Recommendations based on your listening history.
            </p>
        </div>

        <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
            <div
                class="flex items-center gap-2 overflow-x-auto rounded-xl border border-subtle bg-surface-2 p-1"
            >
                {#each daysOptions as option}
                    <button
                        class="whitespace-nowrap px-3 py-1.5 text-sm rounded-md transition-all {days ===
                        option.value
                            ? 'bg-accent text-white shadow-xs'
                            : 'text-muted hover:text-default hover:bg-surface-3'}"
                        on:click={() => changeDays(option.value)}
                    >
                        {option.label}
                    </button>
                {/each}
            </div>

            <IconButton variant="outline" title="Refresh" onClick={refresh}>
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
                        d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                    />
                </svg>
            </IconButton>
        </div>
    </div>

    <!-- Seeds Section -->
    {#if seeds.length > 0}
        <section class="space-y-4">
            <h2
                class="flex items-center gap-2 text-lg font-semibold text-default md:text-xl"
            >
                <svg
                    class="w-5 h-5 text-accent"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                >
                    <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M19.428 15.428a2 2 0 00-1.022-.547l-2.384-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"
                    />
                </svg>
                Based on your recent listening...
            </h2>
            <div class="grid grid-cols-3 gap-3 sm:grid-cols-4 md:hidden">
                {#each seeds as seed}
                    <a
                        href="/artist/{seed.mbid}"
                        class="flex min-w-0 flex-col items-center gap-2 rounded-2xl border border-subtle bg-surface-2/60 px-2 py-3 text-center"
                        title="Impact Score: {seed.score.toFixed(1)}"
                    >
                        <div class="relative h-20 w-20 overflow-hidden rounded-full border border-subtle shadow-md">
                            <img
                                src={seed.art_sha1
                                    ? getArtUrl(seed.art_sha1, 300)
                                    : "/assets/default-artist-placeholder.svg"}
                                alt={seed.name}
                                class="h-full w-full object-cover"
                                loading="lazy"
                            />
                        </div>
                        <span class="w-full truncate text-xs text-default">{seed.name}</span>
                        <span class="text-[10px] text-subtle">{seed.play_count} plays</span>
                    </a>
                {/each}
            </div>
            <div
                class="hidden gap-4 overflow-x-auto py-4 -mx-8 px-8 scrollbar-thin scroll-pl-8 md:flex"
                on:wheel={handleScroll}
            >
                {#each seeds as seed}
                    <a
                        href="/artist/{seed.mbid}"
                        class="flex flex-col items-center gap-2 min-w-[120px] w-[120px] group"
                        title="Impact Score: {seed.score.toFixed(1)}"
                    >
                        <div
                            class="relative w-24 h-24 rounded-full overflow-hidden shadow-md border border-subtle group-hover:border-accent transition-all"
                        >
                            <img
                                src={seed.art_sha1
                                    ? getArtUrl(seed.art_sha1, 300)
                                    : "/assets/default-artist-placeholder.svg"}
                                alt={seed.name}
                                class="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity"
                                loading="lazy"
                            />
                        </div>
                        <span
                            class="text-xs text-center text-muted group-hover:text-default truncate w-full"
                            >{seed.name}</span
                        >
                        <span class="text-[10px] text-subtle"
                            >{seed.play_count} plays</span
                        >
                    </a>
                {/each}
                <div class="min-w-[1px]"></div>
            </div>
        </section>
    {/if}

    <!-- Recommended Artists -->
    {#if artists.length > 0}
        <section class="space-y-4">
            <h2 class="text-xl font-semibold text-default md:text-2xl">
                Artists you might like
            </h2>
            <div class="grid grid-cols-2 gap-4 md:hidden">
                {#each artists as artist}
                    <a
                        href="/artist/{artist.mbid}"
                        class="group relative flex min-w-0 flex-col items-center rounded-2xl border border-subtle bg-surface-2/50 p-3 text-center"
                    >
                        <div class="relative mb-3 h-28 w-28">
                            <div class="h-full w-full overflow-hidden rounded-full bg-surface-3 shadow-lg">
                                <img
                                    src={artist.art_sha1
                                        ? getArtUrl(artist.art_sha1, 300)
                                        : "/assets/default-artist-placeholder.svg"}
                                    alt={artist.name}
                                    class="h-full w-full object-cover"
                                    loading="lazy"
                                />
                            </div>
                            <div
                                class="absolute -bottom-1 -right-1 rounded-full border border-subtle bg-surface-1 px-2 py-1 text-[10px] text-subtle shadow-xs"
                                title="Recommended by {artist.support_count} similar artists"
                            >
                                +{artist.support_count}
                            </div>
                        </div>
                        <h3 class="mb-1 w-full truncate text-sm font-semibold text-default">
                            {artist.name}
                        </h3>
                        <p class="line-clamp-2 text-xs text-subtle">
                            Similar to {artist.similar_to.join(", ")}
                        </p>
                    </a>
                {/each}
            </div>
            <div
                class="hidden gap-6 overflow-x-auto py-6 -mx-8 px-8 scroll-pl-8 snap-x snap-mandatory flex-nowrap scrollbar-thin md:flex"
                on:wheel={handleScroll}
            >
                {#each artists as artist}
                    <a
                        href="/artist/{artist.mbid}"
                        class="group relative min-w-[200px] w-[200px] snap-start flex flex-col items-center text-center p-4 rounded-xl hover:bg-surface-2 transition-colors border border-transparent hover:border-subtle"
                    >
                        <div class="relative w-40 h-40 mb-4">
                            <div
                                class="w-full h-full rounded-full overflow-hidden shadow-lg bg-surface-3"
                            >
                                <img
                                    src={artist.art_sha1
                                        ? getArtUrl(artist.art_sha1, 300)
                                        : "/assets/default-artist-placeholder.svg"}
                                    alt={artist.name}
                                    class="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
                                    loading="lazy"
                                />
                            </div>
                            <!-- Consensus Badge -->
                            <div
                                class="absolute -bottom-2 -right-2 bg-surface-1 border border-subtle text-xs px-2 py-1 rounded-full shadow-xs text-subtle"
                                title="Recommended by {artist.support_count} similar artists"
                            >
                                +{artist.support_count}
                            </div>
                        </div>

                        <h3
                            class="font-semibold text-default truncate w-full mb-1"
                        >
                            {artist.name}
                        </h3>
                        <p class="text-xs text-subtle line-clamp-2 h-8">
                            Similar to {artist.similar_to.join(", ")}
                        </p>
                    </a>
                {/each}
                <div class="min-w-[1px]"></div>
            </div>
        </section>
    {/if}

    <!-- Recommended Albums -->
    {#if albums.length > 0}
        <section class="space-y-4">
            <h2 class="text-xl font-semibold text-default md:text-2xl">
                Albums you might have missed
            </h2>
            <div class="grid grid-cols-2 gap-4 md:hidden">
                {#each albums as album}
                    <div class="group relative min-w-0">
                        <div class="relative aspect-square w-full overflow-hidden rounded-xl bg-surface-2 shadow-lg">
                            <img
                                src={album.art_sha1
                                    ? getArtUrl(album.art_sha1, 300)
                                    : "/assets/default-album-placeholder.svg"}
                                alt={album.title}
                                class="h-full w-full object-cover"
                                loading="lazy"
                            />
                            <a href="/album/{album.mbid}" class="absolute inset-0 z-0" aria-label="View Album"></a>
                            <div class="absolute inset-x-0 bottom-0 z-10 flex items-center justify-center gap-2 bg-gradient-to-t from-black/85 via-black/30 to-transparent p-3">
                                <IconButton variant="primary" size="sm" title="Play Album" onClick={() => playAlbum(album)} stopPropagation={true}>
                                    <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
                                </IconButton>
                                <IconButton variant="outline" size="sm" title="Add to Queue" onClick={() => queueAlbum(album)} stopPropagation={true} className="border-white/30 bg-black/30 text-white">
                                    <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg>
                                </IconButton>
                            </div>
                        </div>
                        <div class="mt-2">
                            <a href="/album/{album.mbid}" class="block truncate text-sm font-medium leading-tight text-default hover:underline" title={album.title}>
                                {album.title}
                            </a>
                            <a href="/artist/{album.artist_mbid}" class="block truncate text-xs text-muted hover:underline" title={album.artist}>
                                {album.artist}
                            </a>
                            <p class="mt-0.5 text-[11px] text-subtle">{album.year || ""}</p>
                        </div>
                    </div>
                {/each}
            </div>
            <div
                class="hidden gap-6 overflow-x-auto py-6 -mx-8 px-8 scroll-pl-8 snap-x snap-mandatory flex-nowrap scrollbar-thin md:flex"
                on:wheel={handleScroll}
            >
                {#each albums as album}
                    <div
                        class="group relative min-w-[220px] w-[220px] snap-start"
                    >
                        <div
                            class="relative aspect-square w-full overflow-hidden rounded-md bg-surface-2 shadow-lg transition-transform duration-300 group-hover:scale-105"
                        >
                            <img
                                src={album.art_sha1
                                    ? getArtUrl(album.art_sha1, 300)
                                    : "/assets/default-album-placeholder.svg"}
                                alt={album.title}
                                class="h-full w-full object-cover"
                                loading="lazy"
                            />
                            <a
                                href="/album/{album.mbid}"
                                class="absolute inset-0 z-0"
                                aria-label="View Album"
                            ></a>

                            <!-- Overlay Actions -->
                            <div
                                class="absolute inset-0 opacity-0 transition-opacity group-hover:opacity-100 flex items-center justify-center gap-3 z-10 pointer-events-none bg-black/40 backdrop-blur-[2px]"
                            >
                                <div
                                    class="pointer-events-auto flex items-center gap-3 text-white"
                                >
                                    <IconButton
                                        variant="primary"
                                        title="Play Album"
                                        onClick={() => playAlbum(album)}
                                        stopPropagation={true}
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
                        <div class="mt-3">
                            <a
                                href="/album/{album.mbid}"
                                class="block font-medium leading-tight truncate hover:underline text-default"
                                title={album.title}
                            >
                                {album.title}
                            </a>
                            <a
                                href="/artist/{album.artist_mbid}"
                                class="block text-sm text-muted truncate hover:underline"
                                title={album.artist}
                            >
                                {album.artist}
                            </a>
                            <p class="text-xs text-subtle mt-0.5">
                                {album.year || ""}
                            </p>
                        </div>
                    </div>
                {/each}
                <div class="min-w-[1px]"></div>
            </div>
        </section>
    {/if}

    <!-- Recommended Tracks -->
    {#if tracks.length > 0}
        <section class="space-y-4">
            <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <h2 class="text-xl font-semibold text-default md:text-2xl">
                    Recommended Tracks
                </h2>
                <div class="grid grid-cols-2 gap-2 sm:flex sm:items-center">
                    <button
                        class="btn btn-primary btn-sm gap-2"
                        on:click={playAllTracks}
                    >
                        <svg
                            class="w-4 h-4"
                            fill="currentColor"
                            viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg
                        >
                        Play All
                    </button>
                    <button
                        class="btn btn-outline btn-sm gap-2"
                        on:click={queueAllTracks}
                    >
                        <svg
                            class="w-4 h-4"
                            fill="currentColor"
                            viewBox="0 0 24 24"
                            ><path
                                d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"
                            /></svg
                        >
                        Queue All
                    </button>
                </div>
            </div>

            <div class="grid grid-cols-1 gap-2">
                {#each tracks as track, i (track.id)}
                    <TrackCard
                        {track}
                        album={track.album}
                        artists={[track.artist]}
                        artwork={track.artwork}
                        showIndex={true}
                        index={i + 1}
                        showArtwork={true}
                        onPlay={() => setQueue([track as any], 0)}
                        onQueue={() => addToQueue([track as any])}
                    />
                {/each}
            </div>
        </section>
    {/if}
</div>
