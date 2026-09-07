-- Sample-dates plan, Task 5. Additive only: every column is NULLABLE, so this
-- is safe to apply while the API is serving. No DROP, no DELETE.
-- Applied by ensure_mosaic() on startup; this file is the written record.
ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS sampling_date   DATE;
ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS sampling_month  SMALLINT;
ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS sampling_day    SMALLINT;
ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS campaign_name   TEXT;
ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS campaign_start  DATE;
ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS campaign_end    DATE;
ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS core_comment    TEXT;
ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS date_precision  TEXT;
