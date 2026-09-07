-- 0001_retire_gfw.sql
-- Phase 1: Retire Global Fishing Watch (GFW) dependency.
-- DESTRUCTIVE: drops GFW-derived tables and rewrites vessel_events in place.
-- Run manually once on the VPS:
--   psql "$DATABASE_URL" -f backend/migrations/0001_retire_gfw.sql
--
-- After apply: restart abyssal-api (systemd) so the new schema is picked up.
-- The ais-ingestor service + /v2/vessels/* endpoints are the replacement.

BEGIN;

-- 1. Drop GFW-only tables and materialized views ---------------------------
DROP MATERIALIZED VIEW IF EXISTS mv_hotspot_fishing_pressure CASCADE;
DROP TABLE IF EXISTS fishing_pressure_tiles CASCADE;
DROP TABLE IF EXISTS fishing_pressure_raw   CASCADE;
DROP TABLE IF EXISTS gfw_api_calls          CASCADE;

-- 2. Rewrite vessel_events in place ----------------------------------------
-- Old shape (GFW loitering/encounter): event_id, source, vessel_id FK→vessels,
--   start_time, end_time, duration_hours, lat, lon, geom, is_high_threat,
--   inside_polygon_type, inside_polygon_id, raw.
-- New shape (dark-vessel / SAR×AIS correlation): event_id, ts, lat, lon, geom,
--   classification ENUM, matched_mmsi, ais_gap_seconds, sar_detection_id,
--   s2_thumbnail_url, inside_polygon_type, inside_polygon_id, raw.

-- Drop the old FK first so we can drop `vessels`.
ALTER TABLE IF EXISTS vessel_events
    DROP CONSTRAINT IF EXISTS vessel_events_vessel_id_fkey;

-- Drop GFW-shaped columns.
ALTER TABLE IF EXISTS vessel_events
    DROP COLUMN IF EXISTS vessel_id,
    DROP COLUMN IF EXISTS duration_hours,
    DROP COLUMN IF EXISTS is_high_threat,
    DROP COLUMN IF EXISTS end_time,
    DROP COLUMN IF EXISTS source;

-- Indexes that referenced dropped columns.
DROP INDEX IF EXISTS idx_vessel_events_vessel;
DROP INDEX IF EXISTS idx_vessel_events_threat;
DROP INDEX IF EXISTS idx_vessel_events_start;

-- Rename start_time → ts for the new (point-in-time) semantics.
ALTER TABLE IF EXISTS vessel_events
    RENAME COLUMN start_time TO ts;

-- Classification ENUM.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vessel_event_class') THEN
        CREATE TYPE vessel_event_class AS ENUM ('matched', 'dark', 'ambiguous');
    END IF;
END$$;

-- Add new columns.
ALTER TABLE IF EXISTS vessel_events
    ADD COLUMN IF NOT EXISTS classification     vessel_event_class,
    ADD COLUMN IF NOT EXISTS matched_mmsi       BIGINT,
    ADD COLUMN IF NOT EXISTS ais_gap_seconds    INTEGER,
    ADD COLUMN IF NOT EXISTS sar_detection_id   TEXT,
    ADD COLUMN IF NOT EXISTS s2_thumbnail_url   TEXT;

-- The old rows are GFW loitering/encounters and no longer have a valid shape.
-- Purge them; new rows come from the SAR×AIS correlator (Phase 3).
TRUNCATE TABLE vessel_events;

-- Recreate indexes on the new schema.
CREATE INDEX IF NOT EXISTS idx_vessel_events_ts
    ON vessel_events (ts DESC);
CREATE INDEX IF NOT EXISTS idx_vessel_events_classification
    ON vessel_events (classification);
CREATE INDEX IF NOT EXISTS idx_vessel_events_matched_mmsi
    ON vessel_events (matched_mmsi)
    WHERE matched_mmsi IS NOT NULL;

-- 3. Drop the GFW `vessels` lookup table -----------------------------------
-- Vessel identity now comes from ais_vessels (live AIS ingest).
-- contractor_vessels is auto-discovered from AIS loitering in ISA concessions
-- (see vessel_events.auto_discover_contractors). No manual CSV.
DROP TABLE IF EXISTS vessels CASCADE;

COMMIT;

-- Post-apply sanity check (run manually):
--   \d vessel_events
--   SELECT COUNT(*) FROM vessel_events;      -- should be 0
--   SELECT to_regclass('public.vessels');    -- should be NULL
--   SELECT to_regclass('public.fishing_pressure_tiles');  -- should be NULL
