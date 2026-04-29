<script lang="ts">
    import { goto } from "$app/navigation";
    import IconButton from "$components/IconButton.svelte";
    import ArtistLinks from "$components/ArtistLinks.svelte";
    import { getArtUrl } from "$lib/api";

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
        plays?: number;
    };

    // Optional metadata
    // Optional metadata
    export let artists:
        | {
              name: string;
              mbid?: string;
          }[]
        | undefined = undefined;

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
              mb_release_id?: string;
              year?: string;
          }
        | undefined = undefined;

    export let artwork:
        | {
              sha1?: string;
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
    export let onRemove: (() => void) | undefined = undefined;
    export let onClick: (() => void) | undefined = undefined;
    export let onNavigate: (() => void) | undefined = undefined;

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
        if (artwork?.sha1) return getArtUrl(artwork.sha1, 100);
        return "/assets/default-album-placeholder.svg";
    }

    function getAlbumUrl(): string {
        if (album?.mb_release_id) return `/album/${album.mb_release_id}`;
        return "#";
    }

    function getArtistUrl(a: { name: string; mbid?: string }): string {
        if (a.mbid) return `/artist/${a.mbid}`;
        if (a.name) return `/artist/${encodeURIComponent(a.name)}`;
        return "#";
    }

    $: isDisabled = track.id <= 0;
    $: gridCols = showIndex
        ? "auto auto 1fr auto"
        : "auto 1fr auto";

    $: containerClass = `w-full grid items-center gap-2 px-2 py-2 rounded-xl hover:bg-surface-2 group transition-colors text-left border relative cursor-pointer sm:gap-4 sm:px-3
        ${isCurrentlyPlaying ? "bg-accent/10 border-accent border-2 shadow-[0_0_20px_var(--accent-glow)]" : "border-transparent hover:border-subtle"}
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
    style="grid-template-columns: {gridCols}"
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
        <span class="w-6 text-center text-xs text-subtle font-mono sm:w-8 sm:text-sm"
            >{index}</span
        >
    {/if}

    <!-- Artwork (84px - 50% larger than 56px) -->
    {#if showArtwork}
        <div
            class="relative h-14 w-14 flex-shrink-0 overflow-hidden rounded-sm bg-surface-800 shadow-lg sm:h-[84px] sm:w-[84px]"
        >
            <img
                src={getArtworkUrl()}
                class="w-full h-full object-cover"
                alt="Art"
                loading="lazy"
                decoding="async"
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
        <a
            href={getAlbumUrl()}
            class={`block truncate text-sm font-semibold transition-colors sm:text-base ${isDisabled ? "text-subtle line-through cursor-default" : "text-default hover:text-primary-500 hover:underline cursor-pointer"}`}
            on:click|preventDefault|stopPropagation={(e) => {
                const url = getAlbumUrl();
                if (url && url !== "#") {
                    if (onNavigate) onNavigate();
                    goto(url);
                }
            }}
        >
            {track.title}
        </a>

        <!-- Row 2: Artist -->
        {#if showArtist}
            <div class="truncate text-xs leading-tight text-muted sm:text-sm">
                <ArtistLinks
                    {artists}
                    {artist}
                    linkClass="hover:text-default hover:underline cursor-pointer"
                    separatorClass="text-subtle"
                    {onNavigate}
                />
            </div>
        {/if}

        <!-- Row 3: Album · Year -->
        {#if (showAlbum && album) || (showPopularity && track.popularity)}
            <div
                class="flex items-center gap-1.5 truncate text-xs leading-tight text-subtle sm:text-sm"
            >
                {#if showAlbum && album}
                    <a
                        href={getAlbumUrl()}
                        class="hover:text-default hover:underline cursor-pointer truncate"
                        on:click|preventDefault|stopPropagation={(e) => {
                            const url = getAlbumUrl();
                            if (url && url !== "#") {
                                if (onNavigate) onNavigate();
                                goto(url);
                            }
                        }}
                    >
                        {album.name}
                    </a>
                {/if}

                {#if showAlbum && album && showYear && album?.year}
                    <span class="text-subtle">·</span>
                    <span class="text-muted">{album.year.substring(0, 4)}</span>
                {/if}

                {#if showPopularity && track.popularity}
                    {#if showAlbum && album}
                        <span class="text-subtle">·</span>
                    {/if}
                    <span class="text-muted"
                        >{formatPlays(track.popularity)}</span
                    >
                {/if}
            </div>
        {/if}
    </div>

    <!-- Right Column: Duration, Tech Details, Actions -->
    <div class="ml-auto flex items-center gap-2 sm:gap-6">
        <!-- Duration & Tech Details -->
        <div class="flex flex-col items-end gap-0.5 text-right">
            <span class="text-xs text-subtle tabular-nums font-mono sm:text-sm">
                {formatDuration(track.duration_seconds)}
            </span>
            {#if showTechDetails}
                <div
                    class="hidden min-h-[16px] items-center gap-2 text-xs font-medium uppercase tracking-wider text-subtle sm:flex"
                >
                    {#if track.plays && track.plays > 0}
                        {#if track.id > 0}
                            <a
                                class="inline-flex items-center gap-1 text-muted hover:text-default transition-colors"
                                href={`/history?track_id=${encodeURIComponent(track.id)}&track_name=${encodeURIComponent(track.title)}`}
                                on:click|stopPropagation={() => {}}
                                title={`${track.plays} plays`}
                                aria-label={`${track.plays} plays`}
                            >
                                <svg
                                    class="h-3.5 w-3.5 opacity-80"
                                    viewBox="0 0 24 24"
                                    fill="none"
                                    stroke="currentColor"
                                    stroke-width="1.8"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                    aria-hidden="true"
                                >
                                    <path
                                        d="M14 3v10.5a2.5 2.5 0 1 1-1-2V6h6V3z"
                                    />
                                    <circle cx="12" cy="18" r="2.5" />
                                    <path d="M3.5 8.5l3-3 2 2 4.5-4.5" />
                                    <path d="M13 3h7" />
                                </svg>
                                <span class="text-xs font-medium"
                                    >{track.plays}</span
                                >
                            </a>
                        {:else}
                            <span
                                class="inline-flex items-center gap-1 text-muted"
                                title={`${track.plays} plays`}
                            >
                                <svg
                                    class="h-3.5 w-3.5 opacity-80"
                                    viewBox="0 0 24 24"
                                    fill="none"
                                    stroke="currentColor"
                                    stroke-width="1.8"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                    aria-hidden="true"
                                >
                                    <path
                                        d="M14 3v10.5a2.5 2.5 0 1 1-1-2V6h6V3z"
                                    />
                                    <circle cx="12" cy="18" r="2.5" />
                                    <path d="M3.5 8.5l3-3 2 2 4.5-4.5" />
                                    <path d="M13 3h7" />
                                </svg>
                                <span class="text-xs font-medium"
                                    >{track.plays}</span
                                >
                            </span>
                        {/if}
                    {/if}
                    {#if track.codec}
                        {#if track.plays && track.plays > 0}
                            <span>·</span>
                        {/if}
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
                class="flex items-center gap-1 opacity-100 transition-opacity sm:opacity-30 sm:group-hover:opacity-100"
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

                {#if onRemove}
                    <IconButton
                        variant="outline"
                        size="sm"
                        title="Remove from Playlist"
                        onClick={onRemove}
                        stopPropagation={true}
                        className="hover:text-red-400 hover:border-red-400"
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
                                d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                            />
                        </svg>
                    </IconButton>
                {/if}
            </div>
        {/if}
    </div>
</div>
