<script lang="ts">
    import { onMount } from "svelte";
    import { fetchWithAuth, triggerScan } from "$lib/api";
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
            const res = await fetchWithAuth(url);
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

    const DEFAULT_RENDERER_ICON = "/assets/icon-renderer.svg";
    const LOCAL_RENDERER_ICON = "/assets/icon-browser.svg";

    function getRendererFallback(renderer: any): string {
        if (!renderer) return DEFAULT_RENDERER_ICON;
        if (renderer.type === "local" || renderer.udn?.startsWith("local")) {
            return LOCAL_RENDERER_ICON;
        }
        return DEFAULT_RENDERER_ICON;
    }

    function getRendererIcon(renderer: any): string {
        if (renderer?.icon_url) return renderer.icon_url;
        return getRendererFallback(renderer);
    }

    function rendererKind(renderer: any): string {
        const raw =
            renderer?.kind ||
            renderer?.type ||
            renderer?.renderer_id?.split(":")[0] ||
            "";
        if (raw === "cast" || raw === "chromecast") return "cast";
        if (raw === "upnp" || renderer?.udn?.startsWith("uuid:")) return "upnp";
        if (raw === "local" || renderer?.udn?.startsWith("local:")) return "local";
        return raw || "unknown";
    }

    function rendererKindLabel(renderer: any): string {
        const kind = rendererKind(renderer);
        if (kind === "cast") {
            const castType = renderer?.cast_type;
            if (!castType || castType === "cast") return "Cast";
            return `Cast ${castType}`;
        }
        if (kind === "upnp") return "UPnP";
        if (kind === "local") return "Local";
        return kind.toUpperCase();
    }

    function rendererKindClass(renderer: any): string {
        const kind = rendererKind(renderer);
        if (kind === "cast") {
            return "border-sky-400/40 bg-sky-500/15 text-sky-300";
        }
        if (kind === "upnp") {
            return "border-emerald-400/40 bg-emerald-500/15 text-emerald-300";
        }
        if (kind === "local") {
            return "border-zinc-400/30 bg-zinc-500/15 text-zinc-300";
        }
        return "border-subtle bg-surface-3 text-muted";
    }

    let scanStatus = "";
    let scanProgress = 0;
    let scanLogs: string[] = [];
    let isScanning = false;
    let pollInterval: any;

    async function checkScanStatus() {
        try {
            const res = await fetchWithAuth("/api/scan-status");
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
                const res = await fetchWithAuth("/api/scan-status");
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

<div class="container mx-auto max-w-5xl px-4 py-6 md:px-6 md:py-8">
    <div class="mb-6 flex flex-col gap-3 sm:mb-8 sm:flex-row sm:items-center sm:justify-between">
        <h1 class="text-2xl font-bold sm:text-3xl">Network Renderers</h1>
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
                class="mt-4 p-4 rounded-sm bg-surface-2 border border-subtle font-mono text-xs text-muted h-32 overflow-y-auto space-y-1"
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
        Discovered network media renderers.
    </p>

    <div class="grid gap-4 grid-cols-1">
        {#each renderers as r}
            <div
                class="relative rounded-xl border border-subtle bg-surface-2 p-4 shadow-lg sm:p-6"
            >
                <div class="absolute right-4 top-4 sm:right-5 sm:top-5">
                    <div class="h-12 w-12 rounded-xl bg-surface-3/70 p-2 shadow-inner sm:h-16 sm:w-16">
                        <img
                            class="h-full w-full rounded-md object-contain"
                            src={getRendererIcon(r)}
                            alt=""
                            loading="lazy"
                            on:error={(e) => {
                                (e.currentTarget as HTMLImageElement).src =
                                    getRendererFallback(r);
                            }}
                        />
                    </div>
                </div>
                <div class="mb-4 flex items-center gap-3 sm:gap-4 pr-12 sm:pr-20">
                    <div
                        class="flex h-10 w-10 items-center justify-center rounded-full bg-primary-500/20 text-primary-400 sm:h-12 sm:w-12"
                    >
                        <svg
                            xmlns="http://www.w3.org/2000/svg"
                            class="h-5 w-5 sm:h-6 sm:w-6"
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
                            class="font-bold text-base leading-tight text-default sm:text-lg"
                        >
                            {r.name}
                        </h3>
                        <div class="mt-1 flex flex-wrap items-center gap-2">
                            <span
                                class={`rounded-sm border px-2 py-0.5 text-[10px] font-semibold uppercase leading-none tracking-wide ${rendererKindClass(r)}`}
                            >
                                {rendererKindLabel(r)}
                            </span>
                            <span class="text-xs text-subtle font-mono"
                                >{r.ip || "Local"}</span
                            >
                        </div>
                    </div>
                </div>

                {#if r.udn && !r.udn.startsWith("local:")}
                    <!-- Device Info -->
                    {#if r.manufacturer || r.model_name}
                        <div class="mb-4 space-y-1 border-t border-subtle pt-4">
                            {#if r.manufacturer}
                                <div class="flex flex-col gap-1 text-sm sm:flex-row sm:justify-between">
                                    <span class="text-subtle">Manufacturer</span
                                    >
                                    <span class="text-muted"
                                        >{r.manufacturer}</span
                                    >
                                </div>
                            {/if}
                            {#if r.model_name}
                                <div class="flex flex-col gap-1 text-sm sm:flex-row sm:justify-between">
                                    <span class="text-subtle">Model</span>
                                    <span class="text-muted"
                                        >{r.model_name}</span
                                    >
                                </div>
                            {/if}
                            {#if r.renderer_id}
                                <div class="flex flex-col gap-1 text-sm sm:flex-row sm:justify-between">
                                    <span class="text-subtle">Renderer ID</span>
                                    <span
                                        class="text-muted font-mono text-xs truncate"
                                        title={r.renderer_id}
                                        >{r.renderer_id}</span
                                    >
                                </div>
                            {/if}
                            {#if r.model_number}
                                <div class="flex flex-col gap-1 text-sm sm:flex-row sm:justify-between">
                                    <span class="text-subtle">Model #</span>
                                    <span class="text-muted font-mono text-xs"
                                        >{r.model_number}</span
                                    >
                                </div>
                            {/if}
                            {#if r.serial_number}
                                <div class="flex flex-col gap-1 text-sm sm:flex-row sm:justify-between">
                                    <span class="text-subtle">Serial</span>
                                    <span class="text-muted font-mono text-xs"
                                        >{r.serial_number}</span
                                    >
                                </div>
                            {/if}
                            {#if r.firmware_version}
                                <div class="flex flex-col gap-1 text-sm sm:flex-row sm:justify-between">
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
                                            class="inline-block rounded-sm bg-surface-3 px-2 py-0.5 font-mono text-xs text-muted"
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
