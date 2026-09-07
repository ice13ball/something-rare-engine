-- Units audit 2026-09-04, finding §1.
--
-- WRI Aqueduct writes -9999 for "no data". This sync stored it as a 0-5 risk
-- score, so every mean, ordering and colour ramp over these columns read as
-- "very low risk" rather than as an error.
--
-- The ingest was fixed first (domains/land/hazards.py, _score_or_none), so no
-- new sentinel can arrive. This repairs the rows already loaded.
--
-- _sync_water_risk is INSERT ... ON CONFLICT (string_id) DO NOTHING behind a
-- row-count guard that returns 0 even under force=True (hazards.py:668-682),
-- because the load is ogr2ogr -append and re-running would double the table.
-- It will never revisit these rows. This file is the only path.
--
-- ⛔ Take a pg_dump of water_risk before running this.
--    Taken 2026-09-04: backups/water_risk.pre-sentinel-migration.sql (435M)
BEGIN;

UPDATE water_risk SET bws_score           = NULL WHERE bws_score           = -9999;
UPDATE water_risk SET bwd_score           = NULL WHERE bwd_score           = -9999;
UPDATE water_risk SET drr_score           = NULL WHERE drr_score           = -9999;
UPDATE water_risk SET rfr_score           = NULL WHERE rfr_score           = -9999;
UPDATE water_risk SET w_awr_min_tot_score = NULL WHERE w_awr_min_tot_score = -9999;

COMMIT;
