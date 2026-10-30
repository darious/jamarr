import { describe, it, expect } from 'vitest';
import type { Track } from '$api';
import { describeMove, describeOrder, indexOfEntry, moveItem, replayOp } from './queue-ops';

const t = (id: number, entry: string | null = `e${id}`): Track =>
    ({
        id,
        path: `/music/${id}.flac`,
        title: `Track ${id}`,
        artist: 'A',
        album: 'B',
        album_artist: null,
        track_no: id,
        disc_no: 1,
        date: null,
        duration_seconds: 100,
        art_sha1: null,
        codec: 'flac',
        bitrate: null,
        sample_rate_hz: null,
        bit_depth: null,
        ...(entry ? { entry_id: entry } : {}),
    }) as Track;

const ids = (q: Track[]) => q.map((x) => x.entry_id);

describe('moveItem', () => {
    it('moves forward with insert-before semantics', () => {
        expect(ids(moveItem([t(1), t(2), t(3)], 0, 3))).toEqual(['e2', 'e3', 'e1']);
        expect(ids(moveItem([t(1), t(2), t(3)], 0, 2))).toEqual(['e2', 'e1', 'e3']);
    });
    it('moves backward', () => {
        expect(ids(moveItem([t(1), t(2), t(3)], 2, 0))).toEqual(['e3', 'e1', 'e2']);
    });
});

describe('describeMove', () => {
    it('names the entry and the one it lands before', () => {
        expect(describeMove([t(1), t(2), t(3)], 2, 0)).toEqual({ kind: 'move', entryId: 'e3', beforeEntryId: 'e1' });
        expect(describeMove([t(1), t(2), t(3)], 0, 3)).toEqual({ kind: 'move', entryId: 'e1', beforeEntryId: null });
        // Dropping "before" the item right after itself skips over itself.
        expect(describeMove([t(1), t(2), t(3)], 0, 2)).toEqual({ kind: 'move', entryId: 'e1', beforeEntryId: 'e3' });
    });
    it('is null without entry ids (older server)', () => {
        expect(describeMove([t(1, null), t(2)], 0, 2)).toBeNull();
    });
});

describe('replayOp', () => {
    it('replays a move after another client appended', () => {
        const op = describeMove([t(1), t(2), t(3)], 2, 0)!;
        const fresh = [t(1), t(2), t(3), t(4)];
        expect(ids(replayOp(fresh, op)!)).toEqual(['e3', 'e1', 'e2', 'e4']);
    });
    it('replays a move to the end as "to the end" of the fresh queue', () => {
        const op = describeMove([t(1), t(2), t(3)], 0, 3)!;
        expect(ids(replayOp([t(1), t(2), t(3), t(4)], op)!)).toEqual(['e2', 'e3', 'e4', 'e1']);
    });
    it('tells duplicates of one track apart', () => {
        const q = [t(1, 'a1'), t(2, 'b'), t(1, 'a2')];
        const op = describeMove(q, 2, 0)!;
        expect(ids(replayOp(q, op)!)).toEqual(['a2', 'a1', 'b']);
    });
    it('gives up when the moved entry is gone', () => {
        const op = describeMove([t(1), t(2), t(3)], 2, 0)!;
        expect(replayOp([t(1), t(2)], op)).toBeNull();
    });
    it('replays an order and keeps entries it did not know about', () => {
        const op = describeOrder([t(3), t(1), t(2)])!;
        const fresh = [t(1), t(2), t(4), t(3)];
        expect(ids(replayOp(fresh, op)!)).toEqual(['e3', 'e1', 'e2', 'e4']);
    });
});

describe('indexOfEntry', () => {
    it('finds by entry id, not track id', () => {
        const q = [t(1, 'a1'), t(2, 'b'), t(1, 'a2')];
        expect(indexOfEntry(q, 'a2')).toBe(2);
        expect(indexOfEntry(q, null)).toBe(-1);
    });
});
