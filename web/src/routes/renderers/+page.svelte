<script lang="ts">
    import { onMount } from "svelte";
    import { triggerScan } from "$lib/api";
    import TabButton from "$lib/components/TabButton.svelte";

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
        <TabButton onClick={startScan} disabled={loading || isScanning}>
            {#if loading || isScanning}
                Scanning...
            {:else}
                Refresh Discovery
            {/if}
        </TabButton>
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
                class="progress progress-primary w-full h-2 bg-surface-3"
                value={scanProgress}
                max="100"
            ></progress>

            <div
                class="mt-4 p-4 rounded bg-surface-2 border border-subtle font-mono text-xs text-muted h-32 overflow-y-auto space-y-1"
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

    <p class="mb-6 text-muted">
        Discovered UPnP/DLNA media renderers on your network.
    </p>

    <div class="grid gap-4 grid-cols-1">
        {#each renderers as r}
            <div
                class="rounded-xl border border-subtle bg-surface-2 p-6 shadow-lg"
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
                    <div class="flex-1">
                        <h3
                            class="font-bold text-lg leading-tight text-default"
                        >
                            {r.name}
                        </h3>
                        <span class="text-xs text-subtle font-mono"
                            >{r.ip || "Local"}</span
                        >
                    </div>
                </div>

                {#if r.udn && !r.udn.startsWith("local:")}
                    <!-- Device Info -->
                    {#if r.manufacturer || r.model_name}
                        <div class="mb-4 space-y-1 border-t border-subtle pt-4">
                            {#if r.manufacturer}
                                <div class="flex justify-between text-sm">
                                    <span class="text-subtle">Manufacturer</span
                                    >
                                    <span class="text-muted"
                                        >{r.manufacturer}</span
                                    >
                                </div>
                            {/if}
                            {#if r.model_name}
                                <div class="flex justify-between text-sm">
                                    <span class="text-subtle">Model</span>
                                    <span class="text-muted"
                                        >{r.model_name}</span
                                    >
                                </div>
                            {/if}
                            {#if r.model_number}
                                <div class="flex justify-between text-sm">
                                    <span class="text-subtle">Model #</span>
                                    <span class="text-muted font-mono text-xs"
                                        >{r.model_number}</span
                                    >
                                </div>
                            {/if}
                            {#if r.serial_number}
                                <div class="flex justify-between text-sm">
                                    <span class="text-subtle">Serial</span>
                                    <span class="text-muted font-mono text-xs"
                                        >{r.serial_number}</span
                                    >
                                </div>
                            {/if}
                            {#if r.firmware_version}
                                <div class="flex justify-between text-sm">
                                    <span class="text-subtle">Firmware</span>
                                    <span class="text-muted font-mono text-xs"
                                        >{r.firmware_version}</span
                                    >
                                </div>
                            {/if}
                        </div>
                    {/if}

                    <!-- Capabilities -->
                    {#if r.supports_events || r.supports_gapless}
                        <div class="mb-4 flex flex-wrap gap-2">
                            {#if r.supports_events}
                                <span
                                    class="inline-flex items-center gap-1 rounded-full bg-green-500/20 px-3 py-1 text-xs font-medium text-green-600 dark:text-green-400"
                                >
                                    <svg
                                        class="h-3 w-3"
                                        fill="currentColor"
                                        viewBox="0 0 20 20"
                                    >
                                        <path
                                            fill-rule="evenodd"
                                            d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                                            clip-rule="evenodd"
                                        />
                                    </svg>
                                    Events
                                </span>
                            {/if}
                            {#if r.supports_gapless}
                                <span
                                    class="inline-flex items-center gap-1 rounded-full bg-accent/20 px-3 py-1 text-xs font-medium text-accent"
                                >
                                    <svg
                                        class="h-3 w-3"
                                        fill="currentColor"
                                        viewBox="0 0 20 20"
                                    >
                                        <path
                                            fill-rule="evenodd"
                                            d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                                            clip-rule="evenodd"
                                        />
                                    </svg>
                                    Gapless
                                </span>
                            {/if}
                        </div>
                    {/if}

                    <!-- Technical Details (collapsible) -->
                    <details class="text-sm text-muted">
                        <summary
                            class="cursor-pointer text-xs uppercase tracking-wider opacity-50 hover:opacity-100"
                            >Technical Details</summary
                        >
                        <div class="mt-2 space-y-2">
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
                            {#if r.control_url}
                                <div class="flex flex-col">
                                    <span
                                        class="text-xs uppercase tracking-wider opacity-50"
                                        >Control URL</span
                                    >
                                    <span
                                        class="font-mono text-xs truncate"
                                        title={r.control_url}
                                        >{r.control_url}</span
                                    >
                                </div>
                            {/if}
                            {#if r.location}
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
                            {/if}
                            {#if r.device_type}
                                <div class="flex flex-col">
                                    <span
                                        class="text-xs uppercase tracking-wider opacity-50"
                                        >Device Type</span
                                    >
                                    <span
                                        class="font-mono text-xs truncate"
                                        title={r.device_type}
                                        >{r.device_type}</span
                                    >
                                </div>
                            {/if}
                        </div>
                    </details>

                    <!-- Supported Formats (collapsible) -->
                    {#if r.supported_mime_types}
                        <details class="text-sm text-muted mt-2">
                            <summary
                                class="cursor-pointer text-xs uppercase tracking-wider opacity-50 hover:opacity-100"
                                >Supported Formats</summary
                            >
                            <div class="mt-2 flex flex-wrap gap-1">
                                {#each r.supported_mime_types.split(",") as mime}
                                    {#if mime.startsWith("audio/")}
                                        <span
                                            class="inline-block rounded bg-surface-3 px-2 py-0.5 font-mono text-xs text-muted"
                                            >{mime}</span
                                        >
                                    {/if}
                                {/each}
                            </div>
                        </details>
                    {/if}
                {:else}
                    <p class="italic text-sm text-muted">
                        This is your current browser session.
                    </p>
                {/if}
            </div>
        {/each}
    </div>
    {#if renderers.length === 0 && !loading}
        <div class="text-center text-subtle py-12">
            No renderers found. Make sure devices are on the same network
            subnet.
        </div>
    {/if}
</div>
