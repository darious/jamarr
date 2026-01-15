import { writable } from 'svelte/store';

export type DownloadStatus = 'pending' | 'downloading' | 'completed' | 'error' | 'cancelled';
export type DownloadMode = 'album' | 'playlist' | 'numbered_album';

export interface DownloadJob {
    id: string;
    name: string; // Playlist or Album name
    totalFiles: number;
    completedFiles: number; // Fully completed files
    activeFiles: number; // Currently downloading
    currentTracks?: string[]; // Names of files currently being downloaded
    progress: number; // 0-100 overall percentage
    status: DownloadStatus;
    error?: string;
    abortController?: AbortController;
}

function createDownloadStore() {
    const { subscribe, update, set } = writable<Record<string, DownloadJob>>({});

    return {
        subscribe,
        addJob: (job: DownloadJob) => update(jobs => ({ ...jobs, [job.id]: job })),
        updateJob: (id: string, patch: Partial<DownloadJob>) => update(jobs => {
            if (!jobs[id]) return jobs;
            return { ...jobs, [id]: { ...jobs[id], ...patch } };
        }),
        removeJob: (id: string) => update(jobs => {
            const { [id]: _, ...rest } = jobs;
            return rest;
        }),
        clearCompleted: () => update(jobs => {
            const newJobs = { ...jobs };
            for (const id in newJobs) {
                if (newJobs[id].status === 'completed' || newJobs[id].status === 'cancelled' || newJobs[id].status === 'error') {
                    delete newJobs[id];
                }
            }
            return newJobs;
        })
    };
}

export const downloadStore = createDownloadStore();
