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
    volume: number | null;
    transport_state?: string;
}

export const playerState = writable<PlayerState>({
    renderers: [{ udn: 'local', name: 'This Device (Web Browser)', type: 'local' }],
    renderer: 'local',
    queue: [],
    current_index: -1,
    is_playing: false,
    position_seconds: 0,
    volume: null
});

// UI: Now Playing overlay visibility
export const nowPlayingVisible = writable<boolean>(false);

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

export function getHeaders(): HeadersInit {
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
                renderer: data.renderer || `local:${getClientId()}`,
                // If server returns null (no history), keep existing volume (e.g. locally restored)
                // If server returns value, use it.
                volume: (data.volume !== null && data.volume !== undefined) ? data.volume : s.volume
            }));

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
            // Don't update store optimistically - immediately refresh from server instead
            // This ensures UI shows accurate state (position, artwork, etc)
            console.log('[setQueue] Queue set successfully, refreshing state from server');
            await loadQueueFromServer();
            // Now trigger playback
            console.log('[setQueue] Calling playCurrentTrack to start playback');
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
            const data = await res.json();
            const newState = data.state || {};
            playerState.update(s => ({
                ...s,
                queue: newState.queue ?? s.queue,
                current_index: newState.current_index ?? index,
                is_playing: newState.is_playing ?? true,
                position_seconds: newState.position_seconds ?? 0,
                transport_state: newState.transport_state ?? s.transport_state,
                renderer: newState.renderer ?? s.renderer,
                volume: newState.volume ?? s.volume
            }));
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
    let track = s.queue[s.current_index];

    // If track is not in frontend queue, fetch from server
    if (!track) {
        console.warn('[playCurrentTrack] Track not in frontend queue, fetching from server');
        try {
            const res = await fetch('/api/player/state', {
                headers: getHeaders()
            });
            if (res.ok) {
                const serverState = await res.json();
                if (serverState.queue && serverState.queue[serverState.current_index]) {
                    track = serverState.queue[serverState.current_index];
                    console.log('[playCurrentTrack] Got track from server:', track.title);
                } else {
                    console.error('[playCurrentTrack] No track at current index on server either');
                    return;
                }
            } else {
                console.error('[playCurrentTrack] Failed to fetch server state');
                return;
            }
        } catch (e) {
            console.error('[playCurrentTrack] Exception fetching server state:', e);
            return;
        }
    }

    console.log('[playCurrentTrack] Called, current track:', track);

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
            // Optimistically update state to Playing for remote
            playerState.update(s => ({ ...s, is_playing: true, position_seconds: 0 }));

            // Immediately refresh state to get accurate position and avoid UI lag
            await loadQueueFromServer();
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

export function toggleNowPlaying() {
    nowPlayingVisible.update(v => !v);
}

export function showNowPlaying(force: boolean) {
    nowPlayingVisible.set(force);
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
    const s = get(playerState);
    if (s.renderer.startsWith('local')) {
        console.log('[playerStore] Local seek, dispatching jamarr:seek', seconds);
        window.dispatchEvent(new CustomEvent('jamarr:seek', { detail: { position: seconds } }));
        playerState.update(state => ({ ...state, position_seconds: seconds }));
        return;
    }

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
