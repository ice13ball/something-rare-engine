# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Hazard land layers: active fires (NASA FIRMS), air quality (OpenAQ),
landslides (NASA COOLR), and water risk (WRI Aqueduct 4.0). Split out of
land_layers.py.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from ingestion.cadence import should_sync

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import Response

import db
from auth import get_api_key
from domains.land.common import _log_land_sync, _pg_conn_string

log = logging.getLogger("land_layers")
OGR2OGR = shutil.which("ogr2ogr") or "/usr/bin/ogr2ogr"
router = APIRouter(tags=["land-layers"], dependencies=[Depends(get_api_key)])

# ── Module-level caches (cleared on sync) ──────────────────────────────────
_fires_cache: str | None = None
_air_quality_cache: str | None = None
_landslides_cache: str | None = None
_water_risk_cache: str | None = None


def clear_caches() -> None:
    """Reset this module's caches. Delegated into from land_layers.clear_caches()
    so the combined 13-cache sweep still clears everything from one call."""
    global _fires_cache, _air_quality_cache, _landslides_cache, _water_risk_cache
    _fires_cache = None
    _air_quality_cache = None
    _landslides_cache = None
    _water_risk_cache = None


# ── Active Fires (NASA FIRMS) ─────────────────────────────────────────────

FIRMS_MAP_KEY = os.environ.get("FIRMS_MAP_KEY", "")
OPENAQ_API_KEY = os.environ.get("OPENAQ_API_KEY", "")

_FIRMS_SENSORS = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"]
_FIRMS_CONFIDENCE = {"l": "Low", "n": "Nominal", "h": "High"}

async def _sync_active_fires() -> int:
    """
    Fetch active fires from NASA FIRMS API (last 24h, global VIIRS).
    Queries three VIIRS sensors for complete global coverage — a single
    sensor misses large regions depending on orbital pass timing.
    Fires are ephemeral — truncate and reload every 6 hours.
    """
    if not FIRMS_MAP_KEY:
        log.warning("active_fires: FIRMS_MAP_KEY not set, skipping")
        return 0

    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = 'active_fires'"
        )
        if last and (datetime.now(tz=timezone.utc) - last).total_seconds() < 3600 * 6:
            log.info("active_fires: synced %s, skipping (6h guard)", last)
            return 0

    async def _fetch_sensors(days: int) -> list[dict]:
        result: list[dict] = []
        async with httpx.AsyncClient(timeout=120) as client:
            for sensor in _FIRMS_SENSORS:
                try:
                    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{FIRMS_MAP_KEY}/{sensor}/world/{days}"
                    resp = await client.get(url)
                    resp.raise_for_status()
                    sensor_rows = list(csv.DictReader(io.StringIO(resp.text)))
                    for r in sensor_rows:
                        r["_sensor"] = sensor.replace("_NRT", "")
                    result.extend(sensor_rows)
                    log.info("active_fires: %s (day=%d) returned %d rows", sensor, days, len(sensor_rows))
                except Exception as e:
                    log.warning("active_fires: %s fetch failed: %s", sensor, e)
        return result

    # Fetch last 2 days — if today's FIRMS refresh isn't done yet, yesterday's data is always present.
    # Deduplication by (lat, lon, acq_date) handles any cross-day overlap.
    rows = await _fetch_sensors(days=2)

    if not rows:
        # Still empty after 2-day fetch — wait 30 min and retry once (FIRMS publication lag).
        log.warning("active_fires: no data from 2-day fetch, retrying in 30 min")
        await asyncio.sleep(1800)
        rows = await _fetch_sensors(days=2)

    if not rows:
        # FIRMS unavailable — update timestamp so stale warning doesn't fire; existing rows stay valid.
        log.warning("active_fires: no data after retry, FIRMS may be down")
        await _log_land_sync("active_fires", 0, 0)
        return 0

    # Deduplicate: same lat/lon/acq_date from multiple sensors → keep highest FRP
    seen: dict[tuple, dict] = {}
    for r in rows:
        key = (r.get("latitude"), r.get("longitude"), r.get("acq_date"))
        existing = seen.get(key)
        if not existing or float(r.get("frp", 0) or 0) > float(existing.get("frp", 0) or 0):
            seen[key] = r
    rows = list(seen.values())
    log.info("active_fires: %d unique fires after dedup", len(rows))

    async with db.pool.acquire() as conn:
        await conn.execute("TRUNCATE active_fires")
        inserted = 0
        for r in rows:
            try:
                lat = float(r.get("latitude", 0))
                lon = float(r.get("longitude", 0))
                acq_str = r.get("acq_date", "")
                acq_date = datetime.strptime(acq_str, "%Y-%m-%d").date() if acq_str else None
                await conn.execute("""
                    INSERT INTO active_fires
                        (latitude, longitude, brightness, confidence, frp, instrument, acq_date, geom)
                    VALUES ($1, $2, $3, $4, $5, $6, $7,
                            ST_SetSRID(ST_MakePoint($8, $9), 4326))
                """,
                    lat, lon,
                    float(r.get("bright_ti4", 0) or 0),
                    _FIRMS_CONFIDENCE.get(r.get("confidence", ""), r.get("confidence", "")),
                    float(r.get("frp", 0) or 0),
                    r.get("_sensor", "VIIRS"),
                    acq_date,
                    lon, lat,
                )
                inserted += 1
            except Exception as e:
                log.warning("active_fires: row failed: %s", e)
        total = await conn.fetchval("SELECT COUNT(*) FROM active_fires")

    global _fires_cache
    _fires_cache = None
    await _log_land_sync("active_fires", inserted, total)
    log.info("active_fires: %d inserted / %d total", inserted, total)
    return inserted


@router.get("/fires")
async def get_fires():
    global _fires_cache
    if _fires_cache:
        return Response(content=_fires_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        row = await conn.fetchval("""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(json_agg(
                    json_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(geom)::json,
                        'properties', json_build_object(
                            'id', id,
                            'brightness', brightness,
                            'confidence', confidence,
                            'frp', frp,
                            'instrument', instrument,
                            'acq_date', acq_date::text
                        )
                    )
                ), '[]'::json)
            )::text
            FROM active_fires
        """)
    _fires_cache = row
    return Response(content=row, media_type="application/json")


# ── Air Quality (OpenAQ) ──────────────────────────────────────────────────

def _parse_openaq_dt(obj: dict | None) -> "datetime | None":
    """Parse {'utc': '2024-01-01T00:00:00Z', ...} → datetime or None."""
    if not obj:
        return None
    utc = obj.get("utc") if isinstance(obj, dict) else None
    if not utc:
        return None
    try:
        return datetime.fromisoformat(utc.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


async def _sync_air_quality() -> int:
    """
    Fetch air quality station locations + latest readings from OpenAQ v3.
    Docs: https://docs.openaq.org/
    """
    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = 'air_quality'"
        )
        if last and (datetime.now(tz=timezone.utc) - last).total_seconds() < 3600 * 12:
            log.info("air_quality: synced %s, skipping (12h guard)", last)
            return 0

    if not OPENAQ_API_KEY:
        log.warning("air_quality: OPENAQ_API_KEY not set, skipping")
        return 0

    all_locations: list[dict] = []
    page = 1
    headers = {"X-API-Key": OPENAQ_API_KEY}
    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        while True:
            resp = await client.get(
                "https://api.openaq.org/v3/locations",
                params={"limit": 1000, "page": page, "order_by": "id"},
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break
            all_locations.extend(results)
            page += 1
            if page > 50:
                log.error(
                    "air_quality: hit the %d-page ceiling with %d locations fetched — "
                    "the station list may be truncated, raise the cap",
                    50, len(all_locations),
                )
                break
            await asyncio.sleep(0.5)

    if not all_locations:
        log.warning("air_quality: no locations returned")
        return 0

    inserted = 0
    async with db.pool.acquire() as conn:
        for loc in all_locations:
            try:
                coords = loc.get("coordinates", {})
                lat = coords.get("latitude")
                lon = coords.get("longitude")
                if lat is None or lon is None:
                    continue

                # NOTE (2026-09-09): /v3/locations also returns a
                # `parameters[]` array (per-parameter lastValue at this
                # location). It is intentionally NOT extracted here — this
                # sync only stores station identity/geometry; per-parameter
                # readings are the job of _sync_air_quality_readings() below,
                # which reads the richer per-SENSOR /v3/locations/{id}/sensors
                # endpoint instead (sensor id, full summary, coverage). Two
                # readings of the same field would drift; keeping one source
                # of truth for values.

                # Extract location-level metadata
                locality   = loc.get("locality") or ""
                tz         = loc.get("timezone") or ""
                is_mobile  = bool(loc.get("isMobile", False))
                is_monitor = bool(loc.get("isMonitor", False))
                provider   = (loc.get("provider") or {}).get("name") or ""
                owner      = (loc.get("owner") or {}).get("name") or ""
                dt_first   = _parse_openaq_dt(loc.get("datetimeFirst"))
                dt_last    = _parse_openaq_dt(loc.get("datetimeLast"))

                await conn.execute("""
                    INSERT INTO air_quality_stations
                        (location_id, name, city, country,
                         last_updated, geom,
                         locality, timezone, is_mobile, is_monitor,
                         provider, owner, datetime_first, datetime_last)
                    VALUES ($1, $2, $3, $4,
                            $5, ST_SetSRID(ST_MakePoint($6, $7), 4326),
                            $8, $9, $10, $11,
                            $12, $13, $14, $15)
                    ON CONFLICT (location_id) DO UPDATE SET
                        name = EXCLUDED.name, city = EXCLUDED.city,
                        country = EXCLUDED.country, geom = EXCLUDED.geom,
                        locality = EXCLUDED.locality, timezone = EXCLUDED.timezone,
                        is_mobile = EXCLUDED.is_mobile, is_monitor = EXCLUDED.is_monitor,
                        provider = EXCLUDED.provider, owner = EXCLUDED.owner,
                        datetime_first = EXCLUDED.datetime_first,
                        datetime_last = EXCLUDED.datetime_last
                """,
                    loc.get("id"),
                    loc.get("name", ""),
                    loc.get("city", ""),
                    loc.get("country", {}).get("name", "") if isinstance(loc.get("country"), dict) else str(loc.get("country", "")),
                    datetime.now(tz=timezone.utc),
                    lon, lat,
                    locality, tz, is_mobile, is_monitor,
                    provider, owner, dt_first, dt_last,
                )
                inserted += 1
            except Exception as e:
                log.warning("air_quality: location %s failed: %s", loc.get("id"), e)

        total = await conn.fetchval("SELECT COUNT(*) FROM air_quality_stations")

    global _air_quality_cache
    _air_quality_cache = None
    await _log_land_sync("air_quality", inserted, total)
    log.info("air_quality: %d upserted / %d total", inserted, total)
    return inserted



# Wall-clock budget for one _sync_air_quality_readings() run. The sweep is
# incremental and resumable (stations already covered drop out of the
# candidate query below), so a run does not need to finish the whole
# 25,814-station backlog — it only needs to make forward progress and stop
# before it starves the event loop or a cron overlap. 8 minutes keeps this
# comfortably inside a 15-minute cron cadence with room for the next run's
# station-list sync.
_READINGS_MAX_RUNTIME_S = 8 * 60
# A hard request ceiling as a second, independent guard — if the API ever
# started answering instantly (no throttling), the time budget alone could
# still allow an unbounded number of requests.
_READINGS_MAX_REQUESTS = 2000
_MAX_BACKOFF_S = 120


async def _sync_air_quality_readings() -> int:
    """
    Fetch latest readings for air quality stations missing measurement data.
    Uses /v3/locations/{id}/sensors sequentially, resuming oldest-station-first
    across runs. Rate limiting is handled by respecting Retry-After / backing
    off, never by abandoning the sweep — a throttled run simply covers fewer
    stations and the next run picks up where this one left off.
    """
    if not OPENAQ_API_KEY:
        log.warning("air_quality_readings: OPENAQ_API_KEY not set, skipping")
        await _log_land_sync("air_quality_readings", 0, 0)
        return 0

    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            # ⛔ Ordered by LAST ATTEMPT, not by "has no readings yet".
            # Verified against the live API 2026-09-09: ~4% of OpenAQ locations
            # answer /v3/locations/{id}/sensors with HTTP 500 — their fault, not
            # ours, and they never produce a params row. Under the previous
            # `NOT EXISTS (... params ...) ORDER BY location_id` they therefore
            # stayed candidates FOREVER and sat at the head of every future run,
            # so the sweep would grind on the same ~1,000 broken stations and
            # never reach the rest. Recording the attempt is what lets a station
            # rotate out of the queue whatever the outcome.
            "SELECT s.location_id FROM air_quality_stations s "
            "ORDER BY s.readings_attempted_at ASC NULLS FIRST, s.location_id "
            "LIMIT 500"
        )
        total_remaining_before = await conn.fetchval(
            "SELECT COUNT(*) FROM air_quality_stations s "
            "WHERE s.readings_attempted_at IS NULL"
        )

    if not rows:
        log.info("air_quality_readings: all stations have readings, skipping")
        await _log_land_sync("air_quality_readings", 0, 0)
        return 0

    location_ids = [r["location_id"] for r in rows]
    log.info("air_quality_readings: fetching latest for %d stations (%d total still uncovered)",
              len(location_ids), total_remaining_before)

    headers = {"X-API-Key": OPENAQ_API_KEY}
    updated = 0
    skipped = 0
    rate_limited_events = 0
    requests_made = 0
    started = asyncio.get_event_loop().time()
    stopped_early_reason: str | None = None
    # location_id -> HTTP status or exception name. Kept apart from `skipped`
    # so an upstream outage is never recorded as an absence of measurements.
    upstream_errors: dict[int, object] = {}
    attempted: list[int] = []

    async def _stamp(lid: int) -> None:
        # ⛔ Stamp per station, inside the loop, NOT in one batch at the end.
        # readings_attempted_at is the queue order, and this backend restarts
        # on every dev push (git poll, 60 s). Observed 2026-09-09: two
        # consecutive 8-minute sweeps wrote readings for ~600 stations and
        # then died to a deploy restart before the end-of-run UPDATE, so the
        # queue never moved — left_before was identical (24,877) on both runs
        # and the next sweep re-fetched the same stations. One small UPDATE
        # per station is free next to the 1.2 s pacing sleep it sits beside.
        async with db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE air_quality_stations "
                "SET readings_attempted_at = NOW(), readings_error = $2 "
                "WHERE location_id = $1",
                lid,
                str(upstream_errors[lid]) if lid in upstream_errors else None,
            )

    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        idx = 0
        for idx, loc_id in enumerate(location_ids):
            elapsed = asyncio.get_event_loop().time() - started
            if elapsed >= _READINGS_MAX_RUNTIME_S:
                stopped_early_reason = f"wall-clock budget ({_READINGS_MAX_RUNTIME_S}s) reached"
                break
            if requests_made >= _READINGS_MAX_REQUESTS:
                stopped_early_reason = f"request budget ({_READINGS_MAX_REQUESTS}) reached"
                break
            # ⛔ AFTER the budget check, never before. `attempted` is what
            # stamps readings_attempted_at, and a stamp says "we asked OpenAQ
            # about this station". Appending first meant the one station the
            # budget stops on was stamped as attempted with readings_error
            # NULL — indistinguishable from "asked, station reports nothing" —
            # while no request was ever sent. It then rotated to the BACK of
            # the queue, so a station skipped this way would not be retried
            # until the whole 25,824-station sweep came round again.
            attempted.append(loc_id)

            backoff = 2.0
            attempt = 0
            data: dict | None = None
            while True:
                attempt += 1
                requests_made += 1
                try:
                    resp = await client.get(f"https://api.openaq.org/v3/locations/{loc_id}/sensors")
                except Exception as exc:
                    upstream_errors[loc_id] = type(exc).__name__
                    skipped += 1
                    break

                if resp.status_code == 429:
                    rate_limited_events += 1
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after is not None:
                        try:
                            wait_s = float(retry_after)
                        except ValueError:
                            wait_s = backoff
                    else:
                        wait_s = backoff
                    wait_s = min(wait_s, _MAX_BACKOFF_S)
                    if attempt >= 6:
                        # Give up on THIS station only — never on the sweep.
                        skipped += 1
                        break
                    log.info("air_quality_readings: 429 for station %s, waiting %.0fs (attempt %d)",
                              loc_id, wait_s, attempt)
                    await asyncio.sleep(wait_s)
                    backoff = min(backoff * 2, _MAX_BACKOFF_S)
                    continue

                if resp.status_code != 200:
                    # ⛔ missing and broken must not share a code path. A 500 is
                    # OpenAQ failing, NOT a station without measurements; storing
                    # it as "no data" would quietly turn their outage into our
                    # fact. Record the reason so the two stay distinguishable.
                    upstream_errors[loc_id] = resp.status_code
                    skipped += 1
                    break

                data = resp.json()
                break

            if data is None:
                await _stamp(loc_id)
                if requests_made >= _READINGS_MAX_REQUESTS:
                    stopped_early_reason = f"request budget ({_READINGS_MAX_REQUESTS}) reached"
                    break
                await asyncio.sleep(1.0)
                continue

            # Station-level aggregate (16 named columns on air_quality_stations,
            # unchanged behaviour): last sensor reporting a parameter wins when
            # several sensors share it. `sensor_rows` below is the honest,
            # per-sensor record — nothing is collapsed there.
            values: dict[str, float | None] = {}
            units: dict[str, str | None] = {}
            sensor_rows: list[dict] = []
            for sensor in data.get("results", []):
                param = sensor.get("parameter") or {}
                param_name = param.get("name", "")
                if not param_name:
                    continue
                sensor_id = sensor.get("id")
                unit = param.get("units")
                units[param_name] = unit
                latest = sensor.get("latest")
                summary = sensor.get("summary") or {}
                coverage = sensor.get("coverage") or {}

                value: float | None = None
                if latest and latest.get("value") is not None:
                    value = latest["value"]
                elif summary.get("avg") is not None:
                    value = round(summary["avg"], 2)
                if value is not None:
                    values[param_name] = value

                sensor_rows.append({
                    # 0 is the same "unknown/unattributed sensor" sentinel the
                    # schema migration backfills for pre-fix rows — OpenAQ
                    # always sends an id in practice, but a response that
                    # somehow omits it still lands (own row per parameter,
                    # not silently dropped) rather than being skipped.
                    "sensor_id": sensor_id if sensor_id is not None else 0,
                    "parameter": param_name,
                    "unit": unit,
                    "value": value,
                    "datetime_first": _parse_openaq_dt(sensor.get("datetimeFirst")),
                    "datetime_last": _parse_openaq_dt(sensor.get("datetimeLast")),
                    "value_min": summary.get("min"),
                    "value_max": summary.get("max"),
                    "value_sd": summary.get("sd"),
                    "expected_count": summary.get("expectedCount"),
                    "observed_count": summary.get("observedCount"),
                    "coverage_pct": coverage.get("percentComplete"),
                })

            # Station-level coverage_pct: prefer PM2.5 sensor, else first available
            coverage_pct: float | None = None
            for sensor in data.get("results", []):
                cov = sensor.get("coverage")
                if cov and cov.get("percentComplete") is not None:
                    pname = (sensor.get("parameter") or {}).get("name", "")
                    if coverage_pct is None or pname == "pm25":
                        coverage_pct = cov["percentComplete"]
                        if pname == "pm25":
                            break

            if values:
                async with db.pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE air_quality_stations
                        SET pm25 = $2,  so2 = $3,  no2 = $4,  o3 = $5,  co = $6,
                            pm10 = $7,  bc = $8,   no = $9,   nox = $10,
                            humidity = $11, temperature = $12, co2 = $13,
                            pm1 = $14,  pm4 = $15, ch4 = $16, ufp = $17,
                            coverage_pct = $18,
                            last_updated = NOW()
                        WHERE location_id = $1
                    """,
                        loc_id,
                        _concentration_or_none(values.get("pm25")),   _concentration_or_none(values.get("so2")),
                        _concentration_or_none(values.get("no2")),    _concentration_or_none(values.get("o3")),
                        _concentration_or_none(values.get("co")),
                        _concentration_or_none(values.get("pm10")),   _concentration_or_none(values.get("bc")),
                        _concentration_or_none(values.get("no")),     _concentration_or_none(values.get("nox")),
                        _score_or_none(values.get("relativehumidity")),
                        _score_or_none(values.get("temperature")),
                        _concentration_or_none(values.get("co2")),
                        _concentration_or_none(values.get("pm1")),    _concentration_or_none(values.get("pm4")),
                        _concentration_or_none(values.get("ch4")),    _concentration_or_none(values.get("ufp")),
                        coverage_pct,
                    )
                    # Store every SENSOR the location reported (44 possible
                    # parameters, and several sensors can share one parameter
                    # — reference-grade + low-cost monitoring the same thing
                    # is the ordinary case, so sensor_id is part of the key,
                    # not just parameter). Verbatim unit, no conversion, no
                    # unit ever assumed; a missing unit stores NULL.
                    for row in sensor_rows:
                        await conn.execute("""
                            INSERT INTO air_quality_params
                                (location_id, sensor_id, parameter, value, unit, last_updated,
                                 datetime_first, datetime_last, value_min, value_max, value_sd,
                                 expected_count, observed_count, coverage_pct)
                            VALUES ($1, $2, $3, $4, $5, NOW(), $6, $7, $8, $9, $10, $11, $12, $13)
                            ON CONFLICT (location_id, sensor_id, parameter) DO UPDATE
                            SET value = EXCLUDED.value, unit = EXCLUDED.unit, last_updated = NOW(),
                                datetime_first = EXCLUDED.datetime_first,
                                datetime_last = EXCLUDED.datetime_last,
                                value_min = EXCLUDED.value_min, value_max = EXCLUDED.value_max,
                                value_sd = EXCLUDED.value_sd,
                                expected_count = EXCLUDED.expected_count,
                                observed_count = EXCLUDED.observed_count,
                                coverage_pct = EXCLUDED.coverage_pct
                        """,
                            loc_id, row["sensor_id"], row["parameter"],
                            _score_or_none(row["value"]), row["unit"],
                            row["datetime_first"], row["datetime_last"],
                            row["value_min"], row["value_max"], row["value_sd"],
                            row["expected_count"], row["observed_count"], row["coverage_pct"],
                        )
                    updated += 1
            else:
                skipped += 1

            await _stamp(loc_id)

            # Log progress every 50 stations
            if (idx + 1) % 50 == 0:
                log.info("air_quality_readings: %d/%d processed, %d updated, %d skipped, %d rate-limit events",
                         idx + 1, len(location_ids), updated, skipped, rate_limited_events)

            await asyncio.sleep(1.2)  # ~50 req/min baseline pace between stations

    async with db.pool.acquire() as conn:
        total_remaining_after = await conn.fetchval(
            "SELECT COUNT(*) FROM air_quality_stations s "
            "WHERE s.pm25 IS NULL AND s.no2 IS NULL AND s.o3 IS NULL "
            "  AND NOT EXISTS (SELECT 1 FROM air_quality_params p WHERE p.location_id = s.location_id)"
        )

    global _air_quality_cache
    _air_quality_cache = None
    # total_records = stations still uncovered after this run. 0 means this
    # run finished the whole backlog (a complete sweep); >0 means it stopped
    # early (throttled or budget-bound) and the next run must resume — the
    # sync log itself carries that distinction, no separate status column.
    # Every station this run touched was already stamped by _stamp() as its
    # outcome became known, so a restart mid-sweep keeps the progress made so
    # far instead of discarding the whole run's queue movement.
    if upstream_errors:
        log.warning(
            "air_quality_readings: %d stations failed UPSTREAM (not empty) — sample: %s",
            len(upstream_errors),
            ", ".join(f"{k}:{v}" for k, v in list(upstream_errors.items())[:5]),
        )

    await _log_land_sync("air_quality_readings", updated, total_remaining_after)
    if stopped_early_reason:
        log.warning(
            "air_quality_readings: INCOMPLETE run — stopped early (%s) after %d/%d stations, "
            "%d updated, %d skipped, %d rate-limit events, %d requests; %d stations still uncovered",
            stopped_early_reason, idx + 1, len(location_ids), updated, skipped,
            rate_limited_events, requests_made, total_remaining_after,
        )
    else:
        log.info("air_quality_readings: done — %d updated, %d skipped, %d rate-limit events out of %d; "
                  "%d stations still uncovered",
                  updated, skipped, rate_limited_events, len(location_ids), total_remaining_after)
    return updated


@router.get("/air-quality")
async def get_air_quality():
    global _air_quality_cache
    if _air_quality_cache:
        return Response(content=_air_quality_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        row = await conn.fetchval("""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(json_agg(
                    json_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(geom)::json,
                        'properties', json_build_object(
                            'id', id,
                            'location_id', location_id,
                            'name', name,
                            'city', city,
                            'country', country,
                            'pm25', pm25,
                            'so2', so2,
                            'no2', no2,
                            'o3', o3,
                            'co', co,
                            'last_updated', last_updated::text,
                            'locality', locality,
                            'timezone', timezone,
                            'is_mobile', is_mobile,
                            'is_monitor', is_monitor,
                            'provider', provider,
                            'owner', owner,
                            'datetime_first', datetime_first::text,
                            'datetime_last', datetime_last::text,
                            'pm10', pm10,
                            'bc', bc,
                            'no', no,
                            'nox', nox,
                            'humidity', humidity,
                            'temperature', temperature,
                            'co2', co2,
                            'pm1', pm1,
                            'pm4', pm4,
                            'ch4', ch4,
                            'ufp', ufp,
                            'coverage_pct', coverage_pct
                        )
                    )
                ), '[]'::json)
            )::text
            FROM air_quality_stations
        """)
    _air_quality_cache = row
    return Response(content=row, media_type="application/json")


# ── Landslides (NASA COOLR) ───────────────────────────────────────────────

async def _sync_landslides(force: bool = False) -> int:
    """
    Import NASA COOLR Global Landslide Catalog.
    Source: https://gpm.nasa.gov/landslides/data.html
    Place downloaded file in /opt/abyssal-data/landslides/ on VPS.
    """
    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = $1", "landslides")
        run, why = should_sync("landslides", last, datetime.now(timezone.utc), force=force)
        log.info("%s", why)
        if not run:
            return 0
        count = await conn.fetchval("SELECT COUNT(*) FROM landslides")
        if count > 0:
            log.info("landslides: already have %d records, skipping", count)
            # ⛔ The row-count guard stays even under force. These loads use
            # `ogr2ogr -append`, so re-running against a populated table
            # DOUBLES it — force skips the cadence window, never the duplicate
            # barrier. Logged at WARNING so a forced run that does nothing is
            # visible rather than being reported as a success.
            if force:
                log.warning(
                    "landslides: force requested but the table already holds %d rows; "
                    "this load is append-only and cannot be safely re-run. "
                    "TRUNCATE deliberately first if a reload is really wanted.",
                    count)
            return 0

    ls_path = "/opt/abyssal-data/landslides"
    src_file = None
    if os.path.isdir(ls_path):
        for fn in os.listdir(ls_path):
            if fn.endswith((".csv", ".geojson", ".gpkg", ".shp")):
                src_file = os.path.join(ls_path, fn)
                break

    if not src_file:
        log.warning("landslides: no data file in %s — download from gpm.nasa.gov", ls_path)
        return 0

    if src_file.endswith(".csv"):
        with open(src_file) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        inserted = 0
        async with db.pool.acquire() as conn:
            for r in rows:
                try:
                    lat = float(r.get("latitude") or r.get("lat") or 0)
                    lon = float(r.get("longitude") or r.get("lon") or 0)
                    if lat == 0 and lon == 0:
                        continue
                    evt_str = r.get("event_date", "") or ""
                    evt_date = None
                    if evt_str:
                        try:
                            evt_date = datetime.strptime(evt_str.split(" ")[0], "%m/%d/%Y").date()
                        except ValueError:
                            try:
                                evt_date = datetime.strptime(evt_str.split(" ")[0], "%Y-%m-%d").date()
                            except ValueError:
                                pass
                    await conn.execute("""
                        INSERT INTO landslides
                            (event_date, event_type, country, location, fatalities, trigger, source, geom)
                        VALUES ($1, $2, $3, $4, $5, $6, $7,
                                ST_SetSRID(ST_MakePoint($8, $9), 4326))
                    """,
                        evt_date,
                        r.get("landslide_category", r.get("event_type", "")),
                        r.get("country_name", r.get("country", "")),
                        r.get("location_description", r.get("location", "")),
                        int(r.get("fatality_count", 0) or 0),
                        r.get("landslide_trigger", r.get("trigger", "")),
                        r.get("source_name", r.get("source", "")),
                        lon, lat,
                    )
                    inserted += 1
                except Exception as e:
                    log.warning("landslides: row failed: %s", e)
            total = await conn.fetchval("SELECT COUNT(*) FROM landslides")
    else:
        cmd = [
            OGR2OGR, "-f", "PostgreSQL", _pg_conn_string(), src_file,
            "-nln", "landslides", "-append",
            "-nlt", "POINT", "-lco", "GEOMETRY_NAME=geom",
            "-t_srs", "EPSG:4326", "--config", "PG_USE_COPY", "YES",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            log.error("landslides ogr2ogr failed: %s", result.stderr)
            return 0
        async with db.pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM landslides")
        inserted = total

    global _landslides_cache
    _landslides_cache = None
    await _log_land_sync("landslides", inserted, total)
    log.info("landslides: %d new / %d total", inserted, total)
    return inserted


@router.get("/landslides")
async def get_landslides():
    global _landslides_cache
    if _landslides_cache:
        return Response(content=_landslides_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        row = await conn.fetchval("""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(json_agg(
                    json_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(geom)::json,
                        'properties', json_build_object(
                            'id', id,
                            'event_date', event_date::text,
                            'event_type', event_type,
                            'country', country,
                            'location', location,
                            'fatalities', fatalities,
                            'trigger', trigger,
                            'source', source
                        )
                    )
                ), '[]'::json)
            )::text
            FROM landslides
        """)
    _landslides_cache = row
    return Response(content=row, media_type="application/json")


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 3 — Deeper Environmental Context
# ═══════════════════════════════════════════════════════════════════════════

# ── Water Risk (WRI Aqueduct 4.0) ──────────────────────────────────────────

_AQUEDUCT_BASE = (
    "https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services"
    "/aqueduct_water_risk/FeatureServer/1/query"
)

# WRI Aqueduct and OpenAQ both write a documented no-data code into numeric
# fields rather than leaving them empty. Storing that code as a measurement is
# the defect the units audit found: -9999 in a 0-5 score column reads as "very
# low risk" to every mean, ordering and colour ramp downstream.
#
# NULL is that code's faithful rendering in a database that can say "no value".
# See docs/methods/data-passthrough.md.
_NO_DATA_CODES = frozenset({-9999.0, -999.0})


def _score_or_none(value) -> float | None:
    """Coerce an upstream numeric to float, mapping documented fill values to None."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f in _NO_DATA_CODES else f


# A concentration cannot be negative. OpenAQ's feed carries at least -9999, -999,
# -1111, -995 and -9 as fill values, which is why this is a domain constraint
# rather than a list of codes to block: the next sensor will invent a fifth.
def _concentration_or_none(value) -> float | None:
    """Coerce an upstream concentration to float; reject fill values and negatives."""
    f = _score_or_none(value)
    return None if f is not None and f < 0 else f


async def _sync_water_risk(force: bool = False) -> int:
    """
    Import WRI Aqueduct 4.0 Baseline Annual water risk polygons from ArcGIS.
    ~68,506 polygons. Static dataset — downloads once, skips if populated.
    """
    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = $1", "water_risk")
        run, why = should_sync("water_risk", last, datetime.now(timezone.utc), force=force)
        log.info("%s", why)
        if not run:
            return 0
        count = await conn.fetchval("SELECT COUNT(*) FROM water_risk")
        if count > 0:
            log.info("water_risk: already have %d records, skipping", count)
            # ⛔ The row-count guard stays even under force. These loads use
            # `ogr2ogr -append`, so re-running against a populated table
            # DOUBLES it — force skips the cadence window, never the duplicate
            # barrier. Logged at WARNING so a forced run that does nothing is
            # visible rather than being reported as a success.
            if force:
                log.warning(
                    "water_risk: force requested but the table already holds %d rows; "
                    "this load is append-only and cannot be safely re-run. "
                    "TRUNCATE deliberately first if a reload is really wanted.",
                    count)
            return 0

    log.info("water_risk: fetching from WRI Aqueduct ArcGIS FeatureServer...")
    out_fields = (
        "string_id,pfaf_id,gid_0,name_0,name_1,area_km2,"
        "bws_score,bws_label,bwd_score,drr_score,rfr_score,"
        "w_awr_min_tot_score,w_awr_min_tot_cat,w_awr_min_tot_label"
    )
    all_features: list[dict] = []
    offset = 0
    async with httpx.AsyncClient(timeout=120) as client:
        while True:
            params = {
                "where": "1=1",
                "outFields": out_fields,
                "f": "geojson",
                "resultRecordCount": 750,
                "resultOffset": offset,
            }
            resp = await client.get(_AQUEDUCT_BASE, params=params)
            resp.raise_for_status()
            features = resp.json().get("features", [])
            all_features.extend(features)
            log.info("water_risk: fetched %d features (offset %d)", len(features), offset)
            if len(features) < 750:
                break
            offset += 750

    if not all_features:
        log.warning("water_risk: no features returned")
        return 0

    log.info("water_risk: inserting %d polygons...", len(all_features))
    inserted = 0
    async with db.pool.acquire() as conn:
        for f in all_features:
            p = f.get("properties") or {}
            geom = f.get("geometry")
            if not geom or not p.get("string_id"):
                continue
            try:
                geojson_str = json.dumps(geom)
                await conn.execute("""
                    INSERT INTO water_risk
                        (string_id, pfaf_id, gid_0, name_0, name_1, area_km2,
                         bws_score, bws_label, bwd_score, drr_score, rfr_score,
                         w_awr_min_tot_score, w_awr_min_tot_cat, w_awr_min_tot_label, geom)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,
                            ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON($15), 4326)))
                    ON CONFLICT (string_id) DO NOTHING
                """,
                    p.get("string_id"),
                    int(p["pfaf_id"]) if p.get("pfaf_id") is not None else None,
                    p.get("gid_0"),
                    p.get("name_0"),
                    p.get("name_1"),
                    float(p["area_km2"]) if p.get("area_km2") is not None else None,
                    _score_or_none(p.get("bws_score")),
                    p.get("bws_label"),
                    _score_or_none(p.get("bwd_score")),
                    _score_or_none(p.get("drr_score")),
                    _score_or_none(p.get("rfr_score")),
                    _score_or_none(p.get("w_awr_min_tot_score")),
                    int(p["w_awr_min_tot_cat"]) if p.get("w_awr_min_tot_cat") is not None else None,
                    p.get("w_awr_min_tot_label"),
                    geojson_str,
                )
                inserted += 1
            except Exception as e:
                log.warning("water_risk: row %s failed: %s", p.get("string_id"), e)

    global _water_risk_cache
    _water_risk_cache = None
    await _log_land_sync("water_risk", inserted, inserted)
    log.info("water_risk: %d inserted", inserted)
    return inserted


@router.get("/water-risk")
async def get_water_risk():
    global _water_risk_cache
    if _water_risk_cache:
        return Response(content=_water_risk_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        row = await conn.fetchval("""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(json_agg(
                    json_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(geom)::json,
                        'properties', json_build_object(
                            'string_id', string_id,
                            'name_0', name_0,
                            'name_1', name_1,
                            'area_km2', area_km2,
                            'bws_score', bws_score,
                            'bws_label', bws_label,
                            'bwd_score', bwd_score,
                            'drr_score', drr_score,
                            'rfr_score', rfr_score,
                            'w_awr_min_tot_score', w_awr_min_tot_score,
                            'w_awr_min_tot_cat', w_awr_min_tot_cat,
                            'w_awr_min_tot_label', w_awr_min_tot_label
                        )
                    )
                ), '[]'::json)
            )::text
            FROM water_risk
        """)
    _water_risk_cache = row
    return Response(content=row, media_type="application/json")
