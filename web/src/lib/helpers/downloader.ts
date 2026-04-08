import type { Track } from "$lib/api";
import { getStreamUrl } from "$lib/api";
import { downloadStore, type DownloadMode, type DownloadJob } from "$stores/downloads";



interface DownloadOptions {
    mode: DownloadMode;
    folderName: string; // Artist for album, Playlist Name for playlist
    subFolderName?: string; // Album Name for album, null for playlist
    tracks: Track[];
    onProgress?: (current: number, total: number, filename: string) => void;
}

const MAX_CONCURRENCY = 3;

interface DownloadTask {
    jobId: string;
    track: Track;
    filename: string;
    targetHandle: any;
    signal: AbortSignal;
}

// Global Queue State
const fileQueue: DownloadTask[] = [];
let activeDownloads = 0;




async function processGlobalQueue() {
    if (activeDownloads >= MAX_CONCURRENCY) return;
    if (fileQueue.length === 0) return;

    // Get next task
    const task = fileQueue.shift();
    if (!task) return;

    activeDownloads++;

    downloadSingleFile(task).finally(() => {
        activeDownloads--;
        processGlobalQueue();
    });

    processGlobalQueue();
}

async function downloadSingleFile(task: DownloadTask) {
    const { jobId, track, filename, targetHandle, signal } = task;

    const state = globalJobState.get(jobId);
    if (!state) return;

    // 1. Update Active State
    state.activeMap.set(track.id, { percent: 0, filename });
    syncJobToStore(jobId);

    try {
        if (signal.aborted) throw new Error('Aborted');

        const url = await getStreamUrl(track.id);
        const response = await fetch(url, { signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        if (!response.body) throw new Error('No body');

        const fileHandle = await targetHandle.getFileHandle(filename, { create: true });
        const writable = await fileHandle.createWritable();

        const contentLength = Number(response.headers.get('content-length'));
        let loaded = 0;

        const progressStream = new TransformStream({
            transform(chunk, controller) {
                loaded += chunk.byteLength;
                if (contentLength) {
                    const percent = (loaded / contentLength) * 100;
                    const entry = state.activeMap.get(track.id);
                    if (entry) {
                        entry.percent = percent;
                        // Throttle store updates slightly?
                        syncJobToStore(jobId);
                    }
                }
                controller.enqueue(chunk);
            }
        });

        await response.body.pipeThrough(progressStream).pipeTo(writable);

        // Success
        state.activeMap.delete(track.id);
        state.completedFiles++;
        syncJobToStore(jobId);

    } catch (err: any) {
        console.error(`Download failed for ${filename}:`, err);
        state.activeMap.delete(track.id);
        if (!signal.aborted) {
            // Log error?
        }
        syncJobToStore(jobId);
    }
}

const globalJobState = new Map<string, {
    totalFiles: number;
    completedFiles: number;
    activeMap: Map<number, { percent: number, filename: string }>;
}>();

function initJobState(jobId: string, totalFiles: number) {
    globalJobState.set(jobId, {
        totalFiles,
        completedFiles: 0,
        activeMap: new Map()
    });
}

function syncJobToStore(jobId: string) {
    const state = globalJobState.get(jobId);
    if (!state) return;

    let activeSum = 0;
    for (const v of state.activeMap.values()) {
        activeSum += v.percent;
    }

    const totalProgress = ((state.completedFiles * 100) + activeSum) / state.totalFiles;

    // Determine status
    let status = 'downloading';
    if (state.completedFiles === state.totalFiles) status = 'completed';
    // If pending? No, if it's in this state map it's at least "accepted".
    // Wait, if 0 completed and 0 active? It's 'pending' or 'queued'.
    if (state.completedFiles === 0 && state.activeMap.size === 0 && totalProgress === 0) {
        status = 'pending'; // Or 'downloading' but waiting for queue.
    }

    downloadStore.updateJob(jobId, {
        progress: totalProgress,
        completedFiles: state.completedFiles,
        activeFiles: state.activeMap.size,
        currentTracks: Array.from(state.activeMap.values()).map(v => v.filename),
        status: status as any
    });
}

export async function downloadTracks(options: DownloadOptions) {
    if (!(window as any).showDirectoryPicker) {
        alert("Your browser does not support the File System Access API.");
        return;
    }

    try {
        const rootHandle = await (window as any).showDirectoryPicker();
        // ... (Directory logic same as before) ...
        let folderHandle = await rootHandle.getDirectoryHandle(sanitizeFilename(options.folderName), { create: true });
        if (options.mode === "playlist") {
            const playlistsHandle = await rootHandle.getDirectoryHandle("Playlists", { create: true });
            folderHandle = await playlistsHandle.getDirectoryHandle(sanitizeFilename(options.folderName), { create: true });
        }

        let targetHandle = folderHandle;
        if (options.subFolderName) {
            targetHandle = await folderHandle.getDirectoryHandle(sanitizeFilename(options.subFolderName), { create: true });
        }

        const jobId = crypto.randomUUID();
        const abortController = new AbortController();
        const total = options.tracks.length;
        const jobName = options.subFolderName ? `${options.folderName} - ${options.subFolderName}` : options.folderName;

        // Init Local State
        initJobState(jobId, total);

        // Init Store
        downloadStore.addJob({
            id: jobId,
            name: jobName,
            totalFiles: total,
            completedFiles: 0,
            activeFiles: 0,
            currentTracks: [],
            progress: 0,
            status: 'pending', // Starts pending until a file is picked up
            abortController
        });

        // Queue all files
        options.tracks.forEach((track, index) => {
            let filename = track.path.split('/').pop() || `track-${track.id}.mp3`;
            if (options.mode === 'playlist') {
                const digits = total > 99 ? 3 : 2;
                const position = (index + 1).toString().padStart(digits, '0');
                filename = `${position} ${filename}`;
            }
            filename = sanitizeFilename(filename);

            fileQueue.push({
                jobId,
                track,
                filename,
                targetHandle,
                signal: abortController.signal
            });
        });

        // Start Processor
        processGlobalQueue();

    } catch (err: any) {
        if (err.name !== 'AbortError') {
            console.error("Setup failed:", err);
            alert("Failed: " + err.message);
        }
    }
}


function sanitizeFilename(name: string): string {
    return name
        .replace(/[\x00-\x1f\x7f]/g, '')      // strip control characters & null bytes
        .replace(/[/\\?%*:|"<>]/g, '-')         // replace illegal path chars
        .replace(/^[\s.]+|[\s.]+$/g, '')         // trim leading/trailing dots and spaces
        || 'unnamed';                             // fallback if result is empty
}
