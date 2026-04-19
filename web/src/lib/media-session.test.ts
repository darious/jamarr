import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { Track } from '$api';
import {
    buildArtwork,
    clearAll,
    clearActionHandlers,
    registerActionHandlers,
    setMetadata,
    setPlaybackState,
    setPositionState,
} from './media-session';

type Handler = ((details: any) => void) | null;

function mockMediaSession() {
    const handlers: Record<string, Handler> = {};
    const ms = {
        metadata: null as any,
        playbackState: 'none' as MediaSessionPlaybackState,
        setActionHandler: vi.fn((action: string, handler: Handler) => {
            handlers[action] = handler;
        }),
        setPositionState: vi.fn(),
    };
    Object.defineProperty(navigator, 'mediaSession', {
        configurable: true,
        value: ms,
    });
    // Provide a MediaMetadata constructor that records the init dict.
    (globalThis as any).MediaMetadata = class {
        title: string;
        artist: string;
        album: string;
        artwork: MediaImage[];
        constructor(init: MediaMetadataInit) {
            this.title = init.title || '';
            this.artist = init.artist || '';
            this.album = init.album || '';
            this.artwork = (init.artwork as MediaImage[]) || [];
        }
    };
    return { ms, handlers };
}

function removeMediaSession() {
    Object.defineProperty(navigator, 'mediaSession', {
        configurable: true,
        value: undefined,
    });
    delete (globalThis as any).MediaMetadata;
}

const makeTrack = (overrides: Partial<Track> = {}): Track => ({
    id: 1,
    path: '/music/a.flac',
    title: 'Test Title',
    artist: 'Test Artist',
    album: 'Test Album',
    album_artist: null,
    track_no: 1,
    disc_no: 1,
    date: null,
    duration_seconds: 240,
    art_sha1: 'abc123',
    codec: 'flac',
    bitrate: null,
    sample_rate_hz: null,
    bit_depth: null,
    ...overrides,
});

describe('media-session: environment safety', () => {
    beforeEach(() => {
        removeMediaSession();
    });

    it('no-ops silently when mediaSession is missing', () => {
        expect(() => setMetadata(makeTrack())).not.toThrow();
        expect(() => setPlaybackState(true, true)).not.toThrow();
        expect(() => setPositionState(10, 100)).not.toThrow();
        expect(() => registerActionHandlers({
            onPlay: () => {}, onPause: () => {},
            onNext: () => {}, onPrevious: () => {},
        })).not.toThrow();
        expect(() => clearActionHandlers()).not.toThrow();
        expect(() => clearAll()).not.toThrow();
    });
});

describe('buildArtwork', () => {
    it('returns three sizes with absolute URLs when art_sha1 is set', () => {
        const art = buildArtwork({ art_sha1: 'abc123' });
        expect(art).toHaveLength(3);
        expect(art.map((a) => a.sizes)).toEqual(['100x100', '300x300', '600x600']);
        for (const a of art) {
            expect(a.type).toBe('image/jpeg');
            expect(a.src).toMatch(/^https?:\/\/.+\/api\/art\/file\/abc123\?max_size=\d+$/);
        }
    });

    it('returns empty array when art_sha1 is missing', () => {
        expect(buildArtwork({ art_sha1: null })).toEqual([]);
        expect(buildArtwork({})).toEqual([]);
    });
});

describe('setMetadata', () => {
    let mock: ReturnType<typeof mockMediaSession>;
    beforeEach(() => {
        mock = mockMediaSession();
    });

    it('populates MediaMetadata from track fields', () => {
        setMetadata(makeTrack({ title: 'Song', artist: 'Band', album: 'Record' }));
        expect(mock.ms.metadata).not.toBeNull();
        expect(mock.ms.metadata.title).toBe('Song');
        expect(mock.ms.metadata.artist).toBe('Band');
        expect(mock.ms.metadata.album).toBe('Record');
        expect(mock.ms.metadata.artwork).toHaveLength(3);
    });

    it('clears metadata when passed null', () => {
        mock.ms.metadata = { title: 'old' };
        setMetadata(null);
        expect(mock.ms.metadata).toBeNull();
    });

    it('handles tracks with missing artwork', () => {
        setMetadata(makeTrack({ art_sha1: null }));
        expect(mock.ms.metadata.artwork).toEqual([]);
    });
});

describe('setPlaybackState', () => {
    let mock: ReturnType<typeof mockMediaSession>;
    beforeEach(() => {
        mock = mockMediaSession();
    });

    it('sets "playing" when playing with a track', () => {
        setPlaybackState(true, true);
        expect(mock.ms.playbackState).toBe('playing');
    });

    it('sets "paused" when paused with a track', () => {
        setPlaybackState(false, true);
        expect(mock.ms.playbackState).toBe('paused');
    });

    it('sets "none" when no track regardless of isPlaying', () => {
        setPlaybackState(true, false);
        expect(mock.ms.playbackState).toBe('none');
        setPlaybackState(false, false);
        expect(mock.ms.playbackState).toBe('none');
    });
});

describe('setPositionState', () => {
    let mock: ReturnType<typeof mockMediaSession>;
    beforeEach(() => {
        mock = mockMediaSession();
    });

    it('forwards valid position/duration', () => {
        setPositionState(30, 240);
        expect(mock.ms.setPositionState).toHaveBeenCalledWith({
            duration: 240,
            position: 30,
            playbackRate: 1,
        });
    });

    it('clamps position to duration', () => {
        setPositionState(999, 240);
        expect(mock.ms.setPositionState).toHaveBeenCalledWith(
            expect.objectContaining({ position: 240, duration: 240 }),
        );
    });

    it('coerces negative position to 0', () => {
        setPositionState(-5, 240);
        expect(mock.ms.setPositionState).toHaveBeenCalledWith(
            expect.objectContaining({ position: 0 }),
        );
    });

    it('skips when duration is invalid', () => {
        setPositionState(10, 0);
        setPositionState(10, NaN);
        setPositionState(10, -1);
        expect(mock.ms.setPositionState).not.toHaveBeenCalled();
    });

    it('swallows exceptions thrown by setPositionState', () => {
        mock.ms.setPositionState.mockImplementation(() => {
            throw new Error('invalid state');
        });
        expect(() => setPositionState(10, 100)).not.toThrow();
    });
});

describe('registerActionHandlers', () => {
    let mock: ReturnType<typeof mockMediaSession>;
    beforeEach(() => {
        mock = mockMediaSession();
    });

    it('registers play/pause/next/previous handlers', () => {
        const onPlay = vi.fn();
        const onPause = vi.fn();
        const onNext = vi.fn();
        const onPrevious = vi.fn();
        registerActionHandlers({ onPlay, onPause, onNext, onPrevious });

        mock.handlers.play?.({});
        mock.handlers.pause?.({});
        mock.handlers.nexttrack?.({});
        mock.handlers.previoustrack?.({});
        expect(onPlay).toHaveBeenCalledTimes(1);
        expect(onPause).toHaveBeenCalledTimes(1);
        expect(onNext).toHaveBeenCalledTimes(1);
        expect(onPrevious).toHaveBeenCalledTimes(1);
    });

    it('passes seekTime through to onSeekTo', () => {
        const onSeekTo = vi.fn();
        registerActionHandlers({
            onPlay: () => {}, onPause: () => {},
            onNext: () => {}, onPrevious: () => {},
            onSeekTo,
        });
        mock.handlers.seekto?.({ action: 'seekto', seekTime: 42 });
        expect(onSeekTo).toHaveBeenCalledWith(42);
    });

    it('ignores seekto calls with no seekTime', () => {
        const onSeekTo = vi.fn();
        registerActionHandlers({
            onPlay: () => {}, onPause: () => {},
            onNext: () => {}, onPrevious: () => {},
            onSeekTo,
        });
        mock.handlers.seekto?.({ action: 'seekto' });
        expect(onSeekTo).not.toHaveBeenCalled();
    });

    it('skips unsupported actions without failing', () => {
        mock.ms.setActionHandler.mockImplementation((action: string) => {
            if (action === 'seekto') throw new Error('not supported');
        });
        expect(() =>
            registerActionHandlers({
                onPlay: () => {}, onPause: () => {},
                onNext: () => {}, onPrevious: () => {},
                onSeekTo: () => {},
            }),
        ).not.toThrow();
    });
});

describe('clearAll', () => {
    it('clears metadata, playbackState, and handlers', () => {
        const mock = mockMediaSession();
        setMetadata(makeTrack());
        setPlaybackState(true, true);
        registerActionHandlers({
            onPlay: () => {}, onPause: () => {},
            onNext: () => {}, onPrevious: () => {},
        });
        clearAll();
        expect(mock.ms.metadata).toBeNull();
        expect(mock.ms.playbackState).toBe('none');
        expect(mock.ms.setActionHandler).toHaveBeenCalledWith('play', null);
        expect(mock.ms.setActionHandler).toHaveBeenCalledWith('pause', null);
        expect(mock.ms.setActionHandler).toHaveBeenCalledWith('nexttrack', null);
        expect(mock.ms.setActionHandler).toHaveBeenCalledWith('previoustrack', null);
    });
});
