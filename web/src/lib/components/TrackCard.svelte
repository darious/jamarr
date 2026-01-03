<script lang="ts">
    import IconButton from "$components/IconButton.svelte";

    // Core track data
    export let track: {
        id: number;
        title: string;
        duration_seconds?: number;
        codec?: string;
        bit_depth?: number;
        sample_rate_hz?: number;
        popularity?: number;
        bitrate?: number;
        art_sha1?: string;
        art_id?: number;
    };

    // Optional metadata
    export let artist:
        | {
              name: string;
              mbid?: string;
          }
        | undefined = undefined;

    export let album:
        | {
              name: string;
              mbid?: string;
              year?: string;
          }
        | undefined = undefined;

    export let artwork:
        | {
              sha1?: string;
              id?: number;
          }
        | undefined = undefined;

    // Display options
    export let showIndex: boolean = false;
    export let index: number | undefined = undefined;
    export let showArtwork: boolean = true;
    export let showAlbum: boolean = true;
    export let showArtist: boolean = true;
    export let showYear: boolean = true;
    export let showTechDetails: boolean = true;
    export let showPopularity: boolean = false;
    export let showBitrate: boolean = false;

    // Actions
    export let onPlay: (() => void) | undefined = undefined;
    export let onQueue: (() => void) | undefined = undefined;
    export let onAddToPlaylist: (() => void) | undefined = undefined;
    export let onClick: (() => void) | undefined = undefined;

    // Drag and drop support
    export let draggable: boolean = false;
    export let onDragStart: ((e: DragEvent) => void) | undefined = undefined;
    export let onDragOver: ((e: DragEvent) => void) | undefined = undefined;
    export let onDragEnd: ((e: DragEvent) => void) | undefined = undefined;
    export let isDragging: boolean = false;

    // Queue-specific
    export let isCurrentlyPlaying: boolean = false;
    export let isPlaying: boolean = false;

    // Helper functions
    function formatDuration(seconds?: number): string {
        if (!seconds) return "—";
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60)
            .toString()
            .padStart(2, "0");
        return `${mins}:${secs}`;
    }

    function formatPlays(count?: number): string {
        if (!count) return "";
        if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M plays`;
        if (count >= 1000) return `${(count / 1000).toFixed(1)}K plays`;
        return `${count} plays`;
    }

    function getArtworkUrl(): string {
        if (artwork?.sha1) return `/art/file/${artwork.sha1}`;
        if (artwork?.id) return `/art/${artwork.id}`;
        return "/assets/default-album-placeholder.svg";
    }

    function getAlbumUrl(): string {
        if (album?.mbid) return `/album/${album.mbid}`;
        if (artist?.name && album?.name) {
            return `/album/${encodeURIComponent(artist.name)}/${encodeURIComponent(album.name)}`;
        }
        return "#";
    }

    function getArtistUrl(): string {
        if (artist?.mbid) return `/artist/${artist.mbid}`;
        if (artist?.name) return `/artist/${encodeURIComponent(artist.name)}`;
        return "#";
    }

    $: isDisabled = track.id <= 0;
    $: gridCols = showIndex
        ? "grid-cols-[auto,auto,1fr,auto]"
        : "grid-cols-[auto,1fr,auto]";

    $: containerClass = `w-full grid ${gridCols} items-center gap-4 px-3 py-2 rounded-xl hover:bg-white/5 group transition-colors text-left border relative cursor-pointer
        ${isCurrentlyPlaying ? "bg-accent/10 border-accent border-2 shadow-[0_0_20px_var(--accent-glow)]" : "border-transparent hover:border-white/5"}
        ${isDragging ? "opacity-30 grayscale" : ""}`;

    function handleClick() {
        if (onClick) {
            onClick();
        }
    }

    function handleKeyDown(e: KeyboardEvent) {
        if (e.key === "Enter" && onClick) {
            onClick();
        }
    }
</script>

<div
    role="button"
    tabindex="0"
    class={containerClass}
    {draggable}
    on:click={handleClick}
    on:keydown={handleKeyDown}
    on:dragstart={onDragStart}
    on:dragover={onDragOver}
    on:dragend={onDragEnd}
    aria-current={isCurrentlyPlaying ? "true" : "false"}
>
    {#if isCurrentlyPlaying}
        <div
            class="absolute left-0 top-3 bottom-3 w-1 bg-accent rounded-r-md shadow-[0_0_10px_var(--accent-glow)]"
        ></div>
    {/if}
    <!-- Index -->
    {#if showIndex && index !== undefined}
        <span class="w-8 text-center text-sm text-white/40 font-mono"
            >{index}</span
        >
    {/if}

    <!-- Artwork (84px - 50% larger than 56px) -->
    {#if showArtwork}
        <div
            class="relative w-[84px] h-[84px] rounded overflow-hidden bg-surface-800 shadow-lg flex-shrink-0"
        >
            <img
                src={getArtworkUrl()}
                class="w-full h-full object-cover"
                alt="Art"
            />
            <!-- Playing Indicator -->
            {#if isCurrentlyPlaying && isPlaying}
                <div
                    class="absolute inset-0 bg-black/40 flex items-center justify-center"
                >
                    <div
                        class="loading loading-bars loading-sm text-white"
                    ></div>
                </div>
            {/if}
        </div>
    {/if}

    <!-- Info Block -->
    <div class="min-w-0 space-y-0">
        <!-- Row 1: Track Title -->
        <p
            class={`truncate text-base font-semibold ${isDisabled ? "text-white/40 line-through" : "text-white"}`}
        >
            {track.title}
        </p>

        <!-- Row 2: Artist · Album · Year -->
        <div
            class="flex items-center gap-1.5 text-sm text-white/60 leading-tight"
        >
            {#if showArtist && artist}
                <a
                    href={getArtistUrl()}
                    class="hover:text-white hover:underline cursor-pointer truncate"
                    on:click|stopPropagation={() => {}}
                >
                    {artist.name}
                </a>
            {/if}

            {#if showArtist && artist && showAlbum && album}
                <span class="text-white/40">·</span>
            {/if}

            {#if showAlbum && album}
                <a
                    href={getAlbumUrl()}
                    class="hover:text-white hover:underline cursor-pointer truncate"
                    on:click|stopPropagation={() => {}}
                >
                    {album.name}
                </a>
            {/if}

            {#if showYear && album?.year}
                <span class="text-white/40">·</span>
                <span class="text-white/50">{album.year.substring(0, 4)}</span>
            {/if}

            {#if showPopularity && track.popularity}
                <span class="text-white/40">·</span>
                <span class="text-white/50"
                    >{formatPlays(track.popularity)}</span
                >
            {/if}
        </div>
    </div>

    <!-- Right Column: Duration, Tech Details, Actions -->
    <div class="flex items-center gap-6 ml-auto">
        <!-- Duration & Tech Details -->
        <div class="flex flex-col items-end gap-0.5 text-right">
            <span class="text-sm text-white/50 tabular-nums font-mono">
                {formatDuration(track.duration_seconds)}
            </span>
            {#if showTechDetails}
                <div
                    class="flex items-center gap-2 text-xs text-white/30 uppercase tracking-wider font-medium min-h-[16px]"
                >
                    {#if track.codec}
                        <span>{track.codec}</span>
                    {/if}
                    {#if track.bit_depth && track.sample_rate_hz}
                        <span>·</span>
                        <span
                            >{track.bit_depth}bit / {Math.round(
                                track.sample_rate_hz / 1000,
                            )}kHz</span
                        >
                    {/if}
                    {#if showBitrate && track.bitrate}
                        <span>·</span>
                        <span>{Math.round(track.bitrate / 1000)}kbps</span>
                    {/if}
                </div>
            {/if}
        </div>

        <!-- Action Buttons -->
        {#if !isDisabled && (onPlay || onQueue || onAddToPlaylist)}
            <div
                class="flex items-center gap-1 opacity-30 group-hover:opacity-100 transition-opacity"
            >
                {#if onPlay}
                    <IconButton
                        variant="outline"
                        size="sm"
                        title="Play"
                        onClick={onPlay}
                        stopPropagation={true}
                    >
                        <svg
                            class="h-4 w-4"
                            fill="currentColor"
                            viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg
                        >
                    </IconButton>
                {/if}

                {#if onQueue}
                    <IconButton
                        variant="outline"
                        size="sm"
                        title="Add to Queue"
                        onClick={onQueue}
                        stopPropagation={true}
                    >
                        <svg
                            class="h-4 w-4"
                            fill="currentColor"
                            viewBox="0 0 24 24"
                            ><path
                                d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"
                            /></svg
                        >
                    </IconButton>
                {/if}

                {#if onAddToPlaylist}
                    <IconButton
                        variant="outline"
                        size="sm"
                        title="Add to Playlist"
                        onClick={onAddToPlaylist}
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
                                d="M9 13h6m-3-3v6m-9 1V7a2 2 0 012-2h6l2 2h6a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z"
                            />
                        </svg>
                    </IconButton>
                {/if}
            </div>
        {/if}
    </div>
</div>
