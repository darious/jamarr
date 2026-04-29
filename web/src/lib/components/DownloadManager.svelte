<script lang="ts">
    import { downloadStore, type DownloadJob } from "$stores/downloads";
    import { slide } from "svelte/transition";

    let activeJobs: DownloadJob[] = [];
    let isExpanded = true;

    $: activeJobs = Object.values(
        $downloadStore as Record<string, DownloadJob>,
    ).filter(
        (job) => true, // Show all jobs
    );

    $: hasJobs = activeJobs.length > 0;

    function toggle() {
        isExpanded = !isExpanded;
    }

    function cancel(id: string) {
        const job = $downloadStore[id];
        if (job && job.abortController) {
            job.abortController.abort();
            downloadStore.updateJob(id, { status: "cancelled", progress: 0 });
        }
    }
</script>

{#if hasJobs}
    <div
        class="fixed bottom-28 right-6 z-[60] w-80 rounded-lg border border-subtle bg-surface-1 shadow-2xl overflow-hidden"
        transition:slide
    >
        <button
            class="w-full flex items-center justify-between bg-surface-2 px-4 py-2 border-b border-subtle cursor-pointer hover:bg-surface-3 transition-colors text-left"
            on:click={toggle}
            type="button"
        >
            <div class="flex items-center gap-2">
                <div
                    class="loading loading-spinner loading-xs text-accent"
                ></div>
                <span class="text-sm font-medium"
                    >Downloading ({activeJobs.length})</span
                >
            </div>
            <div class="text-muted hover:text-default">
                <svg
                    class="h-4 w-4 transform transition-transform {isExpanded
                        ? 'rotate-180'
                        : ''}"
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
            </div>
        </button>

        {#if isExpanded}
            <div class="max-h-60 overflow-y-auto p-2 space-y-2">
                {#each activeJobs as job (job.id)}
                    <div
                        class="rounded-sm bg-surface-base p-2 text-xs border-l-2 {job.status ===
                        'error'
                            ? 'border-red-500'
                            : job.status === 'completed'
                              ? 'border-green-500'
                              : 'border-accent'}"
                    >
                        <div class="flex justify-between items-start mb-1">
                            <span class="font-medium truncate max-w-[180px]"
                                >{job.name}</span
                            >
                            <div class="flex gap-2">
                                {#if job.status === "downloading" || job.status === "pending"}
                                    <button
                                        class="text-red-400 hover:text-red-500"
                                        on:click|stopPropagation={() =>
                                            cancel(job.id)}
                                    >
                                        Cancel
                                    </button>
                                {:else}
                                    <button
                                        class="text-subtle hover:text-default"
                                        on:click|stopPropagation={() =>
                                            downloadStore.removeJob(job.id)}
                                    >
                                        ✕
                                    </button>
                                {/if}
                            </div>
                        </div>
                        {#if job.status === "error"}
                            <div class="text-red-400 mb-1">
                                {job.error || "Failed"}
                            </div>
                        {:else}
                            <div class="flex justify-between text-muted mb-1">
                                <span>
                                    {#if job.status === "pending"}
                                        Queued
                                    {:else if job.status === "completed"}
                                        Done
                                    {:else}
                                        {Math.round(job.progress)}%
                                    {/if}
                                </span>
                                <span
                                    >{job.completedFiles} of {job.totalFiles} files</span
                                >
                            </div>
                            <div
                                class="h-1.5 w-full rounded-full bg-surface-3 overflow-hidden mb-2"
                            >
                                <div
                                    class="h-full {job.status === 'completed'
                                        ? 'bg-green-500'
                                        : job.status === 'pending'
                                          ? 'bg-surface-3'
                                          : 'bg-accent'} transition-all duration-300"
                                    style="width: {job.progress}%"
                                ></div>
                            </div>

                            {#if job.currentTracks && job.currentTracks.length > 0}
                                <div class="space-y-1 mt-2">
                                    {#each job.currentTracks as track}
                                        <div
                                            class="text-[10px] text-muted truncate flex items-center gap-1"
                                        >
                                            <div
                                                class="w-1.5 h-1.5 rounded-full bg-accent animate-pulse"
                                            ></div>
                                            {track}
                                        </div>
                                    {/each}
                                </div>
                            {/if}

                            {#if job.totalFiles - job.completedFiles - job.activeFiles > 0}
                                <div
                                    class="text-[10px] text-subtle mt-1 pl-2.5"
                                >
                                    + {job.totalFiles -
                                        job.completedFiles -
                                        job.activeFiles} files waiting in queue
                                </div>
                            {/if}
                        {/if}
                    </div>
                {/each}
            </div>
            {#if !activeJobs.some((j) => j.status === "downloading" || j.status === "pending") && Object.values($downloadStore).length > 0}
                <div
                    class="bg-surface-2 p-2 border-t border-subtle flex justify-center"
                >
                    <button
                        class="text-xs text-muted hover:text-white transition-colors"
                        on:click={() => downloadStore.clearCompleted()}
                    >
                        Clear All & Close
                    </button>
                </div>
            {/if}
        {/if}
    </div>
{/if}
