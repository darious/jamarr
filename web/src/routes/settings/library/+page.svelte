<script lang="ts">
    import { onMount, onDestroy, afterUpdate } from "svelte";
    import {
        triggerFilesystemScan,
        triggerMetadataScan,
        triggerFullScan,
        triggerPrune,
        cancelScan,
        fetchArtists,
        triggerMissingAlbumsScan,
        triggerOptimize,
    } from "$lib/api";

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
        };
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
        api_stats: {},
        processed_stats: {},
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

    // doLinks removed
    let doMissingAlbums = false;
    let scanAll = false;
    let artistOptions: string[] = [];
    let artistsLoaded = false;
    let queueActive = false;
    let taskQueue: { label: string; start: () => Promise<void> }[] = [];
    let startTimestamp = 0;

    let eventSource: EventSource | undefined;

    onMount(async () => {
        // Connect to SSE
        eventSource = new EventSource("/api/library/events");

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

        // Get initial status
        try {
            const res = await fetch("/api/library/status");
            if (res.ok) {
                const data = await res.json();
                status = data.status;
                isRunning = data.is_running;
                if (data.stats && Object.keys(data.stats).length > 0) {
                    stats = data.stats;
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
        const wantsMetadata =
            doMetadata ||
            doBio ||
            doArtwork ||
            doSpotifyArtwork ||
            doTopTracks ||
            doSingles ||
            doSimilarArtists;

        if (runFilesystem && wantsMetadata) {
            taskQueue.push({
                label: "Full Scan (Filesystem + Metadata)",
                start: () =>
                    triggerFullScan({
                        force: forceRescan,
                        path: scanPath || undefined,
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
                    }),
            });
        } else {
            if (runFilesystem) {
                taskQueue.push({
                    label: "Filesystem",
                    start: () =>
                        triggerFilesystemScan({
                            force: forceRescan,
                            path: scanPath || undefined,
                        }),
                });
            }

            if (wantsMetadata) {
                taskQueue.push({
                    label: "Metadata",
                    start: () =>
                        triggerMetadataScan({
                            artistFilter: artistFilter || undefined,
                            mbidFilter: mbidFilter || undefined,
                            missingOnly,
                            fetchMetadata: doMetadata,
                            fetchBio: doBio,
                            fetchArtwork: doArtwork,
                            fetchSpotifyArtwork: doSpotifyArtwork,
                            fetchLinks: doMetadata,
                            refreshTopTracks: doTopTracks,
                            refreshSingles: doSingles,
                            fetchSimilarArtists: doSimilarArtists,
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
            doSimilarArtists
        ) {
            scanAll = true;
        } else {
            scanAll = false;
        }
    }
</script>

<div
    class="container mx-auto p-6 max-w-6xl text-white min-h-[calc(100vh-80px)]"
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
                class="card bg-black/40 border border-white/10 p-6 backdrop-blur-sm"
            >
                <div class="flex justify-between items-start gap-4">
                    <div class="flex flex-col gap-1">
                        <span
                            class="text-xs uppercase tracking-wide text-primary-300"
                        >
                            {stats.phase || (isRunning ? "running" : "idle")}
                        </span>
                        <span class="text-base font-semibold text-white">
                            {stats.message ||
                                (stats.completed ? "Done" : "Ready")}
                        </span>
                        <div
                            class="text-xs text-white/60 flex items-center gap-3"
                        >
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
                        <span class="text-xs font-mono text-primary-400"
                            >{Math.round(stats.percentage)}%</span
                        >
                        {#if isRunning}
                            <button
                                class="btn btn-xs btn-error mt-2"
                                on:click={handleCancel}
                            >
                                Cancel
                            </button>
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
                        class="mt-3 flex items-center justify-between text-xs text-white/70 bg-white/5 rounded-lg px-3 py-2 border border-white/10"
                    >
                        <span>Scan complete ({stats.completedStatus})</span>
                        <button
                            class="btn btn-ghost btn-xs text-white/80 border border-white/10 bg-white/5 hover:bg-white/10"
                            on:click={() => {
                                stats.completed = false;
                                stats.completedStatus = "";
                            }}
                        >
                            Dismiss
                        </button>
                    </div>
                {/if}
            </div>

            <!-- API & Processed Stats -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <!-- Processed Counts -->
                <div class="card bg-white/5 border border-white/10 p-4">
                    <h3
                        class="text-xs uppercase tracking-wide text-white/40 mb-3"
                    >
                        Processed Items
                    </h3>
                    <div class="flex gap-6">
                        <div class="flex flex-col">
                            <span
                                class="text-2xl font-bold font-display text-white"
                                >{stats.processed_stats?.tracks || 0}</span
                            >
                            <span class="text-xs text-white/50">Tracks</span>
                        </div>
                        <div class="flex flex-col">
                            <span
                                class="text-2xl font-bold font-display text-white"
                                >{stats.processed_stats?.albums || 0}</span
                            >
                            <span class="text-xs text-white/50">Albums</span>
                        </div>
                        <div class="flex flex-col">
                            <span
                                class="text-2xl font-bold font-display text-white"
                                >{stats.processed_stats?.artists || 0}</span
                            >
                            <span class="text-xs text-white/50">Artists</span>
                        </div>
                    </div>
                </div>

                <!-- API Hits -->
                <div class="card bg-white/5 border border-white/10 p-4">
                    <h3
                        class="text-xs uppercase tracking-wide text-white/40 mb-3"
                    >
                        API Requests
                    </h3>
                    <div class="flex flex-wrap gap-4">
                        <!-- MusicBrainz -->
                        <div
                            class="flex items-center gap-2 bg-white/5 rounded-full px-3 py-1 border border-white/5"
                        >
                            <img
                                src="/assets/logo-musicbrainz.svg"
                                alt="MB"
                                class="w-5 h-5 opacity-90"
                            />
                            <span
                                class="font-mono text-sm font-bold text-white/90"
                                >{stats.api_stats?.musicbrainz || 0}</span
                            >
                        </div>

                        <!-- Spotify -->
                        <div
                            class="flex items-center gap-2 bg-white/5 rounded-full px-3 py-1 border border-white/5"
                        >
                            <img
                                src="/assets/logo-spotify.svg"
                                alt="Spotify"
                                class="w-5 h-5 opacity-90"
                            />
                            <span
                                class="font-mono text-sm font-bold text-white/90"
                                >{stats.api_stats?.spotify || 0}</span
                            >
                        </div>

                        <!-- Last.fm -->
                        <div
                            class="flex items-center gap-2 bg-white/5 rounded-full px-3 py-1 border border-white/5"
                        >
                            <img
                                src="/assets/logo-lastfm.png"
                                alt="Last.fm"
                                class="w-5 h-5 opacity-90"
                            />
                            <span
                                class="font-mono text-sm font-bold text-white/90"
                                >{stats.api_stats?.lastfm || 0}</span
                            >
                        </div>

                        <!-- Wikidata (Wikipedia) -->
                        <div
                            class="flex items-center gap-2 bg-white/5 rounded-full px-3 py-1 border border-white/5"
                        >
                            <img
                                src="/assets/logo-wikipedia.svg"
                                alt="Wikidata"
                                class="w-6 h-6 opacity-90"
                            />
                            <span
                                class="font-mono text-sm font-bold text-white/90"
                                >{(stats.api_stats?.wikidata || 0) +
                                    (stats.api_stats?.wikipedia || 0)}</span
                            >
                        </div>

                        <!-- Fanart.tv -->
                        <div
                            class="flex items-center gap-2 bg-white/5 rounded-full px-3 py-1 border border-white/5"
                        >
                            <img
                                src="/assets/logo-fanarttv.svg"
                                alt="Fanart"
                                class="w-5 h-5 opacity-90"
                            />
                            <span
                                class="font-mono text-sm font-bold text-white/90"
                                >{stats.api_stats?.fanart || 0}</span
                            >
                        </div>
                    </div>
                </div>
            </div>

            <div
                class="card bg-[#0d1117] border border-white/10 overflow-hidden flex flex-col font-mono text-sm shadow-inner"
            >
                <div
                    class="bg-white/5 px-4 py-2 border-b border-white/5 flex items-center justify-between"
                >
                    <span class="text-xs uppercase tracking-wider text-white/40"
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
                        <div class="text-white/20 italic">No logs...</div>
                    {/if}
                    {#each logs as log}
                        <div class="break-all">
                            <span class="text-white/30 mr-2 select-none"
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
        <div class="card bg-white/5 border border-white/10 p-6 text-white">
            <div class="grid gap-4 md:grid-cols-2">
                <div class="space-y-4">
                    <label class="label">
                        <span class="label-text text-white">Library Path</span>
                        <input
                            type="text"
                            bind:value={scanPath}
                            placeholder="Defaults to library root"
                            class="input input-bordered bg-white/10 border-white/10 text-white placeholder:text-white/40 mt-2 w-full"
                        />
                    </label>
                    <div class="form-control">
                        <label class="label cursor-pointer justify-start gap-3">
                            <input
                                type="checkbox"
                                bind:checked={forceRescan}
                                class="checkbox checkbox-primary"
                            />
                            <span class="label-text text-white"
                                >Force rescan (re-read tags)</span
                            >
                        </label>
                    </div>
                    <div class="form-control">
                        <label class="label cursor-pointer justify-start gap-3">
                            <input
                                type="checkbox"
                                bind:checked={missingOnly}
                                class="checkbox checkbox-secondary"
                            />
                            <span class="label-text text-white"
                                >Missing only (skip data we already have)</span
                            >
                        </label>
                    </div>
                </div>

                <div class="space-y-3">
                    <label class="label">
                        <span class="label-text text-white"
                            >Artist filter (optional)</span
                        >
                        <input
                            type="text"
                            bind:value={artistFilter}
                            list="artist-list"
                            placeholder={artistsLoaded
                                ? "Type to filter (blank = all)"
                                : "Loading artists..."}
                            class="input input-bordered bg-white/10 border-white/10 text-white placeholder:text-white/40 mt-2 w-full"
                        />
                        <datalist id="artist-list">
                            {#each artistOptions as artistName}
                                <option value={artistName}></option>
                            {/each}
                        </datalist>
                    </label>
                    <label class="label">
                        <span class="label-text text-white"
                            >MusicBrainz ID (optional)</span
                        >
                        <input
                            type="text"
                            bind:value={mbidFilter}
                            placeholder="e.g. ef5aab86-887d-4fc2-a883-431ef017175a"
                            class="input input-bordered bg-white/10 border-white/10 text-white placeholder:text-white/40 mt-2 w-full"
                        />
                    </label>
                </div>
            </div>

            <div class="mt-6 grid md:grid-cols-2 gap-4">
                <div class="space-y-2">
                    <div class="form-control">
                        <label class="label cursor-pointer justify-start gap-3"
                            ><input
                                type="checkbox"
                                bind:checked={scanAll}
                                on:change={toggleScanAll}
                                class="checkbox checkbox-accent"
                            /><span class="label-text text-white font-bold"
                                >Scan All (Full Refresh)</span
                            ></label
                        >
                    </div>
                    <div class="divider my-1"></div>
                    <div class="form-control">
                        <label class="label cursor-pointer justify-start gap-3"
                            ><input
                                type="checkbox"
                                bind:checked={runFilesystem}
                                on:change={updateScanAllState}
                                class="checkbox checkbox-primary"
                            /><span class="label-text text-white"
                                >Scan & add/update files</span
                            ></label
                        >
                    </div>
                    <div class="form-control">
                        <label class="label cursor-pointer justify-start gap-3"
                            ><input
                                type="checkbox"
                                bind:checked={doMetadata}
                                on:change={updateScanAllState}
                                class="checkbox checkbox-primary"
                            /><span class="label-text text-white"
                                >Pull artist metadata (MusicBrainz)</span
                            ></label
                        >
                    </div>
                    <div class="form-control">
                        <label class="label cursor-pointer justify-start gap-3"
                            ><input
                                type="checkbox"
                                bind:checked={doBio}
                                on:change={updateScanAllState}
                                class="checkbox checkbox-primary"
                            /><span class="label-text text-white"
                                >Pull bios (Wikipedia)</span
                            ></label
                        >
                    </div>
                    <div class="form-control">
                        <label class="label cursor-pointer justify-start gap-3"
                            ><input
                                type="checkbox"
                                bind:checked={doArtwork}
                                on:change={updateScanAllState}
                                class="checkbox checkbox-primary"
                            /><span class="label-text text-white"
                                >Pull artist artwork (fanart.tv)</span
                            ></label
                        >
                    </div>
                    <div class="form-control">
                        <label class="label cursor-pointer justify-start gap-3"
                            ><input
                                type="checkbox"
                                bind:checked={doSpotifyArtwork}
                                on:change={updateScanAllState}
                                class="checkbox checkbox-primary"
                            /><span class="label-text text-white"
                                >Pull artist artwork (Spotify)</span
                            ></label
                        >
                    </div>
                </div>
                <div class="space-y-2 pt-[3.25rem]">
                    <!-- Align with right column offset by Scan All + Divider -->
                    <div class="form-control">
                        <label class="label cursor-pointer justify-start gap-3"
                            ><input
                                type="checkbox"
                                bind:checked={doTopTracks}
                                on:change={updateScanAllState}
                                class="checkbox checkbox-primary"
                            /><span class="label-text text-white"
                                >Refresh top tracks (Last.fm)</span
                            ></label
                        >
                    </div>
                    <div class="form-control">
                        <label class="label cursor-pointer justify-start gap-3"
                            ><input
                                type="checkbox"
                                bind:checked={doSingles}
                                on:change={updateScanAllState}
                                class="checkbox checkbox-primary"
                            /><span class="label-text text-white"
                                >Refresh singles (MusicBrainz)</span
                            ></label
                        >
                    </div>
                    <div class="form-control">
                        <label class="label cursor-pointer justify-start gap-3"
                            ><input
                                type="checkbox"
                                bind:checked={doSimilarArtists}
                                on:change={updateScanAllState}
                                class="checkbox checkbox-primary"
                            /><span class="label-text text-white"
                                >Refresh similar artists (Last.fm)</span
                            ></label
                        >
                    </div>
                    <!-- Links refresh is now part of metadata/implicit, removed separate checkbox -->
                    <div class="form-control">
                        <label class="label cursor-pointer justify-start gap-3"
                            ><input
                                type="checkbox"
                                bind:checked={doMissingAlbums}
                                class="checkbox checkbox-primary"
                            /><span class="label-text text-white"
                                >Scan missing albums (discovery)</span
                            ></label
                        >
                    </div>
                </div>
            </div>

            <div class="mt-6 flex flex-wrap gap-3">
                <button
                    class="btn border border-white/10 bg-white/10 text-white hover:bg-white/20 normal-case font-normal"
                    on:click={startCombined}
                    disabled={isRunning || queueActive}
                >
                    Start
                </button>
                <button
                    class="btn border border-white/10 bg-white/5 text-white hover:bg-white/10 normal-case font-normal"
                    on:click={startPrune}
                    disabled={isRunning}
                >
                    Prune Library
                </button>

                <button
                    class="btn border border-white/10 bg-white/5 text-white hover:bg-white/10 normal-case font-normal"
                    disabled={isRunning}
                    on:click={startOptimize}
                >
                    Optimize Database
                </button>
            </div>
        </div>
    </div>
</div>
