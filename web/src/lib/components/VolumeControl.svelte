<script lang="ts">
    import { playerState, setVolume } from "$stores/player";

    export let showIcon = true;
    export let iconClass = "h-5 w-5 text-white/60";
    export let sliderClass = "range range-xs range-primary w-24";
    export let sliderStyle = "";
    export let containerClass = "flex items-center gap-2 group";

    let volume = 1.0;

    // Sync from store
    $: if ($playerState.volume !== null && $playerState.volume !== undefined) {
        // Store is 0-100, local is 0-1
        const newVol = $playerState.volume / 100;
        if (Math.abs(volume - newVol) > 0.01) {
            volume = newVol;
        }
    } else {
    }

    function handleInput(e: Event) {
        const val = parseFloat((e.currentTarget as HTMLInputElement).value);
        volume = val;

        // Optimistic update to store immediately for UI sync
        playerState.update((s) => ({ ...s, volume: Math.round(val * 100) }));

        // Always send volume to API for persistence (local & remote)
        setVolume(Math.round(val * 100));
        // Local: PlayerBar subscribes to store or we let the parent handle it?
        // PlayerBar handles the actual <audio>.volume binding.
        // By updating playerState.volume above, PlayerBar should react if we wire it up correctly.
    }
</script>

<div class={containerClass}>
    {#if showIcon}
        <svg
            class={iconClass}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
        >
            <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z"
            ></path>
        </svg>
    {/if}
    <input
        type="range"
        min="0"
        max="1"
        step="0.01"
        value={volume}
        on:input={handleInput}
        class="volume-slider {sliderClass}"
        style={sliderStyle}
    />
</div>
