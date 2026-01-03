-- Add accent_color column to user table
-- Default to pink (#ff006e) if not set by user
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS accent_color TEXT DEFAULT '#ff006e';

-- Add index for potential future queries
CREATE INDEX IF NOT EXISTS idx_user_accent_color ON "user"(accent_color);
