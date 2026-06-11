<script lang="ts">
    import { fade, scale } from "svelte/transition";
    import { createEventDispatcher } from "svelte";
    import {
        setChartOverride,
        deleteChartOverride,
        type ChartAlbum,
    } from "$lib/api";

    export let entry: ChartAlbum | null = null;
    export let visible = false;

    const dispatch = createEventDispatcher();

    let mbidInput = "";
    let saving = false;
    let error = "";

    $: if (visible && entry) {
        mbidInput = entry.overridden ? entry.release_group_mbid || "" : "";
        error = "";
    }

    function close() {
        visible = false;
        dispatch("close");
    }

    async function save() {
        if (!entry || !mbidInput.trim()) return;
        saving = true;
        error = "";
        try {
            await setChartOverride(entry.artist, entry.title, mbidInput.trim());
            dispatch("saved");
            close();
        } catch (e) {
            error = e instanceof Error ? e.message : "Failed to save override";
        } finally {
            saving = false;
        }
    }

    async function removeOverride() {
        if (!entry) return;
        saving = true;
        error = "";
        try {
            await deleteChartOverride(entry.artist, entry.title);
            dispatch("saved");
            close();
        } catch (e) {
            error =
                e instanceof Error ? e.message : "Failed to remove override";
        } finally {
            saving = false;
        }
    }
</script>

{#if visible && entry}
    <div
        class="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-xs p-4 cursor-pointer"
        transition:fade
        on:click|self={close}
        role="button"
        tabindex="0"
        on:keydown={(e) => e.key === "Escape" && close()}
    >
        <div
            class="bg-surface-50 border border-white/10 rounded-2xl w-full max-w-md shadow-2xl overflow-hidden flex flex-col"
            transition:scale
        >
            <div
                class="p-4 border-b border-white/10 flex justify-between items-center"
            >
                <h2 class="text-lg font-bold">Fix MusicBrainz Match</h2>
                <button
                    class="btn btn-ghost btn-sm btn-circle"
                    aria-label="Close"
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

            <div class="p-4 flex flex-col gap-3">
                <div class="text-sm text-white/70">
                    <span class="font-medium text-white">{entry.title}</span>
                    — {entry.artist}
                </div>
                {#if entry.release_group_mbid}
                    <div class="text-xs text-white/50 break-all">
                        Current match: {entry.release_group_mbid}
                        {#if entry.overridden}(manual){/if}
                    </div>
                {:else}
                    <div class="text-xs text-white/50">Currently unmatched</div>
                {/if}
                <input
                    type="text"
                    class="input input-sm w-full bg-white/5 border-white/10 focus:border-primary-500"
                    placeholder="Release group MBID or MusicBrainz URL"
                    bind:value={mbidInput}
                    on:keydown={(e) => e.key === "Enter" && save()}
                />
                {#if error}
                    <div class="text-xs text-error-500">{error}</div>
                {/if}
            </div>

            <div
                class="p-4 border-t border-white/10 bg-white/5 flex justify-between items-center"
            >
                {#if entry.overridden}
                    <button
                        class="btn btn-sm btn-ghost text-error-500"
                        disabled={saving}
                        on:click={removeOverride}
                    >
                        Remove Override
                    </button>
                {:else}
                    <span></span>
                {/if}
                <button
                    class="btn btn-sm variant-filled-primary"
                    disabled={saving || !mbidInput.trim()}
                    on:click={save}
                >
                    {#if saving}
                        <span class="loading loading-spinner loading-xs"></span>
                    {/if}
                    Save
                </button>
            </div>
        </div>
    </div>
{/if}
