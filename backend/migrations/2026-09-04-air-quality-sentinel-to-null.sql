-- Units audit 2026-09-04, finding §2. Same shape as the water_risk migration.
-- ⛔ Take a pg_dump of air_quality_stations before running this.
BEGIN;
UPDATE air_quality_stations SET pm25 = NULL WHERE pm25 IN (-9999, -999);
UPDATE air_quality_stations SET so2  = NULL WHERE so2  IN (-9999, -999);
UPDATE air_quality_stations SET no2  = NULL WHERE no2  IN (-9999, -999);
UPDATE air_quality_stations SET o3   = NULL WHERE o3   IN (-9999, -999);
UPDATE air_quality_stations SET pm10 = NULL WHERE pm10 IN (-9999, -999);
UPDATE air_quality_stations SET no   = NULL WHERE no   IN (-9999, -999);
UPDATE air_quality_stations SET co   = NULL WHERE co   IN (-9999, -999);
UPDATE air_quality_stations SET nox  = NULL WHERE nox  IN (-9999, -999);
UPDATE air_quality_stations SET bc   = NULL WHERE bc   IN (-9999, -999);
COMMIT;

-- Fix round 1, 2026-09-04. The IN-list above missed -1111, -995 and -9, which
-- also showed up in production (pm25/o3/pm10 min -1111, no2/no min -995, so2
-- min -9). A concentration cannot be negative at all, so this closes the gap
-- as a domain constraint instead of adding a fourth/fifth sentinel to chase.
-- Covers all fourteen pollutant columns the ingest now runs through
-- _concentration_or_none (temperature and humidity are excluded on purpose —
-- a negative temperature is a real reading).
-- ⛔ Take a pg_dump of air_quality_stations before running this.
BEGIN;
UPDATE air_quality_stations SET pm25 = NULL WHERE pm25 < 0;
UPDATE air_quality_stations SET so2  = NULL WHERE so2  < 0;
UPDATE air_quality_stations SET no2  = NULL WHERE no2  < 0;
UPDATE air_quality_stations SET o3   = NULL WHERE o3   < 0;
UPDATE air_quality_stations SET co   = NULL WHERE co   < 0;
UPDATE air_quality_stations SET pm10 = NULL WHERE pm10 < 0;
UPDATE air_quality_stations SET bc   = NULL WHERE bc   < 0;
UPDATE air_quality_stations SET no   = NULL WHERE no   < 0;
UPDATE air_quality_stations SET nox  = NULL WHERE nox  < 0;
UPDATE air_quality_stations SET co2  = NULL WHERE co2  < 0;
UPDATE air_quality_stations SET pm1  = NULL WHERE pm1  < 0;
UPDATE air_quality_stations SET pm4  = NULL WHERE pm4  < 0;
UPDATE air_quality_stations SET ch4  = NULL WHERE ch4  < 0;
UPDATE air_quality_stations SET ufp  = NULL WHERE ufp  < 0;
COMMIT;
