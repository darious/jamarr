// Queue edits expressed in entry ids, so they can be replayed against a
// fresher queue after the server refuses a stale one (409 queue_conflict).
//
// Every queued item carries an `entry_id` the server assigned when it entered
// the queue (#325); the same track can sit in a queue twice, so moves are
// never described by track id or by index alone.
import type { Track } from '$api';

/** A single move: put `entryId` immediately before `beforeEntryId` (or last). */
export interface MoveOp {
    kind: 'move';
    entryId: string;
    beforeEntryId: string | null;
}

/** A whole new order, e.g. shuffle. Replayed by entry id; unknown entries are kept in place. */
export interface OrderOp {
    kind: 'order';
    entryIds: string[];
}

export type QueueOp = MoveOp | OrderOp;

export function entryIdOf(track: Track | undefined | null): string | null {
    return track?.entry_id ?? null;
}

/** Array move with "insert before index" semantics, as both drag UIs use. */
export function moveItem<T>(items: T[], from: number, to: number): T[] {
    const next = [...items];
    const [moved] = next.splice(from, 1);
    const target = to > from ? to - 1 : to;
    next.splice(target, 0, moved);
    return next;
}

/**
 * Describe a drag as a MoveOp. `to` is the index the item is dropped before
 * (so `to === queue.length` means "to the end"). Null when the queue has no
 * entry ids yet (an older server), in which case only a plain order is sent.
 */
export function describeMove(queue: Track[], from: number, to: number): MoveOp | null {
    const moved = queue[from];
    const entryId = entryIdOf(moved);
    if (!entryId) return null;
    // The item that will follow the moved one, in the pre-move queue.
    let before: Track | undefined;
    for (let i = to; i < queue.length; i++) {
        if (i === from) continue;
        before = queue[i];
        break;
    }
    const beforeEntryId = before ? entryIdOf(before) : null;
    if (before && !beforeEntryId) return null;
    return { kind: 'move', entryId, beforeEntryId };
}

export function describeOrder(queue: Track[]): OrderOp | null {
    const entryIds: string[] = [];
    for (const t of queue) {
        const id = entryIdOf(t);
        if (!id) return null;
        entryIds.push(id);
    }
    return { kind: 'order', entryIds };
}

/**
 * Apply `op` to a (fresher) queue. Returns null when the operation no longer
 * makes sense there: the moved entry is gone, or an ordering names nothing
 * the queue still has.
 */
export function replayOp(queue: Track[], op: QueueOp): Track[] | null {
    if (op.kind === 'move') {
        const from = queue.findIndex((t) => entryIdOf(t) === op.entryId);
        if (from < 0) return null;
        let to: number;
        if (op.beforeEntryId === null) {
            to = queue.length;
        } else {
            to = queue.findIndex((t) => entryIdOf(t) === op.beforeEntryId);
            if (to < 0) return null;
        }
        if (to === from || to === from + 1) return [...queue];
        return moveItem(queue, from, to);
    }
    const byId = new Map<string, Track>();
    for (const t of queue) {
        const id = entryIdOf(t);
        if (id) byId.set(id, t);
    }
    const ordered: Track[] = [];
    for (const id of op.entryIds) {
        const t = byId.get(id);
        if (t) {
            ordered.push(t);
            byId.delete(id);
        }
    }
    if (!ordered.length) return null;
    // Entries added elsewhere since the order was decided stay, at the end.
    return [...ordered, ...queue.filter((t) => byId.has(entryIdOf(t) ?? ''))];
}

/** Index of the entry with `entryId`, or -1. */
export function indexOfEntry(queue: Track[], entryId: string | null | undefined): number {
    if (!entryId) return -1;
    return queue.findIndex((t) => entryIdOf(t) === entryId);
}
