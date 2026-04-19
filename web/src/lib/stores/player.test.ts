import { describe, it, expect } from 'vitest';
import type { Track } from '$api';
import { computeNextTrackToArm } from './player';

const makeTrack = (id: number, overrides: Partial<Track> = {}): Track => ({
    id,
    path: `/music/${id}.flac`,
    title: `Track ${id}`,
    artist: 'Test Artist',
    album: 'Test Album',
    album_artist: null,
    track_no: id,
    disc_no: 1,
    date: null,
    duration_seconds: 180,
    art_sha1: null,
    codec: 'flac',
    bitrate: null,
    sample_rate_hz: null,
    bit_depth: null,
    ...overrides,
});

describe('computeNextTrackToArm', () => {
    it('returns next track when in middle of queue (repeat off)', () => {
        const queue = [makeTrack(1), makeTrack(2), makeTrack(3)];
        const result = computeNextTrackToArm(queue, 0, 'off');
        expect(result).toEqual({ index: 1, track: queue[1] });
    });

    it('returns null at end of queue with repeat off', () => {
        const queue = [makeTrack(1), makeTrack(2)];
        expect(computeNextTrackToArm(queue, 1, 'off')).toBeNull();
    });

    it('wraps to first track at end of queue with repeat all', () => {
        const queue = [makeTrack(10), makeTrack(20), makeTrack(30)];
        const result = computeNextTrackToArm(queue, 2, 'all');
        expect(result).toEqual({ index: 0, track: queue[0] });
    });

    it('still advances within queue with repeat all', () => {
        const queue = [makeTrack(1), makeTrack(2), makeTrack(3)];
        const result = computeNextTrackToArm(queue, 0, 'all');
        expect(result).toEqual({ index: 1, track: queue[1] });
    });

    it('returns same track with repeat one', () => {
        const queue = [makeTrack(1), makeTrack(2), makeTrack(3)];
        const result = computeNextTrackToArm(queue, 1, 'one');
        expect(result).toEqual({ index: 1, track: queue[1] });
    });

    it('repeat one at end of queue still returns the current track', () => {
        const queue = [makeTrack(1), makeTrack(2)];
        const result = computeNextTrackToArm(queue, 1, 'one');
        expect(result).toEqual({ index: 1, track: queue[1] });
    });

    it('returns null for empty queue', () => {
        expect(computeNextTrackToArm([], 0, 'off')).toBeNull();
        expect(computeNextTrackToArm([], 0, 'all')).toBeNull();
        expect(computeNextTrackToArm([], 0, 'one')).toBeNull();
    });

    it('returns null when current_index is negative (no track playing)', () => {
        const queue = [makeTrack(1), makeTrack(2)];
        expect(computeNextTrackToArm(queue, -1, 'off')).toBeNull();
        expect(computeNextTrackToArm(queue, -1, 'all')).toBeNull();
        expect(computeNextTrackToArm(queue, -1, 'one')).toBeNull();
    });

    it('single-track queue with repeat off returns null', () => {
        const queue = [makeTrack(1)];
        expect(computeNextTrackToArm(queue, 0, 'off')).toBeNull();
    });

    it('single-track queue with repeat all wraps to itself', () => {
        const queue = [makeTrack(1)];
        const result = computeNextTrackToArm(queue, 0, 'all');
        expect(result).toEqual({ index: 0, track: queue[0] });
    });
});
