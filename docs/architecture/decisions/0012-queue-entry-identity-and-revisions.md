# ADR-0012: Queue entry identity and optimistic revisions

- **Status:** Accepted
- **Date:** 2026-10-30 (#325, #332)

## Context

The server-owned queue is a JSON list of track dicts in `renderer_state`,
edited by whole-list replacement: a client reads the state, rearranges the
list and posts it back. Two defects followed from that shape.

- **Occurrences were matched by track id.** A queue can hold the same track
  twice (an album followed by a playlist that includes one of its tracks).
  After a reorder the server found "the current track" by its first matching
  track id, so with `[A, B, A]` and the last A playing, the first A could
  become current, and removing one A could remove the other. Clients had no
  way to say which one they meant.
- **Edits were unconditional.** A delayed reorder from one client replaced
  the list after another client had appended or removed, and the second
  client's change silently disappeared. Progress reports from the browser
  also wrote the whole row back from their own read, so even a position tick
  could undo an edit that landed between its read and its write.

Options considered: normalising the queue into rows (a real table with
stable primary keys and `ORDER BY position`), which fixes identity but is a
larger migration touching every reader and the renderer backends; or keeping
the JSON list and adding identity and versioning to it. Android, the TUI and
the web all consume the list shape, and the UPnP/Cast staging code indexes
into it positionally.

## Decision

Keep the JSON list and make it safe to edit:

- Every queued item carries an **`entry_id`** the server assigns when the
  track enters a queue. Reorder matches on it; clients cannot supply one
  where tracks are added. Items from before the change get deterministic
  ids on read until the next write stores them.
- The row carries a **`queue_revision`** that moves only when the stored
  queue text changes. Mutations accept an optional `expected_revision`; the
  check and the write are one conditional statement. A mismatch is a 409
  carrying the live revision and state, so the client can replay its edit by
  entry id. Omitting the revision keeps last-writer-wins for older clients.
- **Status paths never write the queue.** Progress, pause, seek and volume
  touch status columns; the history `logged` flag is set on its single entry
  with a compare-and-swap on the stored text.

## Consequences

- Duplicate tracks behave: moving or removing one occurrence leaves the
  other alone, and the playing entry follows a reorder wherever it goes.
- Concurrent editors see a refusal instead of losing work. The web replays a
  drag against the fresh queue once; the TUI refreshes. Clients that ignore
  revisions keep working as before, so the change rolls out without a
  flag day. Clients that *do* send revisions will see occasional 409s
  during normal use (another client edited, or the user dragged twice
  quickly); handling them is now part of the contract.
- The queue is still a JSON blob: a renderer backend that wants per-item
  state keeps reading the list, and large queues are still rewritten whole
  on each edit. A normalised table remains possible later; entry ids are
  the primary key it would need, so this step is not wasted.
- Revisions are per renderer state row, not global; moving a queue between
  renderers starts a new revision line.
