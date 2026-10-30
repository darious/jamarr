import { writable, derived, get } from 'svelte/store';
import type { Track } from '$api';
import { fetchWithAuth } from '$lib/api';
import {
    describeMove,
    describeOrder,
    entryIdOf,
    indexOfEntry,
    moveItem,
    replayOp,
    type QueueOp,
} from './queue-ops';
import {
    activeRendererControls,
    findActiveRenderer,
    rendererCanMute,
    rendererMatchesActive,
    rendererSelectionId,
    type RendererCapabilitiesLike,
    type RendererControls,
} from '$lib/renderer-utils';

export interface Renderer {
    udn: string;
    renderer_id?: string;
    name: string;
    type: string;
    kind?: string;
    native_id?: string;
    cast_type?: string;
    icon_url?: string;
    icon_mime?: string;
    icon_width?: number;
    icon_height?: number;
    capabilities?: RendererCapabilitiesLike | null;
}

export interface PlayerState {
    renderers: Renderer[];
    renderer: string;
    renderer_id?: string;
    renderer_kind?: string;
    queue: Track[];
    current_index: number;
    // Server-side version of the queue's membership and order (#332). Sent
    // back as expected_revision with an edit; a stale one is refused (409)
    // and replayed against the fresh queue by entry id.
    queue_revision?: number;
    is_playing: boolean;
    position_seconds: number;
    volume: number | null;
    // Mute as the renderer reports it (UPnP events, Cast receiver status);
    // null/undefined when unknown.
    muted?: boolean | null;
    transport_state?: string;
    // Set by the server when the queue halted on its own rather than because
    // the listener stopped it — a renderer dropping out mid-track. Without it
    // the UI just goes quiet and looks broken.
    stopped_reason?: string | null;
    repeatMode: 'off' | 'all' | 'one';
    stream_quality?: string;
    stream_quality_label?: string;
    original_quality_label?: string;
    // Server-side audio output plan for the current track on a remote
    // renderer: what is sent and why (transcode reason, resulting quality).
    output_plan?: OutputPlan | null;
}

export interface OutputPlan {
    action: 'original' | 'remux' | 'decode' | 'lossy';
    format: string;
    mime_type: string;
    reason: string;
    source_label: string;
    quality_label: string;
    lossless: boolean;
}

export const playerState = writable<PlayerState>({
    renderers: [],
    renderer: '',
    queue: [],
    current_index: -1,
    is_playing: false,
    position_seconds: 0,
    volume: null,
    repeatMode: 'off'
});

// Transport controls the active renderer supports (capabilities.can_pause /
// can_seek). Defaults to everything enabled when capabilities are unknown.
export const rendererControls = derived<typeof playerState, RendererControls>(
    playerState,
    ($s) => activeRendererControls($s.renderers, $s.renderer),
);

// The active renderer takes mute commands (capabilities.can_mute).
export const canMute = derived<typeof playerState, boolean>(
    playerState,
    ($s) => rendererCanMute(findActiveRenderer($s.renderers, $s.renderer)),
);

// UI: Now Playing overlay visibility
export const nowPlayingVisible = writable<boolean>(false);

function mergeQueueArt(prev: Track[], next: Track[]): Track[] {
    if (!prev.length || !next.length) return next;
    const metadataById = new Map<number, Partial<Track>>();
    for (const t of prev) {
        if (!t?.id) continue;
        metadataById.set(t.id, {
            art_sha1: t.art_sha1 ?? null,
            loudness_lufs: t.loudness_lufs,
            true_peak_db: t.true_peak_db,
            loudness_gain_db: t.loudness_gain_db,
            loudness_gain_mode: t.loudness_gain_mode,
            loudness_target_lufs: t.loudness_target_lufs,
            loudness_normalized: t.loudness_normalized,
        });
    }
    return next.map((t) => {
        if (!t?.id) return t;
        const previous = metadataById.get(t.id);
        if (!previous) return t;
        return {
            ...t,
            art_sha1: t.art_sha1 || previous.art_sha1 || null,
            loudness_lufs: t.loudness_lufs ?? previous.loudness_lufs,
            true_peak_db: t.true_peak_db ?? previous.true_peak_db,
            loudness_gain_db: t.loudness_gain_db ?? previous.loudness_gain_db,
            loudness_gain_mode: t.loudness_gain_mode ?? previous.loudness_gain_mode,
            loudness_target_lufs: t.loudness_target_lufs ?? previous.loudness_target_lufs,
            loudness_normalized: t.loudness_normalized ?? previous.loudness_normalized,
        };
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

        const res = await fetchWithAuth(`/api/renderers?refresh=${force}`, {
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

            playerState.update(s => {
                const currentRenderer =
                    s.renderer && finalRenderers.some((r: Renderer) => rendererMatchesActive(r, s.renderer))
                        ? s.renderer
                        : `local:${myId}`;
                return { ...s, renderers: finalRenderers, renderer: currentRenderer };
            });

        } else {
            console.error('[refreshRenderers] Response not OK:', res.status, res.statusText);
        }
    } catch (e) {
        console.error('[refreshRenderers] Failed to refresh renderers', e);
    }
}

export async function setRenderer(rendererIdOrUdn: string) {
    try {
        const res = await fetchWithAuth('/api/player/renderer', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ renderer_id: rendererIdOrUdn })
        });
        if (res.ok) {
            const data = await res.json();
            const active = data.renderer_id || data.active || rendererIdOrUdn;
            // Reset volume for remote renderers — device volume is unknown
            // until the next sync_status poll fetches it.  Prevents stale
            // volume from previous renderer leaking into the new one.
            const isRemote = !active.startsWith("local");
            playerState.update(s => ({
                ...s,
                renderer: active,
                renderer_id: data.renderer_id || active,
                volume: isRemote ? null : s.volume,
                muted: null,
            }));
            await loadQueueFromServer();
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
        const res = await fetchWithAuth('/api/client-ip', { headers: { 'X-Jamarr-Client-Id': getClientId() } });
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
                queue_revision: data.queue_revision ?? s.queue_revision,
                position_seconds: data.position_seconds,
                is_playing: data.is_playing,
                renderer: data.renderer_id || data.renderer || `local:${getClientId()}`,
                renderer_id: data.renderer_id,
                renderer_kind: data.renderer_kind,
                // If server returns null (no history), keep existing volume (e.g. locally restored)
                // If server returns value, use it.
                volume: (data.volume !== null && data.volume !== undefined) ? data.volume : s.volume,
                muted: data.muted ?? null,
                stopped_reason: data.stopped_reason ?? null,
                output_plan: data.output_plan ?? null
            }));

        } else {
            console.error('[loadQueueFromServer] Failed, status:', res.status);
        }
    } catch (e) {
        console.error('[loadQueueFromServer] Exception:', e);
    }
}

export function selectionIdForRenderer(renderer: Renderer): string {
    return rendererSelectionId(renderer);
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
            const data = await res.json().catch(() => ({}));
            const state = data?.state;
            playerState.update(s => ({
                ...s,
                // The server answers with the queue as stored, entry ids
                // included; fall back to the local guess for an older server.
                queue: state?.queue ? mergeQueueArt(s.queue, state.queue) : [...s.queue, ...tracks],
                queue_revision: state?.queue_revision ?? s.queue_revision,
            }));
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
    const current = get(playerState);
    let newQueue: Track[];
    let op: QueueOp | null;

    if (Array.isArray(arg1)) {
        // A whole new order (shuffle).
        newQueue = arg1;
        op = describeOrder(arg1);
    } else if (typeof arg1 === 'number' && typeof arg2 === 'number') {
        // A drag: item at arg1 dropped before index arg2.
        newQueue = moveItem(current.queue, arg1, arg2);
        op = describeMove(current.queue, arg1, arg2);
    } else {
        console.error('[reorderQueue] Invalid arguments');
        return;
    }

    const currentEntry = entryIdOf(current.queue[current.current_index]);
    const currentTrackId = current.queue[current.current_index]?.id;

    const apply = (state: Record<string, unknown>, fallbackQueue: Track[]) => {
        const queue = (state.queue as Track[] | undefined) ?? fallbackQueue;
        playerState.update((s) => ({
            ...s,
            queue: mergeQueueArt(s.queue, queue),
            current_index:
                (state.current_index as number | undefined) ??
                (currentEntry
                    ? indexOfEntry(queue, currentEntry)
                    : currentTrackId
                      ? queue.findIndex((t: Track) => t.id === currentTrackId)
                      : -1),
            queue_revision: (state.queue_revision as number | undefined) ?? s.queue_revision,
            position_seconds: (state.position_seconds as number | undefined) ?? s.position_seconds,
            is_playing: (state.is_playing as boolean | undefined) ?? s.is_playing,
            transport_state: (state.transport_state as string | undefined) ?? s.transport_state,
        }));
    };

    const send = async (queue: Track[], expected: number | undefined) => {
        const body: Record<string, unknown> = { queue };
        if (expected !== undefined) body.expected_revision = expected;
        return fetchWithAuth('/api/player/queue/reorder', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify(body),
        });
    };

    try {
        const res = await send(newQueue, current.queue_revision);
        if (res.ok) {
            const data = await res.json();
            apply(data.state || {}, newQueue);
            return;
        }
        if (res.status !== 409) {
            console.error('[reorderQueue] Failed, status:', res.status, await res.text());
            return;
        }
        // The queue changed under us. Take the live state, then replay the
        // same operation (by entry id) against it, once.
        const detail = (await res.json().catch(() => ({})))?.detail ?? {};
        const live = detail.state || {};
        apply(live, current.queue);
        const liveQueue: Track[] = live.queue ?? get(playerState).queue;
        const replayed = op ? replayOp(liveQueue, op) : null;
        if (!replayed) {
            console.warn('[reorderQueue] Queue changed elsewhere; edit dropped');
            return;
        }
        const retry = await send(replayed, live.queue_revision ?? detail.queue_revision);
        if (retry.ok) {
            const data = await retry.json();
            apply(data.state || {}, replayed);
        } else {
            console.warn('[reorderQueue] Replay refused, status:', retry.status);
            if (retry.status === 409) {
                const again = (await retry.json().catch(() => ({})))?.detail?.state;
                if (again) apply(again, liveQueue);
            }
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
            const data = await res.json().catch(() => ({}));
            playerState.update(s => ({
                ...s,
                queue: [],
                current_index: -1,
                queue_revision: data?.state?.queue_revision ?? s.queue_revision,
                position_seconds: 0,
                is_playing: false,
                transport_state: 'STOPPED'
            }));

            void stopPlayback;
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
                queue_revision: newState.queue_revision ?? s.queue_revision,
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

// Advance the server's current_index and local store WITHOUT triggering
// playback. Used when the PlayerBar has already started the next track
// via a pre-armed <audio> element and only needs to sync state. Calling
// the normal playFromQueue() here would re-fetch the stream URL and
// interrupt the audio that is already playing.
export async function advanceIndexLocal(newIndex: number) {
    const hostname = typeof window !== 'undefined' ? window.location.hostname : '';
    const client_ip = await getClientIp();
    try {
        const res = await fetchWithAuth('/api/player/index', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ index: newIndex, hostname, client_ip }),
        });
        if (res.ok) {
            const data = await res.json();
            const newState = data.state || {};
            const mergedQueue = newState.queue
                ? mergeQueueArt(get(playerState).queue, newState.queue)
                : undefined;
            playerState.update((s) => ({
                ...s,
                queue: mergedQueue ?? s.queue,
                current_index: newState.current_index ?? newIndex,
                queue_revision: newState.queue_revision ?? s.queue_revision,
                is_playing: true,
                position_seconds: 0,
                transport_state: newState.transport_state ?? s.transport_state,
                renderer: newState.renderer ?? s.renderer,
                volume: newState.volume ?? s.volume,
            }));
        } else {
            console.error('[advanceIndexLocal] Failed, status:', res.status);
        }
    } catch (e) {
        console.error('[advanceIndexLocal] Exception:', e);
    }
}

// Pure helper: given current queue state, compute which track should be
// pre-armed as the next one to play. Returns null if nothing to arm.
export function computeNextTrackToArm(
    queue: Track[],
    currentIndex: number,
    repeatMode: 'off' | 'all' | 'one',
): { index: number; track: Track } | null {
    if (!queue.length || currentIndex < 0) return null;
    if (repeatMode === 'one') {
        const t = queue[currentIndex];
        return t ? { index: currentIndex, track: t } : null;
    }
    if (currentIndex < queue.length - 1) {
        return { index: currentIndex + 1, track: queue[currentIndex + 1] };
    }
    if (repeatMode === 'all' && queue.length > 0) {
        return { index: 0, track: queue[0] };
    }
    return null;
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


        if (!res.ok) {
            // The renderer refused the track (or never confirmed it); the
            // server has recorded why, so pull its state instead of claiming
            // playback.
            console.error('[playCurrentTrack] Play failed:', res.status, data?.detail);
            await loadQueueFromServer();
        } else if (data.status === 'local_playback') {
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

// A slider drag fires one input event per step, and for a UPnP renderer each
// one becomes a SOAP call to the device. Sending them all buries it: a Naim
// Uniti Atom took ~20 calls in two seconds, its responses slowed from 9ms to
// 1.4s, and it dropped the track it was playing. So keep at most one request in
// flight and coalesce everything that arrives meanwhile into a single follow-up
// — the user only cares about the value they land on, not the ones they dragged
// through.
const VOLUME_MIN_INTERVAL_MS = 150;

let volumeInFlight = false;
let volumePending: number | null = null;
let volumeLastSentAt = 0;
let volumeTimer: ReturnType<typeof setTimeout> | undefined;

async function flushVolume() {
    // Wait for the in-flight request; its finally block reschedules us.
    if (volumeInFlight || volumePending === null) return;

    const percent = volumePending;
    volumePending = null;
    volumeInFlight = true;
    volumeLastSentAt = Date.now();
    try {
        await fetchWithAuth('/api/player/volume', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ percent })
        });
    } catch (e) {
        console.error('Failed to set volume', e);
    } finally {
        volumeInFlight = false;
        // Someone moved the slider while we were away — send where they ended up.
        if (volumePending !== null) scheduleVolume();
    }
}

function scheduleVolume() {
    if (volumeTimer !== undefined) return;
    const wait = Math.max(0, VOLUME_MIN_INTERVAL_MS - (Date.now() - volumeLastSentAt));
    volumeTimer = setTimeout(() => {
        volumeTimer = undefined;
        flushVolume();
    }, wait);
}

export function setVolume(percent: number) {
    volumePending = percent;
    scheduleVolume();
}

/** Mute/unmute the active remote renderer. The store flips optimistically
 *  and reverts if the server refuses (400: the renderer can't mute). */
export async function setMuted(muted: boolean): Promise<boolean> {
    const previous = get(playerState).muted ?? null;
    playerState.update((s) => ({ ...s, muted }));
    try {
        const res = await fetchWithAuth('/api/player/mute', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ muted }),
        });
        if (!res.ok) throw new Error(`mute failed: ${res.status}`);
        const data = await res.json();
        const confirmed = typeof data?.muted === 'boolean' ? data.muted : muted;
        playerState.update((s) => ({ ...s, muted: confirmed }));
        return true;
    } catch (e) {
        console.error('Failed to set mute', e);
        playerState.update((s) => ({ ...s, muted: previous }));
        return false;
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
    // The renderer would ignore it; don't move the progress bar either.
    if (!activeRendererControls(s.renderers, s.renderer).canSeek) return;
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
