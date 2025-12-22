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
    } from "$lib/api";

    let status = "Idle";
    let isRunning = false;
    let stats = {
        scanned: 0,
        total: 0,
        percentage: 0,
        message: "",
        phase: "",
        completed: false,
        completedStatus: "",
    };
    let logs: { timestamp: number; message: string }[] = [];
    let logContainer: HTMLElement;

    let forceRescan = false;
    let scanPath = "";
    let artistFilter = "";
    let mbidFilter = "";
    let missingOnly = false;
    let missingAlbumsOnly = false;
    let bioOnly = false;
    let linksOnly = false;
    let artistOptions: string[] = [];
    let artistsLoaded = false;

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
        }
    });

    onDestroy(() => {
        if (eventSource) {
            eventSource.close();
        }
    });

    afterUpdate(() => {
        if (logContainer) {
            logContainer.scrollTop = logContainer.scrollHeight;
        }
    });

    function handleEvent(data: any) {
        if (data.type === "status") {
            status = data.status;
            if (data.stats && Object.keys(data.stats).length > 0) {
                stats = { ...stats, ...data.stats };
            }
        } else if (data.type === "progress") {
            status = "Running";
            isRunning = true;
            stats = {
                scanned: data.current,
                total: data.total,
                percentage: data.percentage,
                message: data.message,
                phase: data.phase || stats.phase,
                completed: false,
                completedStatus: "",
            };
        } else if (data.type === "log") {
            addLog(data.message);
        } else if (data.type === "start") {
            status = "Running";
            isRunning = true;
            stats.phase = data.phase || stats.phase;
            if (!logs.length || !isRunning) {
                logs = []; // Clear logs on first start to match CLI session feel
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
            isRunning = false;
            addLog(
                `Scan finished: ${data.status}${
                    data.error ? ` (${data.error})` : ""
                }`,
            );
            stats.completed = true;
            stats.completedStatus = data.status;
        }
    }

    function addLog(msg: string) {
        logs = [...logs, { timestamp: Date.now(), message: msg }];
        // Keep max logs
        if (logs.length > 500) logs = logs.slice(100);
    }

    async function startFilesystemScan() {
        try {
            await triggerFilesystemScan({
                force: forceRescan,
                path: scanPath || undefined,
            });
        } catch (e) {
            addLog(`Error starting scan: ${e}`);
        }
    }

    async function startMetadataScan() {
        try {
            if (missingAlbumsOnly) {
                await triggerMissingAlbumsScan(
                    mbidFilter || undefined,
                    artistFilter || undefined,
                );
            } else {
                await triggerMetadataScan({
                    artistFilter: artistFilter || undefined,
                    mbidFilter: mbidFilter || undefined,
                    missingOnly,
                    bioOnly,
                    linksOnly,
                });
            }
        } catch (e) {
            addLog(`Error starting metadata update: ${e}`);
        }
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

    async function startFull() {
        try {
            const metadataMissingOnly = forceRescan ? false : true;
            await triggerFullScan({
                force: forceRescan,
                path: scanPath || undefined,
                artistFilter: artistFilter || undefined,
                mbidFilter: mbidFilter || undefined,
                missingOnly: metadataMissingOnly,
                bioOnly,
                linksOnly,
            });
        } catch (e) {
            addLog(`Error starting full run: ${e}`);
        }
    }

    async function handleCancel() {
        await cancelScan();
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

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <!-- Left: Actions -->
        <div class="space-y-8">
            <!-- Full Library Refresh -->
            <div class="card bg-white/5 border border-white/10 p-6 text-white">
                <h2 class="text-xl font-semibold mb-4 flex items-center gap-2">
                    <svg
                        xmlns="http://www.w3.org/2000/svg"
                        class="h-5 w-5"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        ><path
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            stroke-width="2"
                            d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                        /></svg
                    >
                    Full Library Refresh
                </h2>
                <p class="text-sm text-white/70 mb-6">
                    Runs filesystem scan, metadata update, and prune in one go.
                    Mirrors the CLI <code>full</code> command.
                </p>

                <div class="space-y-4 mb-4">
                    <label class="label">
                        <span class="label-text text-white"
                            >Custom Path (optional)</span
                        >
                        <input
                            type="text"
                            bind:value={scanPath}
                            placeholder="/music"
                            class="input input-bordered bg-white/10 border-white/10 text-white placeholder:text-white/40 mt-2 w-full"
                        />
                    </label>
                    <div class="form-control">
                        <label class="label cursor-pointer justify-start gap-4">
                            <input
                                type="checkbox"
                                bind:checked={forceRescan}
                                class="checkbox checkbox-primary"
                            />
                            <span class="label-text text-white"
                                >Force Rescan (re-read all tags)</span
                            >
                        </label>
                    </div>
                </div>

                <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <button
                        class="btn w-full border border-white/10 bg-white/10 text-white hover:bg-white/20 normal-case font-normal"
                        on:click={startFull}
                        disabled={isRunning}
                    >
                        Run Full Refresh
                    </button>
                    <button
                        class="btn w-full border border-white/10 bg-white/5 text-white hover:bg-white/10 normal-case font-normal"
                        on:click={startFilesystemScan}
                        disabled={isRunning}
                    >
                        Filesystem Only
                    </button>
                </div>
            </div>

            <!-- Filesystem Scanner -->
            <div class="card bg-white/5 border border-white/10 p-6 text-white">
                <h2 class="text-xl font-semibold mb-4 flex items-center gap-2">
                    <svg
                        xmlns="http://www.w3.org/2000/svg"
                        class="h-5 w-5"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        ><path
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            stroke-width="2"
                            d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
                        /></svg
                    >
                    Filesystem Scanner
                </h2>
                <p class="text-sm text-white/70 mb-6">
                    Scan specific folders or the entire library for new files.
                    Changes to tags update existing entries.
                </p>

                <label class="label">
                    <span class="label-text text-white"
                        >Custom Path (optional)</span
                    >
                    <input
                        type="text"
                        bind:value={scanPath}
                        placeholder="Defaults to MUSIC_PATH"
                        class="input input-bordered bg-white/10 border-white/10 text-white placeholder:text-white/40 mt-2 w-full"
                    />
                </label>

                <div class="form-control mb-6">
                    <label class="label cursor-pointer justify-start gap-4">
                        <input
                            type="checkbox"
                            bind:checked={forceRescan}
                            class="checkbox checkbox-primary"
                        />
                        <span class="label-text text-white"
                            >Force Rescan (Re-read all tags)</span
                        >
                    </label>
                </div>

                <div class="flex gap-4">
                    <button
                        class="btn btn-primary flex-1"
                        on:click={startFilesystemScan}
                        disabled={isRunning}
                    >
                        Start Scan
                    </button>
                </div>
            </div>

            <!-- Metadata Manager -->
            <div class="card bg-white/5 border border-white/10 p-6 text-white">
                <h2 class="text-xl font-semibold mb-4 flex items-center gap-2">
                    <svg
                        xmlns="http://www.w3.org/2000/svg"
                        class="h-5 w-5"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        ><path
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            stroke-width="2"
                            d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
                        /></svg
                    >
                    Metadata
                </h2>
                <p class="text-sm text-white/70 mb-6">
                    Fetch info from MusicBrainz, Spotify, and other sources.
                </p>

                <div class="space-y-4 mb-6">
                    <label class="label">
                        <span class="label-text text-white"
                            >Artist Filter (Optional)</span
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
                            >MusicBrainz ID (Optional)</span
                        >
                        <input
                            type="text"
                            bind:value={mbidFilter}
                            placeholder="e.g. ef5aab86-887d-4fc2-a883-431ef017175a"
                            class="input input-bordered bg-white/10 border-white/10 text-white placeholder:text-white/40 mt-2 w-full"
                        />
                    </label>

                    <div class="form-control">
                        <label class="label cursor-pointer justify-start gap-4">
                            <input
                                type="checkbox"
                                bind:checked={missingOnly}
                                class="checkbox checkbox-secondary"
                            />
                            <span class="label-text text-white"
                                >Missing Metadata Only</span
                            >
                        </label>
                    </div>

                    <div class="form-control">
                        <label class="label cursor-pointer justify-start gap-4">
                            <input
                                type="checkbox"
                                bind:checked={missingAlbumsOnly}
                                class="checkbox checkbox-accent"
                            />
                            <span class="label-text text-white"
                                >Scan Missing Albums (Discovery)</span
                            >
                        </label>
                    </div>

                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <label class="label cursor-pointer justify-start gap-4">
                            <input
                                type="checkbox"
                                bind:checked={bioOnly}
                                class="checkbox checkbox-secondary"
                            />
                            <span class="label-text text-white"
                                >Bio & Images Only</span
                            >
                        </label>
                        <label class="label cursor-pointer justify-start gap-4">
                            <input
                                type="checkbox"
                                bind:checked={linksOnly}
                                class="checkbox checkbox-secondary"
                            />
                            <span class="label-text text-white"
                                >Links Only (Tidal/Qobuz/Wiki)</span
                            >
                        </label>
                    </div>
                </div>

                <button
                    class="btn w-full border border-white/10 bg-white/10 text-white hover:bg-white/20 normal-case font-normal"
                    on:click={startMetadataScan}
                    disabled={isRunning}
                >
                    Update Metadata
                </button>
            </div>

            <!-- Maintenance -->
            <div class="card bg-white/5 border border-white/10 p-6 text-white">
                <h2
                    class="text-xl font-semibold mb-4 text-error flex items-center gap-2"
                >
                    <svg
                        xmlns="http://www.w3.org/2000/svg"
                        class="h-5 w-5"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        ><path
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            stroke-width="2"
                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                        /></svg
                    >
                    Maintenance
                </h2>
                <p class="text-sm text-white/70 mb-6">
                    Clean up the database by removing entries for deleted files
                    and unused artwork.
                </p>
                <button
                    class="btn w-full border border-white/10 bg-white/5 text-white hover:bg-white/10 normal-case font-normal"
                    on:click={startPrune}
                    disabled={isRunning}
                >
                    Prune Library
                </button>
            </div>
        </div>

        <!-- Right: Output -->
        <div class="flex flex-col h-full space-y-4">
            <!-- Progress Card -->
            <div
                class="card bg-black/40 border border-white/10 p-6 backdrop-blur-sm"
            >
                <div class="flex justify-between items-center mb-2">
                    <div class="flex flex-col">
                        <span
                            class="text-xs uppercase tracking-wide text-primary-300"
                            >{stats.phase || "idle"}</span
                        >
                        <span class="text-sm font-medium text-white/80"
                            >{stats.message ||
                                (stats.completed ? "Done" : "Ready")}</span
                        >
                    </div>
                    <span class="text-xs font-mono text-primary-400"
                        >{Math.round(stats.percentage)}%</span
                    >
                </div>
                <progress
                    class="progress progress-primary w-full"
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

                {#if isRunning}
                    <div class="mt-4 flex justify-end">
                        <button
                            class="btn btn-xs btn-error"
                            on:click={handleCancel}>Cancel Operation</button
                        >
                    </div>
                {/if}
            </div>

            <!-- Terminal -->
            <div
                class="flex-1 card bg-[#0d1117] border border-white/10 overflow-hidden flex flex-col font-mono text-sm shadow-inner"
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
                    class="flex-1 overflow-y-auto p-4 space-y-1 scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent"
                    bind:this={logContainer}
                >
                    {#if logs.length === 0}
                        <div class="text-white/20 italic">No logs...</div>
                    {/if}
                    {#each logs as log}
                        <div class="break-all font-mono">
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
    </div>
</div>
