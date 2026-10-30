-- Queue revision per renderer state (#332): moves whenever the stored queue's
-- membership or order changes, never on progress or index writes. Clients
-- send it back as expected_revision so a stale reorder is refused (409)
-- instead of overwriting a newer edit.
ALTER TABLE renderer_state ADD COLUMN IF NOT EXISTS queue_revision BIGINT NOT NULL DEFAULT 0;
