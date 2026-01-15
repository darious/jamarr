import { writable, get } from 'svelte/store';
import type { Track } from '$api';
import { fetchWithAuth } from '$lib/api';

export interface Renderer {
    udn: string;
    name: string;
    type: string;
    icon_url?: string;
    icon_mime?: string;
    icon_width?: number;
    icon_height?: number;
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
    repeatMode: 'off' | 'all' | 'one';
}

export const playerState = writable<PlayerState>({
    renderers: [{ udn: 'local', name: 'This Device (Web Browser)', type: 'local' }],
    renderer: 'local',
    queue: [],
    current_index: -1,
    is_playing: false,
    position_seconds: 0,
    volume: null,
    repeatMode: 'off'
});

// UI: Now Playing overlay visibility
export const nowPlayingVisible = writable<boolean>(false);

function mergeQueueArt(prev: Track[], next: Track[]): Track[] {
    if (!prev.length || !next.length) return next;
    const artById = new Map<number, string | null | undefined>();
    for (const t of prev) {
        if (t?.id) artById.set(t.id, t.art_sha1 ?? null);
    }
    return next.map((t) => {
        if (!t?.id) return t;
        if (!t.art_sha1 && artById.has(t.id)) {
            return { ...t, art_sha1: artById.get(t.id) ?? null };
        }
        return t;
    });
}

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

    try {

        const res = await fetch(`/api/renderers?refresh=${force}`, {
            headers: { 'X-Jamarr-Client-Id': getClientId() }
        });

        if (res.ok) {
            const allRenderers = await res.json();


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

        } else {
            console.error('[refreshRenderers] Response not OK:', res.status, res.statusText);
        }
    } catch (e) {
        console.error('[refreshRenderers] Failed to refresh renderers', e);
    }
}

export async function setRenderer(udn: string) {
    try {
        const res = await fetchWithAuth('/api/player/renderer', {
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

    try {
        const res = await fetchWithAuth('/api/player/state', {
            headers: { 'X-Jamarr-Client-Id': getClientId() }
        });

        if (res.ok) {
            const data = await res.json();


            // Map renderer UDN "local:<myId>" to internal "local" if we want UI consistency?
            // Actually, UI should just use the UDN.
            // If backend says renderer is "local:<myId>", we treat it as active.

            const mergedQueue = mergeQueueArt(get(playerState).queue, data.queue || []);
            playerState.update(s => ({
                ...s,
                queue: mergedQueue,
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

    try {

        const hostname = window.location.hostname;
        const client_ip = await getClientIp();
        const res = await fetchWithAuth('/api/player/queue', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ queue: tracks, start_index: startIndex, hostname, client_ip })
        });

        if (res.ok) {
            // Don't update store optimistically - immediately refresh from server instead
            // This ensures UI shows accurate state (position, artwork, etc)

            await loadQueueFromServer();
            // Now trigger playback

            await playCurrentTrack();
        } else {
            console.error('[setQueue] Failed, status:', res.status, await res.text());
        }
    } catch (e) {
        console.error('[setQueue] Exception:', e);
    }
}

export async function addToQueue(tracks: Track[]) {

    try {

        const res = await fetchWithAuth('/api/player/queue/append', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ tracks })
        });

        if (res.ok) {
            playerState.update(s => ({ ...s, queue: [...s.queue, ...tracks] }));
            // If queue was empty, maybe start playing?
            const s = get(playerState);
            if (s.current_index === -1) {

                await playFromQueue(0);
            }
        } else {
            console.error('[addToQueue] Failed, status:', res.status, await res.text());
        }
    } catch (e) {
        console.error('[addToQueue] Exception:', e);
    }
}

export async function reorderQueue(arg1: Track[] | number, arg2?: number) {
    let newQueue: Track[] = [];

    // Check if called with (newQueue: Track[])
    if (Array.isArray(arg1)) {
        newQueue = arg1;
    }
    // Check if called with (fromIndex: number, toIndex: number)
    else if (typeof arg1 === 'number' && typeof arg2 === 'number') {
        const current = get(playerState);
        const q = [...current.queue];
        const [moved] = q.splice(arg1, 1);
        // If dropping after the original position (arg2 > arg1), the index shifts by -1 due to splice
        // But logic depends on where dropIndex is calculated.
        // Assuming standard DnD logic: insert at arg2.
        // However, if arg2 > arg1, we simply insert at arg2 (handled by splice logic: splice removes, indices shift).
        // Let's standardise: splice insert.
        // But wait, if arg2 > arg1, usually dropIndex is "index to insert before".

        // Let's assume standard array move:
        q.splice(arg2, 0, moved);
        newQueue = q;
    } else {
        console.error('[reorderQueue] Invalid arguments');
        return;
    }

    const current = get(playerState);
    const currentTrackId = current.queue[current.current_index]?.id;
    try {
        const res = await fetchWithAuth('/api/player/queue/reorder', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ queue: newQueue })
        });
        if (res.ok) {
            const data = await res.json();
            const state = data.state || {};
            playerState.update((s) => ({
                ...s,
                queue: state.queue ? mergeQueueArt(s.queue, state.queue) : newQueue,
                current_index:
                    state.current_index ??
                    (currentTrackId
                        ? (state.queue || newQueue).findIndex((t: Track) => t.id === currentTrackId)
                        : -1),
                position_seconds: state.position_seconds ?? s.position_seconds,
                is_playing: state.is_playing ?? s.is_playing,
                transport_state: state.transport_state ?? s.transport_state,
            }));
        } else {
            console.error('[reorderQueue] Failed, status:', res.status, await res.text());
        }
    } catch (e) {
        console.error('[reorderQueue] Exception:', e);
    }
}

export async function clearQueue(stopPlayback: boolean = true) {

    try {
        const res = await fetchWithAuth('/api/player/queue/clear', {
            method: 'POST',
            headers: getHeaders()
        });

        if (res.ok) {
            playerState.update(s => ({
                ...s,
                queue: [],
                current_index: -1,
                position_seconds: 0,
                is_playing: false,
                transport_state: 'STOPPED'
            }));

            if (stopPlayback) {
                try {
                    await pause();
                } catch (err) {
                    console.warn('[clearQueue] Failed to pause after clear:', err);
                }
            }
        } else {
            console.error('[clearQueue] Failed, status:', res.status, await res.text());
        }
    } catch (e) {
        console.error('[clearQueue] Exception:', e);
    }
}

export async function playFromQueue(index: number) {
    try {
        const hostname = window.location.hostname;
        const client_ip = await getClientIp();
        const res = await fetchWithAuth('/api/player/index', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ index, hostname, client_ip })
        });
        if (res.ok) {
            const data = await res.json();
            const newState = data.state || {};
            const mergedQueue = newState.queue
                ? mergeQueueArt(get(playerState).queue, newState.queue)
                : undefined;
            playerState.update(s => ({
                ...s,
                queue: mergedQueue ?? s.queue,
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
    if (s.repeatMode === 'one') {
        await playFromQueue(s.current_index);
        return;
    }

    if (s.current_index < s.queue.length - 1) {
        await playFromQueue(s.current_index + 1);
    } else if (s.repeatMode === 'all' && s.queue.length > 0) {
        await playFromQueue(0);
    }
}

export async function previous() {
    const s = get(playerState);
    // If repeat one, maybe restart track? Standard behavior usually is dependent on time played (e.g. >3s restarts).
    // For now simple prev logic.
    if (s.current_index > 0) {
        await playFromQueue(s.current_index - 1);
    } else if (s.repeatMode === 'all' && s.queue.length > 0) {
        await playFromQueue(s.queue.length - 1);
    }
}

export async function shuffleQueue() {
    const s = get(playerState);
    if (s.queue.length <= 1) return;

    const currentTrack = s.queue[s.current_index];
    // Filter out current track
    let others = s.queue.filter((_, i) => i !== s.current_index);

    // Shuffle others
    for (let i = others.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [others[i], others[j]] = [others[j], others[i]];
    }

    // New queue: current + shuffled
    const newQueue = currentTrack ? [currentTrack, ...others] : others;

    // We must update the server
    await reorderQueue(newQueue);

    // Local update will happen via socket or response from reorderQueue ideally, 
    // but reorderQueue function already updates store.
}

export function toggleRepeat() {
    playerState.update(s => {
        const modes: ('off' | 'all' | 'one')[] = ['off', 'all', 'one'];
        const idx = modes.indexOf(s.repeatMode);
        const nextMode = modes[(idx + 1) % modes.length];
        return { ...s, repeatMode: nextMode };
    });
}

// Throttling handled by caller (PlayerBar.svelte)
export async function updateProgress(seconds: number, isPlaying: boolean) {
    playerState.update(s => ({ ...s, position_seconds: seconds, is_playing: isPlaying }));


    try {
        const res = await fetchWithAuth('/api/player/progress', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ position_seconds: seconds, is_playing: isPlaying })
        });
        if (res.ok) {

        } else {
            console.error('[updateProgress] Server update failed:', res.status);
        }
    } catch (e) {
        console.error('[updateProgress] Failed to update progress', e);
    }
}


async function playCurrentTrack() {
    const s = get(playerState);
    let track = s.queue[s.current_index];

    // If track is not in frontend queue, fetch from server
    if (!track) {
        console.warn('[playCurrentTrack] Track not in frontend queue, fetching from server');
        try {
            const res = await fetchWithAuth('/api/player/state', {
                headers: getHeaders()
            });
            if (res.ok) {
                const serverState = await res.json();
                if (serverState.queue && serverState.queue[serverState.current_index]) {
                    track = serverState.queue[serverState.current_index];

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



    try {

        const res = await fetchWithAuth('/api/player/play', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ track_id: track.id })
        });

        const data = await res.json();


        if (data.status === 'local_playback') {
            // Dispatch event for PlayerBar to handle local playback

            window.dispatchEvent(new CustomEvent('jamarr:play-local', { detail: track }));
        } else {

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
        await fetchWithAuth('/api/player/volume', {
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
    const s = get(playerState);
    if (s.renderer.startsWith('local')) {

        window.dispatchEvent(new CustomEvent('jamarr:pause'));
        playerState.update(s => ({ ...s, is_playing: false }));
        return;
    }

    try {
        await fetchWithAuth('/api/player/pause', {
            method: 'POST',
            headers: getHeaders()
        });
        playerState.update(s => ({ ...s, is_playing: false }));
    } catch (e) {
        console.error('Failed to pause', e);
    }
}

export async function resume() {
    const s = get(playerState);
    if (s.renderer.startsWith('local')) {

        window.dispatchEvent(new CustomEvent('jamarr:resume'));
        playerState.update(s => ({ ...s, is_playing: true }));
        return;
    }

    try {
        await fetchWithAuth('/api/player/resume', {
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

        window.dispatchEvent(new CustomEvent('jamarr:seek', { detail: { position: seconds } }));
        playerState.update(state => ({ ...state, position_seconds: seconds }));
        return;
    }

    try {
        await fetchWithAuth('/api/player/seek', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ seconds })
        });
        playerState.update(s => ({ ...s, position_seconds: seconds }));
    } catch (e) {
        console.error('Failed to seek', e);
    }
}
