-- Migration 029: Add protocol-neutral renderer backend fields.

ALTER TABLE renderer
    ADD COLUMN IF NOT EXISTS kind TEXT DEFAULT 'upnp',
    ADD COLUMN IF NOT EXISTS native_id TEXT,
    ADD COLUMN IF NOT EXISTS renderer_id TEXT,
    ADD COLUMN IF NOT EXISTS cast_uuid TEXT,
    ADD COLUMN IF NOT EXISTS cast_type TEXT,
    ADD COLUMN IF NOT EXISTS last_discovered_by TEXT DEFAULT 'server',
    ADD COLUMN IF NOT EXISTS available BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS enabled_by_default BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS renderer_metadata JSONB DEFAULT '{}'::jsonb;

UPDATE renderer
SET
    kind = COALESCE(kind, 'upnp'),
    native_id = COALESCE(native_id, udn),
    renderer_id = COALESCE(renderer_id, 'upnp:' || udn),
    last_discovered_by = COALESCE(last_discovered_by, 'server'),
    available = COALESCE(available, TRUE),
    enabled_by_default = COALESCE(enabled_by_default, TRUE),
    renderer_metadata = COALESCE(renderer_metadata, '{}'::jsonb)
WHERE udn IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_attribute a
          ON a.attrelid = t.oid
         AND a.attnum = ANY(c.conkey)
        WHERE t.relname = 'renderer'
          AND c.contype = 'u'
          AND a.attname = 'renderer_id'
    ) THEN
        ALTER TABLE renderer
            ADD CONSTRAINT renderer_renderer_id_unique UNIQUE (renderer_id);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_renderer_renderer_id
    ON renderer(renderer_id)
    WHERE renderer_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_renderer_cast_uuid
    ON renderer(cast_uuid)
    WHERE cast_uuid IS NOT NULL;

ALTER TABLE client_session
    ADD COLUMN IF NOT EXISTS active_renderer_id TEXT;

UPDATE client_session
SET active_renderer_id = CASE
    WHEN active_renderer_udn IS NULL THEN NULL
    WHEN active_renderer_udn LIKE 'local:%' THEN active_renderer_udn
    WHEN active_renderer_udn LIKE 'upnp:%' THEN active_renderer_udn
    WHEN active_renderer_udn LIKE 'cast:%' THEN active_renderer_udn
    ELSE 'upnp:' || active_renderer_udn
END
WHERE active_renderer_id IS NULL;
