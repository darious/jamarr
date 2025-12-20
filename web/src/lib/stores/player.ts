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

// --- Client ID Logic ---
function uuidv4() {
    // Fallback for non-secure contexts where crypto.randomUUID is not available
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
        return crypto.randomUUID();
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
        var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

function getClientId(): string {
    const KEY = 'jamarr_client_id';
    if (typeof window === 'undefined') return 'server-side'; // Safety for SSR

    let id = localStorage.getItem(KEY);
    if (!id) {
        id = uuidv4();
        localStorage.setItem(KEY, id);
    }
    return id;
}

function getHeaders(): HeadersInit {
    return {
        'Content-Type': 'application/json',
        'X-Jamarr-Client-Id': getClientId()
    };
}

// --- Actions ---

export async function refreshRenderers(force: boolean = false) {
    console.log('[refreshRenderers] Starting...', { force });
    try {
        console.log(`[refreshRenderers] Fetching from: /api/renderers?refresh=${force}`);
        const res = await fetch(`/api/renderers?refresh=${force}`, {
            headers: { 'X-Jamarr-Client-Id': getClientId() }
        });
        console.log('[refreshRenderers] Response status:', res.status);
        if (res.ok) {
            const allRenderers = await res.json();
            console.log('[refreshRenderers] Received renderers:', allRenderers);

            // Filter out other 'local:*' renderers that are not us
            const myId = getClientId();
            const filtered = allRenderers.filter((r: any) => {
                if (r.udn.startsWith('local:')) {
                    return r.udn === `local:${myId}`;
                }
                return true;
            });

            // Ensure our local device is named nicely if backend generated it
            const finalRenderers = filtered.map((r: any) => {
                if (r.udn === `local:${myId}`) {
                    return { ...r, name: 'This Device (Web Browser)' };
                }
                return r;
            });

            playerState.update(s => ({ ...s, renderers: finalRenderers }));
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
            headers: getHeaders(),
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
        const res = await fetch('/api/client-ip', { headers: { 'X-Jamarr-Client-Id': getClientId() } });
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
        const res = await fetch('/api/player/state', {
            headers: { 'X-Jamarr-Client-Id': getClientId() }
        });
        console.log('[loadQueueFromServer] Response status:', res.status);
        if (res.ok) {
            const data = await res.json();
            console.log('[loadQueueFromServer] Received data:', data);

            // Map renderer UDN "local:<myId>" to internal "local" if we want UI consistency?
            // Actually, UI should just use the UDN.
            // If backend says renderer is "local:<myId>", we treat it as active.

            playerState.update(s => ({
                ...s,
                queue: data.queue || [],
                current_index: data.current_index,
                position_seconds: data.position_seconds,
                is_playing: data.is_playing,
                renderer: data.renderer || `local:${getClientId()}`
            }));
            console.log('[loadQueueFromServer] State updated. Renderer:', data.renderer);

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
            headers: getHeaders(),
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
            headers: getHeaders(),
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
            headers: getHeaders(),
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
        // console.log('[updateProgress] Sending to server:', { position_seconds: seconds, is_playing: isPlaying });
        try {
            const res = await fetch('/api/player/progress', {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({ position_seconds: seconds, is_playing: isPlaying })
            });
            if (res.ok) {
                // console.log('[updateProgress] Server updated successfully');
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
            headers: getHeaders(),
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
            headers: getHeaders(),
            body: JSON.stringify({ percent })
        });
    } catch (e) {
        console.error('Failed to set volume', e);
    }
}

export async function pause() {
    try {
        await fetch('/api/player/pause', {
            method: 'POST',
            headers: getHeaders()
        });
        playerState.update(s => ({ ...s, is_playing: false }));
    } catch (e) {
        console.error('Failed to pause', e);
    }
}

export async function resume() {
    try {
        await fetch('/api/player/resume', {
            method: 'POST',
            headers: getHeaders()
        });
        playerState.update(s => ({ ...s, is_playing: true }));
    } catch (e) {
        console.error('Failed to resume', e);
    }
}

export async function seek(seconds: number) {
    try {
        await fetch('/api/player/seek', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ seconds })
        });
        playerState.update(s => ({ ...s, position_seconds: seconds }));
    } catch (e) {
        console.error('Failed to seek', e);
    }
}
