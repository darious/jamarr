import { writable, get } from 'svelte/store';
import type { Track } from '$api';

export interface Renderer {
    udn: string;
    name: string;
    type: string;
}

export interface PlayerState {
    renderers: Renderer[];
    renderer: string;
    queue: Track[];
    current_index: number;
    is_playing: boolean;
    position_seconds: number;
}

export const playerState = writable<PlayerState>({
    renderers: [{ udn: 'local', name: 'This Device (Web Browser)', type: 'local' }],
    renderer: 'local',
    queue: [],
    current_index: -1,
    is_playing: false,
    position_seconds: 0
});

export async function refreshRenderers(force: boolean = false) {
    console.log('[refreshRenderers] Starting...', { force });
    try {
        console.log(`[refreshRenderers] Fetching from: /api/renderers?refresh=${force}`);
        const res = await fetch(`/api/renderers?refresh=${force}`);
        console.log('[refreshRenderers] Response status:', res.status);
        if (res.ok) {
            const renderers = await res.json();
            console.log('[refreshRenderers] Received renderers:', renderers);
            playerState.update(s => ({ ...s, renderers }));
            console.log('[refreshRenderers] Store updated');
        } else {
            console.error('[refreshRenderers] Response not OK:', res.status, res.statusText);
        }
    } catch (e) {
        console.error('[refreshRenderers] Failed to refresh renderers', e);
    }
}

export async function setRenderer(udn: string) {
    try {
        const res = await fetch('/api/player/renderer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ udn })
        });
        if (res.ok) {
            playerState.update(s => ({ ...s, renderer: udn }));
        }
    } catch (e) {
        console.error('Failed to set renderer', e);
    }
}

// Helper to get client IP (best effort)
let cachedClientIp: string | null = null;

async function getClientIp(): Promise<string | null> {
    if (cachedClientIp) return cachedClientIp;

    try {
        // Try to get IP from our own backend endpoint
        const res = await fetch('/api/client-ip');
        if (res.ok) {
            const data = await res.json();
            cachedClientIp = data.ip;
            return cachedClientIp;
        }
    } catch (e) {
        console.warn('[getClientIp] Failed to get client IP:', e);
    }

    return null;
}

export async function loadQueueFromServer() {
    console.log('[loadQueueFromServer] Fetching player state...');
    try {
        const res = await fetch('/api/player/state');
        console.log('[loadQueueFromServer] Response status:', res.status);
        if (res.ok) {
            const data = await res.json();
            console.log('[loadQueueFromServer] Received data:', data);
            console.log('[loadQueueFromServer] Queue length:', data.queue?.length);
            playerState.update(s => ({
                ...s,
                queue: data.queue || [],
                current_index: data.current_index,
                position_seconds: data.position_seconds,
                is_playing: data.is_playing,
                renderer: data.renderer || 'local'
            }));
            console.log('[loadQueueFromServer] State updated. Renderer:', data.renderer);

            // If playing, we might want to resume? 
            // For now, let's just load the state. The UI can decide to auto-play or not.
        } else {
            console.error('[loadQueueFromServer] Failed, status:', res.status);
        }
    } catch (e) {
        console.error('[loadQueueFromServer] Exception:', e);
    }
}

export async function setQueue(tracks: Track[], startIndex: number = 0) {
    console.log('[setQueue] Called with tracks:', tracks, 'startIndex:', startIndex);
    try {
        console.log('[setQueue] Calling POST /api/player/queue');
        const hostname = window.location.hostname;
        const client_ip = await getClientIp();
        const res = await fetch('/api/player/queue', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ queue: tracks, start_index: startIndex, hostname, client_ip })
        });
        console.log('[setQueue] Response status:', res.status);
        if (res.ok) {
            playerState.update(s => ({
                ...s,
                queue: tracks,
                current_index: startIndex,
                is_playing: true,
                position_seconds: 0
            }));
            console.log('[setQueue] State updated, calling playCurrentTrack');
            await playCurrentTrack();
        } else {
            console.error('[setQueue] Failed, status:', res.status, await res.text());
        }
    } catch (e) {
        console.error('[setQueue] Exception:', e);
    }
}

export async function addToQueue(tracks: Track[]) {
    console.log('[addToQueue] Called with tracks:', tracks);
    try {
        console.log('[addToQueue] Calling POST /api/player/queue/append');
        const res = await fetch('/api/player/queue/append', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tracks })
        });
        console.log('[addToQueue] Response status:', res.status);
        if (res.ok) {
            playerState.update(s => ({ ...s, queue: [...s.queue, ...tracks] }));
            // If queue was empty, maybe start playing?
            const s = get(playerState);
            if (s.current_index === -1) {
                console.log('[addToQueue] Queue was empty, calling playFromQueue(0)');
                await playFromQueue(0);
            }
        } else {
            console.error('[addToQueue] Failed, status:', res.status, await res.text());
        }
    } catch (e) {
        console.error('[addToQueue] Exception:', e);
    }
}

export async function playFromQueue(index: number) {
    try {
        const hostname = window.location.hostname;
        const client_ip = await getClientIp();
        const res = await fetch('/api/player/index', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ index, hostname, client_ip })
        });
        if (res.ok) {
            playerState.update(s => ({ ...s, current_index: index, is_playing: true, position_seconds: 0 }));
            await playCurrentTrack();
        }
    } catch (e) {
        console.error('Failed to set index', e);
    }
}

export async function next() {
    const s = get(playerState);
    if (s.current_index < s.queue.length - 1) {
        await playFromQueue(s.current_index + 1);
    }
}

export async function previous() {
    const s = get(playerState);
    if (s.current_index > 0) {
        await playFromQueue(s.current_index - 1);
    }
}

// Debounce progress updates
let progressUpdateTimeout: any;
export function updateProgress(seconds: number, isPlaying: boolean) {
    playerState.update(s => ({ ...s, position_seconds: seconds, is_playing: isPlaying }));

    clearTimeout(progressUpdateTimeout);
    progressUpdateTimeout = setTimeout(async () => {
        console.log('[updateProgress] Sending to server:', { position_seconds: seconds, is_playing: isPlaying });
        try {
            const res = await fetch('/api/player/progress', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ position_seconds: seconds, is_playing: isPlaying })
            });
            if (res.ok) {
                console.log('[updateProgress] Server updated successfully');
            } else {
                console.error('[updateProgress] Server update failed:', res.status);
            }
        } catch (e) {
            console.error('[updateProgress] Failed to update progress', e);
        }
    }, 5000); // Update server every 5 seconds
}


async function playCurrentTrack() {
    const s = get(playerState);
    const track = s.queue[s.current_index];
    console.log('[playCurrentTrack] Called, current track:', track);
    if (!track) {
        console.warn('[playCurrentTrack] No track found at index', s.current_index);
        return;
    }

    try {
        console.log('[playCurrentTrack] Calling POST /api/player/play with track_id:', track.id);
        const res = await fetch('/api/player/play', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ track_id: track.id })
        });
        console.log('[playCurrentTrack] Response status:', res.status);
        const data = await res.json();
        console.log('[playCurrentTrack] Response data:', data);

        if (data.status === 'local_playback') {
            // Dispatch event for PlayerBar to handle local playback
            console.log('[playCurrentTrack] Dispatching jamarr:play-local event');
            window.dispatchEvent(new CustomEvent('jamarr:play-local', { detail: track }));
        } else {
            console.log('[playCurrentTrack] Not local playback, data:', data);
        }
    } catch (e) {
        console.error('[playCurrentTrack] Exception:', e);
    }
}

export async function setVolume(percent: number) {
    try {
        await fetch('/api/player/volume', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ percent })
        });
    } catch (e) {
        console.error('Failed to set volume', e);
    }
}
