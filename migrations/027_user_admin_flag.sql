ALTER TABLE "user"
ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE "user"
SET is_admin = FALSE
WHERE username <> 'chris';

UPDATE "user"
SET is_admin = TRUE
WHERE username = 'chris';

ALTER TABLE "user"
ALTER COLUMN is_admin SET DEFAULT FALSE;

ALTER TABLE "user"
ALTER COLUMN is_admin SET NOT NULL;
