import type { Track } from '$api';
import { getArtUrl } from '$lib/api';

export interface MediaSessionActions {
    onPlay: () => void;
    onPause: () => void;
    onNext: () => void;
    onPrevious: () => void;
    onSeekTo?: (seconds: number) => void;
    onStop?: () => void;
}

function hasMediaSession(): boolean {
    return (
        typeof navigator !== 'undefined' &&
        'mediaSession' in navigator &&
        typeof (navigator as any).mediaSession?.setActionHandler === 'function'
    );
}

function hasMediaMetadataCtor(): boolean {
    return typeof (globalThis as any).MediaMetadata === 'function';
}

function toAbsolute(url: string): string {
    if (!url) return url;
    if (url.startsWith('http://') || url.startsWith('https://')) return url;
    if (typeof window === 'undefined') return url;
    return window.location.origin + (url.startsWith('/') ? url : `/${url}`);
}

export function buildArtwork(track: { art_sha1?: string | null }): MediaImage[] {
    if (!track || !track.art_sha1) return [];
    return [100, 300, 600].map((size) => ({
        src: toAbsolute(getArtUrl(track.art_sha1, size)),
        sizes: `${size}x${size}`,
        type: 'image/jpeg',
    }));
}

export function registerActionHandlers(actions: MediaSessionActions): void {
    if (!hasMediaSession()) return;
    const ms = navigator.mediaSession;

    const safeSet = (action: MediaSessionAction, handler: MediaSessionActionHandler | null) => {
        try {
            ms.setActionHandler(action, handler);
        } catch {
            /* action unsupported by browser */
        }
    };

    safeSet('play', () => actions.onPlay());
    safeSet('pause', () => actions.onPause());
    safeSet('nexttrack', () => actions.onNext());
    safeSet('previoustrack', () => actions.onPrevious());
    if (actions.onStop) safeSet('stop', () => actions.onStop!());
    if (actions.onSeekTo) {
        safeSet('seekto', (details) => {
            const d = details as MediaSessionActionDetails & { seekTime?: number };
            if (typeof d.seekTime === 'number' && Number.isFinite(d.seekTime)) {
                actions.onSeekTo!(d.seekTime);
            }
        });
    }
}

export function clearActionHandlers(): void {
    if (!hasMediaSession()) return;
    const actions: MediaSessionAction[] = [
        'play',
        'pause',
        'nexttrack',
        'previoustrack',
        'stop',
        'seekto',
    ];
    for (const a of actions) {
        try {
            navigator.mediaSession.setActionHandler(a, null);
        } catch {
            /* ignore */
        }
    }
}

export function setMetadata(track: Track | null | undefined): void {
    if (!hasMediaSession()) return;
    if (!track) {
        try {
            navigator.mediaSession.metadata = null;
        } catch {
            /* ignore */
        }
        return;
    }
    if (!hasMediaMetadataCtor()) return;
    try {
        navigator.mediaSession.metadata = new MediaMetadata({
            title: track.title || '',
            artist: track.artist || '',
            album: track.album || '',
            artwork: buildArtwork(track),
        });
    } catch (e) {
        console.warn('[media-session] Failed to set metadata:', e);
    }
}

export function setPlaybackState(isPlaying: boolean, hasTrack: boolean): void {
    if (!hasMediaSession()) return;
    try {
        navigator.mediaSession.playbackState = !hasTrack
            ? 'none'
            : isPlaying
              ? 'playing'
              : 'paused';
    } catch {
        /* ignore */
    }
}

export function setPositionState(
    position: number,
    duration: number,
    playbackRate: number = 1,
): void {
    if (!hasMediaSession()) return;
    const ms = navigator.mediaSession as MediaSession & {
        setPositionState?: (state?: MediaPositionState) => void;
    };
    if (typeof ms.setPositionState !== 'function') return;
    if (!Number.isFinite(duration) || duration <= 0) return;
    if (!Number.isFinite(position) || position < 0) position = 0;
    const clamped = Math.min(position, duration);
    try {
        ms.setPositionState({ duration, position: clamped, playbackRate });
    } catch {
        /* ignore invalid state (e.g. position > duration) */
    }
}

export function clearAll(): void {
    if (!hasMediaSession()) return;
    try {
        navigator.mediaSession.metadata = null;
    } catch {
        /* ignore */
    }
    try {
        navigator.mediaSession.playbackState = 'none';
    } catch {
        /* ignore */
    }
    clearActionHandlers();
}
