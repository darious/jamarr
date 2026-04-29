<script lang="ts">
    import { onMount, onDestroy, afterUpdate } from "svelte";
    import {
        fetchWithAuth,
        triggerFilesystemScan,
        triggerMetadataScan,
        triggerFullScan,
        triggerPrune,
        cancelScan,
        fetchArtists,
        triggerMissingAlbumsScan,
        triggerOptimize,
        syncLastfmScrobbles,
    } from "$lib/api";
    import { getAccessToken, refreshAccessToken } from "$lib/stores/auth";
    import TabButton from "$lib/components/TabButton.svelte";
    import Checkbox from "$lib/components/Checkbox.svelte";

    interface ScanStats {
        scanned: number;
        total: number;
        percentage: number;
        message: string;
        phase: string;
        completed: boolean;
        completedStatus: string;
        api_stats?: Record<string, number>;
        processed_stats?: {
            tracks?: number;
            albums?: number;
            artists?: number;
            artists_metadata?: number;
        };
        categories?: Array<{
            name: string;
            missing: number;
            searched: number;
            hits: number;
            misses: number;
            success_rate: string;
        }>;
        // Legacy support
        stage_metrics?: Record<
            string,
            {
                missing: number;
                searched: number;
                hits: number;
                misses: number;
            }
        >;
    }

    let status = "Idle";
    let isRunning = false;
    let stats: ScanStats = {
        scanned: 0,
        total: 0,
        percentage: 0,
        message: "",
        phase: "",
        completed: false,
        completedStatus: "",

        processed_stats: {},
        categories: [],
    };
    let logs: { timestamp: number; message: string }[] = [];
    let logContainer: HTMLElement;

    let forceRescan = false;
    let scanPath = "";
    let artistFilter = "";
    let mbidFilter = "";
    let missingOnly = false;
    let runFilesystem = false;
    let doMetadata = false;
    let doBio = false;
    let doArtwork = false;
    let doSpotifyArtwork = false;
    let doTopTracks = false;
    let doSingles = false;
    let doSimilarArtists = false;
    let doAlbumMetadata = false;

    // doLinks removed
    let doMissingAlbums = false;
    let scanAll = false;
    let artistOptions: string[] = [];
    let artistsLoaded = false;
    let queueActive = false;
    let taskQueue: { label: string; start: () => Promise<void> }[] = [];
    let startTimestamp = 0;

    let eventSource: EventSource | undefined;
    let lastfmEventSource: EventSource | undefined;

    onMount(async () => {
        await refreshAccessToken();
        const token = getAccessToken();
        const tokenParam = token ? `?access_token=${encodeURIComponent(token)}` : "";

        // Connect to SSE
        eventSource = new EventSource(`/api/library/events${tokenParam}`);

        eventSource.onopen = () => {
            addLog("Connected to scan server.");
        };

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleEvent(data);
            } catch (e) {
                // checking for initial connection comment or keepalive
                if (event.data.includes("connected")) return;
                console.error("Failed to parse SSE event", e);
            }
        };

        eventSource.onerror = (err) => {
            // addLog("Connection lost. Retrying...");
            // EventSource auto-retries, but we might want to know.
        };

        // Connect to Last.fm SSE
        lastfmEventSource = new EventSource(`/api/lastfm/events${tokenParam}`);

        lastfmEventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === "log") {
                    addLog(data.message);
                } else if (data.type === "start") {
                    addLog("Starting Last.fm sync...");
                } else if (data.type === "complete") {
                    addLog(
                        `Last.fm sync finished: ${data.status}${
                            data.error ? ` (${data.error})` : ""
                        }`,
                    );
                }
            } catch (e) {
                if (event.data.includes("connected")) return;
                console.error("Failed to parse Last.fm SSE event", e);
            }
        };

        // Get initial status
        try {
            const res = await fetchWithAuth("/api/library/status");
            if (res.ok) {
                const data = await res.json();
                status = data.status;
                isRunning = data.is_running;

                // Load stats from API response
                if (data.processed) {
                    stats.processed_stats = data.processed;
                }
                if (data.api_requests) {
                    stats.api_stats = data.api_requests;
                }

                // Convert categories or stage_metrics to categories format
                if (data.categories && data.categories.length > 0) {
                    stats.categories = data.categories;
                } else if (data.stage_metrics) {
                    stats.categories = convertStageMetricsToCategories(
                        data.stage_metrics,
                    );
                }

                if (data.music_path && !scanPath) {
                    scanPath = data.music_path;
                    if (scanPath && !scanPath.endsWith("/")) {
                        scanPath += "/";
                    }
                }
            }
        } catch (e) {}

        // Preload artist list for dropdown
        try {
            const artists = await fetchArtists();
            artistOptions = artists
                .map((a) => a.name)
                .filter(Boolean)
                .sort((a, b) => a.localeCompare(b));
            artistsLoaded = true;
        } catch (e) {
            addLog(`Failed to load artists for filter: ${e}`);
            artistsLoaded = true;
        }
    });

    onDestroy(() => {
        if (eventSource) {
            eventSource.close();
        }
    });

    let isUserScrolled = false;

    afterUpdate(() => {
        if (logContainer && !isUserScrolled) {
            logContainer.scrollTop = 0;
        }
    });

    function handleScroll() {
        if (!logContainer) return;
        // Check if we are close to the top (tolerance of 10px)
        isUserScrolled = logContainer.scrollTop > 10;
    }

    // Convert stage_metrics to categories format
    function convertStageMetricsToCategories(
        stage_metrics: Record<string, any>,
    ): Array<any> {
        if (!stage_metrics) return [];
        return Object.entries(stage_metrics).map(([name, metrics]) => ({
            name,
            missing: metrics.missing || 0,
            searched: metrics.searched || 0,
            hits: metrics.hits || 0,
            misses: metrics.misses || 0,
            success_rate:
                metrics.missing > 0
                    ? `${Math.round((metrics.hits / metrics.missing) * 100)}%`
                    : "N/A",
        }));
    }

    function handleEvent(data: any) {
        if (data.type === "status") {
            status = data.status;
            if (data.stats && Object.keys(data.stats).length > 0) {
                stats = { ...stats, ...data.stats };
            }
        } else if (data.type === "progress") {
            status = "Running";
            isRunning = true;
            if (!startTimestamp) startTimestamp = Date.now();
            stats = {
                scanned: data.current,
                total: data.total,
                percentage: data.percentage,
                message: data.message,
                phase: data.phase || stats.phase,
                completed: false,
                completedStatus: "",
                api_stats: data.api_stats || stats.api_stats || {},
                processed_stats:
                    data.processed_stats || stats.processed_stats || {},
                categories:
                    data.categories ||
                    (data.stage_metrics
                        ? convertStageMetricsToCategories(data.stage_metrics)
                        : stats.categories) ||
                    [],
                stage_metrics: data.stage_metrics || stats.stage_metrics || {},
            };
        } else if (data.type === "log") {
            addLog(data.message);
        } else if (data.type === "start") {
            status = "Running";
            isRunning = true;
            if (!startTimestamp) startTimestamp = Date.now();
            stats.phase = data.phase || stats.phase;
            if (!logs.length || !isRunning) {
                logs = [];
            }
            addLog(
                `Started ${data.mode}${
                    data.phase ? ` (${data.phase})` : ""
                }...`,
            );
            stats.completed = false;
            stats.completedStatus = "";
        } else if (data.type === "complete") {
            status = data.status === "success" ? "Idle" : "Error";
            isRunning = queueActive ? true : false;
            addLog(
                `Scan finished: ${data.status}${
                    data.error ? ` (${data.error})` : ""
                }`,
            );
            stats.completed = true;
            stats.completedStatus = data.status;
            if (queueActive) {
                runNextTask();
            } else {
                isRunning = false;
                startTimestamp = 0;
            }
        }
    }

    function addLog(msg: string) {
        logs = [{ timestamp: Date.now(), message: msg }, ...logs];
        // Keep max logs
        if (logs.length > 500) logs = logs.slice(0, 500);
    }

    function buildTasks() {
        taskQueue = [];
        const pathValue = scanPath?.trim();
        const wantsMetadata =
            doMetadata ||
            doBio ||
            doArtwork ||
            doSpotifyArtwork ||
            doTopTracks ||
            doSingles ||
            doSimilarArtists ||
            doAlbumMetadata;

        if (runFilesystem && wantsMetadata) {
            taskQueue.push({
                label: "Full Scan (Filesystem + Metadata)",
                start: () =>
                    triggerFullScan({
                        force: forceRescan,
                        path: pathValue || undefined,
                        artistFilter: artistFilter || undefined,
                        mbidFilter: mbidFilter || undefined,
                        missingOnly,
                        fetchMetadata: doMetadata,
                        fetchBio: doBio,
                        fetchArtwork: doArtwork,
                        fetchSpotifyArtwork: doSpotifyArtwork,
                        // fetchLinks implicit in backend logic for full scan or metadata
                        refreshTopTracks: doTopTracks,
                        refreshSingles: doSingles,
                        fetchSimilarArtists: doSimilarArtists,
                        fetchAlbumMetadata: doAlbumMetadata,
                    }),
            });
        } else {
            if (runFilesystem) {
                taskQueue.push({
                    label: "Filesystem",
                    start: () =>
                        triggerFilesystemScan({
                            force: forceRescan,
                            path: pathValue || undefined,
                        }),
                });
            }

            if (wantsMetadata) {
                taskQueue.push({
                    label: "Metadata",
                    start: () =>
                        triggerMetadataScan({
                            path: pathValue || undefined,
                            artistFilter: artistFilter || undefined,
                            mbidFilter: mbidFilter || undefined,
                            missingOnly,
                            fetchMetadata: doMetadata,
                            fetchBio: doBio,
                            fetchArtwork: doArtwork,
                            fetchSpotifyArtwork: doSpotifyArtwork,
                            // fetchLinks removed to rely on backend default (True)
                            refreshTopTracks: doTopTracks,
                            refreshSingles: doSingles,
                            fetchSimilarArtists: doSimilarArtists,
                            fetchAlbumMetadata: doAlbumMetadata,
                        }),
                });
            }
        }

        if (doMissingAlbums) {
            taskQueue.push({
                label: "Missing Albums",
                start: () =>
                    triggerMissingAlbumsScan(
                        mbidFilter || undefined,
                        artistFilter || undefined,
                        pathValue || undefined,
                    ),
            });
        }
    }

    function runNextTask() {
        if (!taskQueue.length) {
            queueActive = false;
            isRunning = false;
            startTimestamp = 0;
            return;
        }
        const next = taskQueue.shift();
        if (!next) {
            queueActive = false;
            isRunning = false;
            startTimestamp = 0;
            return;
        }
        addLog(`Starting ${next.label}...`);
        next.start().catch((e) => {
            addLog(`Error starting ${next.label}: ${e}`);
            queueActive = false;
            isRunning = false;
            startTimestamp = 0;
        });
    }

    async function startCombined() {
        if (isRunning || queueActive) {
            addLog("A scan is already running.");
            return;
        }
        buildTasks();
        if (!taskQueue.length) {
            addLog("Nothing selected to run.");
            return;
        }
        queueActive = true;
        startTimestamp = 0;
        logs = [];
        runNextTask();
    }

    async function startPrune() {
        if (
            !confirm(
                "Are you sure you want to prune the library? This will delete database entries for missing files.",
            )
        )
            return;
        try {
            await triggerPrune();
        } catch (e) {
            addLog(`Error starting prune: ${e}`);
        }
    }

    async function startOptimize() {
        if (isRunning) return;
        if (
            !confirm(
                "Run database optimization (VACUUM, ANALYZE)? This may take a while and lock the database.",
            )
        )
            return;

        try {
            status = "Optimizing...";
            isRunning = true;
            addLog("Starting database optimization...");
            await triggerOptimize();
            addLog("Database optimization completed.");
        } catch (e) {
            addLog(`Error optimizing DB: ${e}`);
        } finally {
            isRunning = false;
            status = "Idle";
        }
    }

    async function startLastfmSync() {
        if (isRunning) return;

        try {
            status = "Syncing Last.fm...";
            isRunning = true;
            addLog("Starting Last.fm scrobble sync and matching...");

            const result = await syncLastfmScrobbles({
                fetch_new: true,
                rematch_all: false,
            });

            addLog(
                `✅ Sync complete: ${result.fetched} fetched, ${result.matched} matched, ${result.unmatched} unmatched`,
            );
        } catch (e) {
            addLog(`Error syncing Last.fm: ${e}`);
        } finally {
            isRunning = false;
            status = "Idle";
        }
    }

    async function startFull() {
        return startCombined();
    }

    async function handleCancel() {
        await cancelScan();
    }

    function toggleScanAll() {
        if (scanAll) {
            runFilesystem = true;
            doMetadata = true;
            doBio = true;
            doArtwork = true;
            doSpotifyArtwork = false; // By default don't enable fallback unless explicit? Or enable it?
            // User requirement: "looking for soptify artwork should NEVER run on all ariists... even when missing only is unchecked"
            // Wait, logic says: "looking for soptify artwork should NEVER run on all ariists" -> this implies it's a fallback mechanism.
            // But here we are just toggling the checkbox.
            // If I check Scan All, should I check Spotify Art?
            // Usually "All" means all available options.
            // But user said: "when we so scan all, we should do the spotofy check AFTER the fanart.tv check"
            // So enabling it is fine, the backend handles the "if missing" logic.
            // However, "looking for soptify artwork should NEVER run on all ariists" means even if I strictly say "fetch spotify art",
            // the backend should still check if art exists first?
            // Yes, user said: "we should only check spotify IF we dont have a artistthumb for that artist... so we need to check that first"
            // So it is safe to enable the flag, logic is in backend.
            doSpotifyArtwork = true;
            doTopTracks = true;
            doSingles = true;
            doSimilarArtists = true;
            doAlbumMetadata = true;
            // doMissingAlbums remains separate as requested
        } else {
            runFilesystem = false;
            doMetadata = false;
            doBio = false;
            doArtwork = false;
            doSpotifyArtwork = false;
            doTopTracks = false;
            doSingles = false;
            doSimilarArtists = false;
            doAlbumMetadata = false;
        }
    }

    function updateScanAllState() {
        if (
            runFilesystem &&
            doMetadata &&
            doBio &&
            doArtwork &&
            doSpotifyArtwork &&
            doTopTracks &&
            doSingles &&
            doSimilarArtists &&
            doAlbumMetadata
        ) {
            scanAll = true;
        } else {
            scanAll = false;
        }
    }
</script>

<div
    class="container mx-auto p-6 max-w-6xl text-default min-h-[calc(100vh-80px)]"
>
    <div class="flex items-center justify-between mb-8">
        <h1 class="text-3xl font-bold font-display tracking-tight">
            Library Settings
        </h1>
        <div
            class="badge badge-lg {isRunning ? 'badge-primary' : 'badge-ghost'}"
        >
            {status}
        </div>
    </div>

    <div class="space-y-6">
        <!-- Status + Logs -->
        <div class="space-y-4">
            <div
                class="card bg-surface-2 border border-subtle p-6 backdrop-blur-xs"
            >
                <div class="flex justify-between items-start gap-4">
                    <div class="flex flex-col gap-1">
                        <span
                            class="text-xs uppercase tracking-wide text-primary"
                        >
                            {stats.phase || (isRunning ? "running" : "idle")}
                        </span>
                        <span class="text-base font-semibold text-default">
                            {stats.message ||
                                (stats.completed ? "Done" : "Ready")}
                        </span>
                        <div class="text-xs text-muted flex items-center gap-3">
                            <span
                                >Progress: {stats.scanned}/{stats.total ||
                                    "?"}</span
                            >
                            <span
                                >Elapsed: {startTimestamp
                                    ? Math.max(
                                          0,
                                          Math.round(
                                              (Date.now() - startTimestamp) /
                                                  1000,
                                          ),
                                      ) + "s"
                                    : "0s"}</span
                            >
                            <span
                                >ETA: {stats.total > 0 && stats.percentage > 0
                                    ? Math.max(
                                          0,
                                          Math.round(
                                              ((100 - stats.percentage) *
                                                  (Date.now() -
                                                      startTimestamp)) /
                                                  Math.max(
                                                      stats.percentage,
                                                      1,
                                                  ) /
                                                  1000,
                                          ),
                                      ) + "s"
                                    : "--"}</span
                            >
                        </div>
                    </div>
                    <div class="flex flex-col items-end text-right">
                        <span class="text-xs font-mono text-primary"
                            >{Math.round(stats.percentage)}%</span
                        >
                        {#if isRunning}
                            <TabButton
                                className="text-red-400 hover:text-red-300 !border-red-500/0 hover:!border-red-400"
                                onClick={handleCancel}
                            >
                                Cancel
                            </TabButton>
                        {/if}
                    </div>
                </div>
                <progress
                    class="progress progress-primary w-full mt-4"
                    value={stats.percentage}
                    max="100"
                ></progress>
                {#if stats.completed}
                    <div
                        class="mt-3 flex items-center justify-between text-xs text-muted bg-surface-3 rounded-lg px-3 py-2 border border-subtle"
                    >
                        <span>Scan complete ({stats.completedStatus})</span>
                        <TabButton
                            className="text-muted hover:text-default"
                            onClick={() => {
                                stats.completed = false;
                                stats.completedStatus = "";
                            }}
                        >
                            Dismiss
                        </TabButton>
                    </div>
                {/if}
            </div>

            <!-- API & Processed Stats -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                <!-- Processed Counts -->
                <div
                    class="card bg-surface-2 border border-subtle p-4 md:col-span-1"
                >
                    <h3
                        class="text-xs uppercase tracking-wide text-subtle mb-3"
                    >
                        Processed Items
                    </h3>
                    <div class="flex gap-6">
                        <div class="flex flex-col">
                            <span
                                class="text-2xl font-bold font-display text-default"
                                >{stats.processed_stats?.tracks || 0}</span
                            >
                            <span class="text-xs text-subtle">Tracks</span>
                        </div>
                        <div class="flex flex-col">
                            <span
                                class="text-2xl font-bold font-display text-default"
                                >{stats.processed_stats?.albums || 0}</span
                            >
                            <span class="text-xs text-subtle">Albums</span>
                        </div>
                        <div class="flex flex-col">
                            <span
                                class="text-2xl font-bold font-display text-default"
                                >{stats.processed_stats?.artists || 0}</span
                            >
                            <span class="text-xs text-subtle">Artists</span>
                        </div>
                        <div class="flex flex-col">
                            <span
                                class="text-2xl font-bold font-display text-default"
                                >{stats.processed_stats?.artists_metadata ||
                                    0}</span
                            >
                            <span class="text-xs text-subtle"
                                >Artist Metadata</span
                            >
                        </div>
                    </div>
                </div>

                <!-- API Hits -->
                <div
                    class="card bg-surface-2 border border-subtle p-4 md:col-span-2"
                >
                    <h3
                        class="text-xs uppercase tracking-wide text-subtle mb-3"
                    >
                        API Requests
                    </h3>
                    <div class="flex flex-wrap gap-4">
                        <!-- MusicBrainz -->
                        <div
                            class="flex items-center gap-2 bg-surface-3 rounded-full px-3 py-1 border border-subtle cursor-help"
                            title="MusicBrainz"
                        >
                            <img
                                src="/assets/logo-musicbrainz.svg"
                                alt="MB"
                                class="w-5 h-5 opacity-90"
                            />
                            <span
                                class="font-mono text-sm font-bold text-default"
                                >{stats.api_stats?.musicbrainz || 0}</span
                            >
                        </div>

                        <!-- Fanart.tv -->
                        <div
                            class="flex items-center gap-2 bg-surface-3 rounded-full px-3 py-1 border border-subtle cursor-help"
                            title="Fanart.tv"
                        >
                            <img
                                src="/assets/logo-fanarttv.svg"
                                alt="Fanart"
                                class="w-5 h-5 opacity-90"
                            />
                            <span
                                class="font-mono text-sm font-bold text-default"
                                >{stats.api_stats?.fanart || 0}</span
                            >
                        </div>

                        <!-- Last.fm -->
                        <div
                            class="flex items-center gap-2 bg-surface-3 rounded-full px-3 py-1 border border-subtle cursor-help"
                            title="Last.fm"
                        >
                            <img
                                src="/assets/logo-lastfm.png"
                                alt="Last.fm"
                                class="w-5 h-5 opacity-90"
                            />
                            <span
                                class="font-mono text-sm font-bold text-default"
                                >{stats.api_stats?.lastfm || 0}</span
                            >
                        </div>

                        <!-- Wikidata -->
                        <div
                            class="flex items-center gap-2 bg-surface-3 rounded-full px-3 py-1 border border-subtle cursor-help"
                            title="Wikidata"
                        >
                            <img
                                src="/assets/logo-wikidata.png"
                                alt="Wikidata"
                                class="w-6 h-6 opacity-90"
                            />
                            <span
                                class="font-mono text-sm font-bold text-default"
                                >{stats.api_stats?.wikidata || 0}</span
                            >
                        </div>

                        <!-- Wikipedia -->
                        <div
                            class="flex items-center gap-2 bg-surface-3 rounded-full px-3 py-1 border border-subtle cursor-help"
                            title="Wikipedia"
                        >
                            <img
                                src="/assets/logo-wikipedia.svg"
                                alt="Wikipedia"
                                class="w-6 h-6 opacity-90"
                            />
                            <span
                                class="font-mono text-sm font-bold text-default"
                                >{stats.api_stats?.wikipedia || 0}</span
                            >
                        </div>

                        <!-- Spotify -->
                        <div
                            class="flex items-center gap-2 bg-surface-3 rounded-full px-3 py-1 border border-subtle cursor-help"
                            title="Spotify"
                        >
                            <img
                                src="/assets/logo-spotify.svg"
                                alt="Spotify"
                                class="w-5 h-5 opacity-90"
                            />
                            <span
                                class="font-mono text-sm font-bold text-default"
                                >{stats.api_stats?.spotify || 0}</span
                            >
                        </div>

                        <!-- Qobuz -->
                        <div
                            class="flex items-center gap-2 bg-surface-3 rounded-full px-3 py-1 border border-subtle cursor-help"
                            title="Qobuz"
                        >
                            <img
                                src="/assets/logo-qobuz.png"
                                alt="Qobuz"
                                class="w-5 h-5 opacity-90"
                            />
                            <span
                                class="font-mono text-sm font-bold text-default"
                                >{stats.api_stats?.qobuz || 0}</span
                            >
                        </div>
                    </div>
                </div>
            </div>

            <!-- Detailed Stats Table -->
            <div class="card bg-surface-2 border border-subtle p-4 mb-4">
                <h3 class="text-xs uppercase tracking-wide text-subtle mb-3">
                    Scan Statistics
                </h3>
                {#if stats.categories && stats.categories.length > 0}
                    <div class="overflow-x-auto">
                        <table class="table table-xs w-full text-left">
                            <thead>
                                <tr class="text-subtle border-b border-subtle">
                                    <th class="pb-2 font-normal">Category</th>
                                    <th class="pb-2 font-normal text-right"
                                        >Missing</th
                                    >
                                    <th class="pb-2 font-normal text-right"
                                        >Searched</th
                                    >
                                    <th class="pb-2 font-normal text-right"
                                        >Hits</th
                                    >
                                    <th class="pb-2 font-normal text-right"
                                        >Misses</th
                                    >
                                    <th class="pb-2 font-normal text-right"
                                        >Success Rate</th
                                    >
                                </tr>
                            </thead>
                            <tbody class="text-sm">
                                {#each stats.categories.sort( (a, b) => a.name.localeCompare(b.name), ) as category}
                                    <tr
                                        class="border-b border-subtle last:border-0 hover:bg-surface-3 transition-colors"
                                    >
                                        <td
                                            class="py-2 text-default font-medium"
                                            >{category.name}</td
                                        >
                                        <td class="py-2 text-right text-muted"
                                            >{category.missing}</td
                                        >
                                        <td class="py-2 text-right text-muted"
                                            >{category.searched}</td
                                        >
                                        <td
                                            class="py-2 text-right text-green-400"
                                            >{category.hits}</td
                                        >
                                        <td class="py-2 text-right text-red-400"
                                            >{category.misses}</td
                                        >
                                        <td class="py-2 text-right text-subtle">
                                            {category.success_rate}
                                        </td>
                                    </tr>
                                {/each}
                            </tbody>
                        </table>
                    </div>
                {:else}
                    <div class="text-subtle text-sm italic">
                        Run a scan to view detailed statistics...
                    </div>
                {/if}
            </div>

            <div
                class="card surface-glass-popover border border-subtle overflow-hidden flex flex-col font-mono text-sm shadow-inner"
            >
                <div
                    class="bg-surface-3 px-4 py-2 border-b border-subtle flex items-center justify-between"
                >
                    <span class="text-xs uppercase tracking-wider text-muted"
                        >Log Output</span
                    >
                    <span class="flex gap-2">
                        <div
                            class="w-3 h-3 rounded-full bg-red-500/20 mix-blend-screen"
                        ></div>
                        <div
                            class="w-3 h-3 rounded-full bg-yellow-500/20 mix-blend-screen"
                        ></div>
                        <div
                            class="w-3 h-3 rounded-full bg-green-500/20 mix-blend-screen"
                        ></div>
                    </span>
                </div>
                <div
                    class="h-96 overflow-y-auto p-4 space-y-2 scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent"
                    bind:this={logContainer}
                    on:scroll={handleScroll}
                >
                    {#if logs.length === 0}
                        <div class="text-subtle italic">No logs...</div>
                    {/if}
                    {#each logs as log}
                        <div class="break-all">
                            <span class="text-muted mr-2 select-none"
                                >[{new Date(
                                    log.timestamp,
                                ).toLocaleTimeString()}]</span
                            >
                            <span class="text-white/80">{log.message}</span>
                        </div>
                    {/each}
                </div>
            </div>
        </div>

        <!-- Controls -->
        <div class="card bg-surface-2 border border-subtle p-6 text-default">
            <div class="grid gap-4 md:grid-cols-2">
                <div class="space-y-4">
                    <label class="label">
                        <span class="label-text text-default">Library Path</span
                        >
                        <input
                            type="text"
                            bind:value={scanPath}
                            placeholder="Defaults to library root"
                            class="input input-bordered bg-surface border-subtle text-default placeholder:text-subtle mt-2 w-full"
                        />
                    </label>
                    <div class="form-control">
                        <Checkbox
                            bind:checked={forceRescan}
                            label="Force rescan (re-read tags)"
                            className="checkbox-primary"
                        />
                    </div>
                    <div class="form-control">
                        <Checkbox
                            bind:checked={missingOnly}
                            label="Missing only (skip data we already have)"
                            className="checkbox-secondary"
                        />
                    </div>
                </div>

                <div class="space-y-3">
                    <label class="label">
                        <span class="label-text text-default"
                            >Artist filter (optional)</span
                        >
                        <input
                            type="text"
                            bind:value={artistFilter}
                            list="artist-list"
                            placeholder={artistsLoaded
                                ? "Type to filter (blank = all)"
                                : "Loading artists..."}
                            class="input input-bordered bg-surface border-subtle text-default placeholder:text-subtle mt-2 w-full"
                        />
                        <datalist id="artist-list">
                            {#each artistOptions as artistName}
                                <option value={artistName}></option>
                            {/each}
                        </datalist>
                    </label>
                    <label class="label">
                        <span class="label-text text-default"
                            >MusicBrainz ID (optional)</span
                        >
                        <input
                            type="text"
                            bind:value={mbidFilter}
                            placeholder="e.g. ef5aab86-887d-4fc2-a883-431ef017175a"
                            class="input input-bordered bg-surface border-subtle text-default placeholder:text-subtle mt-2 w-full"
                        />
                    </label>
                </div>
            </div>

            <div class="mt-6 grid md:grid-cols-2 gap-4">
                <div class="space-y-2">
                    <div class="form-control">
                        <Checkbox
                            bind:checked={scanAll}
                            label="Scan All (Full Refresh)"
                            className="checkbox-accent font-bold"
                            on:click={toggleScanAll}
                        />
                    </div>
                    <div class="divider my-1"></div>
                    <div class="form-control">
                        <Checkbox
                            bind:checked={runFilesystem}
                            label="Scan & add/update files"
                            className="checkbox-primary"
                            on:click={updateScanAllState}
                        />
                    </div>
                    <div class="form-control">
                        <Checkbox
                            bind:checked={doMetadata}
                            label="Pull artist metadata (MusicBrainz)"
                            className="checkbox-primary"
                            on:click={updateScanAllState}
                        />
                    </div>
                    <div class="form-control">
                        <Checkbox
                            bind:checked={doBio}
                            label="Pull bios (Wikipedia)"
                            className="checkbox-primary"
                            on:click={updateScanAllState}
                        />
                    </div>
                    <div class="form-control">
                        <Checkbox
                            bind:checked={doArtwork}
                            label="Pull artist artwork (fanart.tv)"
                            className="checkbox-primary"
                            on:click={updateScanAllState}
                        />
                    </div>
                    <div class="form-control">
                        <Checkbox
                            bind:checked={doSpotifyArtwork}
                            label="Pull artist artwork (Spotify fallback)"
                            className="checkbox-primary"
                            on:click={updateScanAllState}
                        />
                    </div>
                </div>
                <div class="space-y-2 pt-[3.25rem]">
                    <!-- Align with right column offset by Scan All + Divider -->
                    <div class="form-control">
                        <Checkbox
                            bind:checked={doTopTracks}
                            label="Refresh top tracks (Last.fm)"
                            className="checkbox-primary"
                            on:click={updateScanAllState}
                        />
                    </div>
                    <div class="form-control">
                        <Checkbox
                            bind:checked={doSingles}
                            label="Refresh singles (MusicBrainz)"
                            className="checkbox-primary"
                            on:click={updateScanAllState}
                        />
                    </div>
                    <div class="form-control">
                        <Checkbox
                            bind:checked={doSimilarArtists}
                            label="Refresh similar artists (Last.fm)"
                            className="checkbox-primary"
                            on:click={updateScanAllState}
                        />
                    </div>
                    <div class="form-control">
                        <Checkbox
                            bind:checked={doAlbumMetadata}
                            label="Scan album metadata (Desc, Charts, Links)"
                            className="checkbox-primary"
                            on:click={updateScanAllState}
                        />
                    </div>
                    <!-- Links refresh is now part of metadata/implicit, removed separate checkbox -->
                    <div class="form-control">
                        <Checkbox
                            bind:checked={doMissingAlbums}
                            label="Scan missing albums (discovery)"
                            className="checkbox-primary"
                        />
                    </div>
                </div>
            </div>

            <div class="mt-6 flex flex-wrap gap-3">
                <TabButton
                    onClick={startCombined}
                    disabled={isRunning || queueActive}
                >
                    Start
                </TabButton>
                <TabButton onClick={startPrune} disabled={isRunning}>
                    Prune Library
                </TabButton>

                <TabButton onClick={startOptimize} disabled={isRunning}>
                    Optimize Database
                </TabButton>

                <TabButton onClick={startLastfmSync} disabled={isRunning}>
                    Update Scrobbles & Match
                </TabButton>
            </div>
        </div>
    </div>
</div>
