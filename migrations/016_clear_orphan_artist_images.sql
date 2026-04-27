UPDATE artist
SET image_url = NULL, image_source = NULL
WHERE image_url IS NOT NULL AND artwork_id IS NULL;
