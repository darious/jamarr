<script lang="ts">
    import { onMount } from "svelte";
    import { triggerScan } from "$lib/api";

    let renderers: any[] = [];
    let loading = false;
    let error = "";

    async function fetchRenderers(refresh = false) {
        loading = true;
        error = "";
        try {
            // Pass refresh=true to force backend discovery
            const url = refresh
                ? "/api/renderers?refresh=true"
                : "/api/renderers";
            const res = await fetch(url);
            if (!res.ok) throw new Error("Failed to fetch renderers");
            renderers = await res.json();
        } catch (e) {
            error = e.message;
        } finally {
            loading = false;
        }
    }

    onMount(() => {
        fetchRenderers(false);
        checkScanStatus();
    });

    let scanStatus = "";
    let scanProgress = 0;
    let scanLogs: string[] = [];
    let isScanning = false;
    let pollInterval: any;

    async function checkScanStatus() {
        try {
            const res = await fetch("/api/scan-status");
            const data = await res.json();
            if (data.is_scanning) {
                isScanning = true;
                startPolling();
            }
        } catch (e) {
            console.error("Status check error", e);
        }
    }

    async function startScan() {
        // Trigger scan
        fetchRenderers(true);
        // Start polling
        isScanning = true;
        scanProgress = 0;
        scanLogs = [];
        startPolling();
    }

    function startPolling() {
        if (pollInterval) clearInterval(pollInterval);

        pollInterval = setInterval(async () => {
            try {
                const res = await fetch("/api/scan-status");
                const data = await res.json();
                isScanning = data.is_scanning;
                scanStatus = data.message;
                scanProgress = data.progress || 0;
                scanLogs = (data.logs || []).reverse(); // Newest first for this view style

                if (!isScanning) {
                    clearInterval(pollInterval);
                    scanStatus = "Scan complete.";
                    scanProgress = 100;
                    setTimeout(() => {
                        scanStatus = "";
                        scanProgress = 0;
                    }, 3000);
                    fetchRenderers(false); // Refresh list one last time
                }
            } catch (e) {
                console.error("Poll error", e);
            }
        }, 1000);
    }
</script>

<div class="container mx-auto max-w-5xl px-6 py-8">
    <div class="mb-8 flex items-center justify-between">
        <h1 class="text-3xl font-bold">Network Renderers</h1>
        <button
            class="btn border border-white/10 bg-white/5 hover:bg-white/10"
            on:click={startScan}
            disabled={loading || isScanning}
        >
            {#if loading || isScanning}
                Scanning...
            {:else}
                Refresh Discovery
            {/if}
        </button>
    </div>

    {#if isScanning || scanStatus}
        <div class="mb-6 space-y-2">
            <div
                class="flex justify-between text-sm text-primary-400 font-mono"
            >
                <span>{scanStatus}</span>
                <span>{scanProgress}%</span>
            </div>
            <progress
                class="progress progress-primary w-full h-2 bg-surface-700"
                value={scanProgress}
                max="100"
            ></progress>

            <div
                class="mt-4 p-4 rounded bg-black/30 font-mono text-xs text-white/50 h-32 overflow-y-auto space-y-1"
            >
                {#each scanLogs as log}
                    <div class="truncate">{log}</div>
                {/each}
            </div>
        </div>
    {/if}

    {#if error}
        <div class="alert alert-error mb-4">
            {error}
        </div>
    {/if}

    <p class="mb-6 text-white/60">
        Discovered UPnP/DLNA media renderers on your network.
    </p>

    <div class="grid gap-4 grid-cols-1">
        {#each renderers as r}
            <!-- Filter out the 'local' browser entry if we only care about network devices, but user might want to see it -->
            <div
                class="rounded-xl border border-white/10 bg-surface-800 p-6 shadow-lg"
            >
                <div class="mb-4 flex items-center gap-4">
                    <div
                        class="flex h-12 w-12 items-center justify-center rounded-full bg-primary-500/20 text-primary-400"
                    >
                        <svg
                            xmlns="http://www.w3.org/2000/svg"
                            class="h-6 w-6"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                        >
                            <path
                                stroke-linecap="round"
                                stroke-linejoin="round"
                                stroke-width="2"
                                d="M5.636 18.364a9 9 0 010-12.728m12.728 0a9 9 0 010 12.728m-9.9-2.829a5 5 0 010-7.07m7.072 0a5 5 0 010 7.07M9 12a1 1 0 112 0 1 1 0 01-2 0z"
                            />
                        </svg>
                    </div>
                    <div>
                        <h3 class="font-bold text-lg leading-tight">
                            {r.name}
                        </h3>
                        <span class="text-xs text-white/40 font-mono"
                            >{r.ip || "Local"}</span
                        >
                    </div>
                </div>

                <div class="space-y-2 text-sm text-white/60">
                    {#if r.udn && !r.udn.startsWith("local:")}
                        <div class="flex flex-col">
                            <span
                                class="text-xs uppercase tracking-wider opacity-50"
                                >UDN</span
                            >
                            <span
                                class="font-mono text-xs truncate"
                                title={r.udn}>{r.udn}</span
                            >
                        </div>
                        <div class="flex flex-col">
                            <span
                                class="text-xs uppercase tracking-wider opacity-50"
                                >Control URL</span
                            >
                            <span
                                class="font-mono text-xs truncate"
                                title={r.control_url}>{r.control_url}</span
                            >
                        </div>
                        <div class="flex flex-col">
                            <span
                                class="text-xs uppercase tracking-wider opacity-50"
                                >Location</span
                            >
                            <span
                                class="font-mono text-xs truncate"
                                title={r.location}>{r.location}</span
                            >
                        </div>
                    {:else}
                        <p class="italic">
                            This is your current browser session.
                        </p>
                    {/if}
                </div>
            </div>
        {/each}
    </div>
    {#if renderers.length === 0 && !loading}
        <div class="text-center text-white/40 py-12">
            No renderers found. Make sure devices are on the same network
            subnet.
        </div>
    {/if}
</div>
