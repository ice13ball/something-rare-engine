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
import openaq_guard
from parse_util import arcgis_features
import sync_log
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


def _firms_instant(acq_date, acq_time: "str | None"):
    """Combine FIRMS's acq_date + acq_time (HHMM, UTC) into one instant.

    ⛔ FIRMS drops the leading zero: 09:30 arrives as "930", not "0930", and
    00:05 arrives as "5". zfill(4) is what makes both parse. A naive slice of
    "930" reads hour 93.

    Returns None when either half is missing or the time is not four digits of
    a real clock — an unparseable stamp must read as "no time", never as
    midnight, which would invent an observation NASA never made.
    """
    if acq_date is None or not acq_time:
        return None
    digits = acq_time.strip().zfill(4)
    if not digits.isdigit() or len(digits) != 4:
        return None
    hh, mm = int(digits[:2]), int(digits[2:])
    if hh > 23 or mm > 59:
        return None
    return datetime(acq_date.year, acq_date.month, acq_date.day, hh, mm,
                    tzinfo=timezone.utc)
_FIRMS_CONFIDENCE = {"l": "Low", "n": "Nominal", "h": "High"}


def _firms_row_to_fields(r: dict) -> dict:
    """Pure per-row mapping from one FIRMS CSV dict to the columns we store.

    Values are stored exactly as NASA publishes them: no rounding, empty
    string -> None (NULL), daynight and version kept as raw text. Split out
    of the sync loop so it can be unit-tested without a DB or network call.
    """
    lat = float(r.get("latitude", 0))
    lon = float(r.get("longitude", 0))
    acq_str = r.get("acq_date", "")
    acq_date = datetime.strptime(acq_str, "%Y-%m-%d").date() if acq_str else None
    acq_time = (r.get("acq_time") or "").strip() or None
    observed_at = _firms_instant(acq_date, acq_time)

    def _num(key: str) -> "float | None":
        raw = (r.get(key) or "").strip() if isinstance(r.get(key), str) else r.get(key)
        if raw is None or raw == "":
            return None
        return float(raw)

    def _txt(key: str) -> "str | None":
        raw = r.get(key)
        if raw is None:
            return None
        raw = raw.strip() if isinstance(raw, str) else raw
        return raw or None

    return {
        "lat": lat,
        "lon": lon,
        "brightness": float(r.get("bright_ti4", 0) or 0),
        "confidence": _FIRMS_CONFIDENCE.get(r.get("confidence", ""), r.get("confidence", "")),
        "frp": float(r.get("frp", 0) or 0),
        "instrument": _txt("instrument"),
        "satellite": _txt("satellite"),
        "acq_date": acq_date,
        "acq_time": acq_time,
        "observed_at": observed_at,
        "scan": _num("scan"),
        "track": _num("track"),
        "version": _txt("version"),
        "bright_ti5": _num("bright_ti5"),
        "daynight": _txt("daynight"),
    }


async def _sync_active_fires(force: bool = False) -> int:
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
        # `force` comes from the admin Force Sync button. Without it the button
        # hit this same 6h guard as the scheduler, returned 0, and reported
        # success — the exact silent no-op documented for the other land
        # entries in sync_sources.py. Found 2026-09-18 by repointing
        # test_cadence.test_the_admin_force_sync_map_actually_forces_the_land_syncs
        # at the file that now holds the dict; it had been slicing the wrong
        # dict out of main.py and passing without checking anything.
        if not force and last and (datetime.now(tz=timezone.utc) - last).total_seconds() < 3600 * 6:
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

    # Deduplicate: the same pixel seen by more than one satellite → keep highest FRP.
    # ⛔ acq_time belongs in the key. Without it, two genuine detections of the
    # same pixel at different hours collapsed into one. Measured against the live
    # FIRMS CSV 2026-09-10: 294,496 rows, the old key dropped 20 of them and only
    # 2 were genuinely different times — small, but they were NASA's records and
    # this portal mirrors its sources 1:1.
    seen: dict[tuple, dict] = {}
    for r in rows:
        key = (r.get("latitude"), r.get("longitude"),
               r.get("acq_date"), r.get("acq_time"))
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
                f = _firms_row_to_fields(r)
                await conn.execute("""
                    INSERT INTO active_fires
                        (latitude, longitude, brightness, confidence, frp,
                         instrument, satellite, acq_date, acq_time, observed_at,
                         scan, track, version, bright_ti5, daynight, geom)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                            $11, $12, $13, $14, $15,
                            ST_SetSRID(ST_MakePoint($16, $17), 4326))
                """,
                    f["lat"], f["lon"], f["brightness"], f["confidence"], f["frp"],
                    # ⛔ NASA's own two fields, not our fused "VIIRS_SNPP" label.
                    # `_sensor` is the request we made; instrument and satellite
                    # are what FIRMS answered with.
                    f["instrument"], f["satellite"],
                    f["acq_date"], f["acq_time"], f["observed_at"],
                    f["scan"], f["track"], f["version"], f["bright_ti5"], f["daynight"],
                    f["lon"], f["lat"],
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
                            'satellite', satellite,
                            'acq_date', acq_date::text,
                            'acq_time', acq_time,
                            'observed_at', observed_at,
                            'daynight', daynight,
                            'version', version,
                            'scan', scan,
                            'track', track,
                            'bright_ti5', bright_ti5
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


async def _sync_air_quality(force: bool = False) -> int:
    """
    Fetch air quality station locations + latest readings from OpenAQ v3.
    Docs: https://docs.openaq.org/
    """
    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = 'air_quality'"
        )
        # See _sync_active_fires above — same silently-ignored Force Sync.
        if not force and last and (datetime.now(tz=timezone.utc) - last).total_seconds() < 3600 * 12:
            log.info("air_quality: synced %s, skipping (12h guard)", last)
            return 0

    if not OPENAQ_API_KEY:
        log.warning("air_quality: OPENAQ_API_KEY not set, skipping")
        return 0

    all_locations: list[dict] = []
    page = 1
    headers = {"X-API-Key": OPENAQ_API_KEY}
    pacer = openaq_guard.process_pacer()  # shared with the readings drip
    budget = openaq_guard.DailyBudget()
    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        while True:
            try:
                resp = await openaq_guard.guarded_get(
                    client, "https://api.openaq.org/v3/locations",
                    pacer=pacer, budget=budget,
                    params={"limit": 1000, "page": page, "order_by": "id"},
                )
            except openaq_guard.OpenAQStop as stop:
                # A truncated station list is not a sync: write nothing, and say
                # why (log_sync_skipped keeps last_synced_at ageing on purpose).
                log.warning("air_quality: stopped on page %d: %s", page, stop.reason)
                await sync_log.log_sync_skipped("air_quality", stop.reason)
                return 0
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



# ── Air-quality readings: bulk /v3/parameters/{id}/latest ────────────────────
# One request returns the latest value of ONE parameter for up to 1,000 sensors,
# so a full refresh is ~one request per 1,000 sensors instead of one per
# station (26,078 stations at ~5 req/min was ~160 days). Approach ported from
# downWindGlobal's `_fetch_measurements` (agents/l6_openaq.py), with two
# deliberate differences:
#   * downwind hardcodes parameter ids AND the unit ("µg/m³") for them. We read
#     both from `GET /v3/parameters` once per run: a `/latest` row carries no
#     unit, so a guessed one would silently mislabel ppm/ppb readings (the
#     unit bug fixed 2026-09-10), and one parameter NAME has several ids (one per
#     unit) — every id of a name must be fetched or its stations are missed.
#   * the set is the 16 pollutants/meteo values this platform stores in named
#     columns (downwind: 6 EAQI ones only).
_READINGS_PAGE_LIMIT = 1000
_READINGS_MAX_PAGES_PER_PARAM = 200        # runaway-pagination guard
# Second, independent ceilings next to the pacer and the daily budget.
_READINGS_MAX_RUNTIME_S = 60 * 60
_READINGS_MAX_REQUESTS = 400
# Consecutive upstream failures (5xx / network) before the run gives up.
# Requests are ~12 s apart, so 3 is ~36 s of hammering a dead endpoint.
_CONSECUTIVE_5XX_ABORT = 3

# OpenAQ parameter name -> (air_quality_stations column, is_concentration).
# Concentrations go through _concentration_or_none (OpenAQ ships -9999, -999 ...
# as fill values); humidity/temperature through _score_or_none (a real -55 C).
_READINGS_COLUMNS: dict[str, tuple[str, bool]] = {
    "pm25": ("pm25", True), "so2": ("so2", True), "no2": ("no2", True),
    "o3": ("o3", True), "co": ("co", True), "pm10": ("pm10", True),
    "bc": ("bc", True), "no": ("no", True), "nox": ("nox", True),
    "relativehumidity": ("humidity", False), "temperature": ("temperature", False),
    "co2": ("co2", True), "pm1": ("pm1", True), "pm4": ("pm4", True),
    "ch4": ("ch4", True), "ufp": ("ufp", True),
}
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)

_READINGS_PARAM_UPSERT = """
    INSERT INTO air_quality_params
        (location_id, sensor_id, parameter, value, unit, last_updated, datetime_last)
    VALUES ($1, $2, $3, $4, $5, NOW(), $6)
    ON CONFLICT (location_id, sensor_id, parameter) DO UPDATE
    SET value = EXCLUDED.value, unit = EXCLUDED.unit, last_updated = NOW(),
        datetime_last = EXCLUDED.datetime_last
"""


async def _sync_air_quality_readings() -> int:
    """Refresh station readings from OpenAQ's bulk `/v3/parameters/{id}/latest`.

    Writes the SAME tables/columns the old per-station path wrote:
    `air_quality_params` (key location + sensor + parameter, OpenAQ's own unit,
    the reading's OWN datetime in `datetime_last`) and the 16 named columns on
    `air_quality_stations` (newest sensor wins when several report a name).
    The per-sensor aggregates a `/sensors` call provided (datetime_first,
    min/max/sd, counts, coverage) are not in `/latest`, so an upsert leaves
    them untouched — never overwritten with NULL.

    Match key: `locationsId` -> station, `sensorsId` -> sensor. A row for a
    location we do not hold is dropped. `readings_attempted_at` is stamped for
    every station that appeared in a result page (stamped page by page, so a
    stopped or killed run keeps its progress). There is no queue any more: a
    run starts from page 1, parameters ordered by least recently refreshed, so
    a run that stops early does not starve the same parameters every time.

    Every request goes through openaq_guard (pacer, daily budget, 401/403/429
    stop). Any stop or upstream failure goes to sync_log via log_sync_skipped,
    never as a completed sweep.
    """
    if not OPENAQ_API_KEY:
        log.warning("air_quality_readings: OPENAQ_API_KEY not set, skipping")
        await _log_land_sync("air_quality_readings", 0, 0)
        return 0

    async with db.pool.acquire() as conn:
        known = {r["location_id"] for r in await conn.fetch(
            "SELECT location_id FROM air_quality_stations")}
        last_by_name = {r["parameter"]: r["m"] for r in await conn.fetch(
            "SELECT parameter, MAX(last_updated) AS m FROM air_quality_params "
            "WHERE parameter = ANY($1::text[]) GROUP BY parameter",
            list(_READINGS_COLUMNS))}
    if not known:
        log.info("air_quality_readings: no stations, skipping")
        await _log_land_sync("air_quality_readings", 0, 0)
        return 0

    pacer = openaq_guard.process_pacer()  # shared with the station sync
    budget = openaq_guard.DailyBudget()
    headers = {"X-API-Key": OPENAQ_API_KEY}
    base = "https://api.openaq.org/v3"
    started = asyncio.get_event_loop().time()
    requests_made = 0
    guard_stop: str | None = None
    abort_reason: str | None = None
    failed: list[str] = []            # parameter ids we could not read fully
    touched: set[int] = set()         # stations with a value written
    consecutive_fail = 0
    last_fail: object = None

    class _Halt(Exception):
        pass

    async def _get(client, path, params):
        """One guarded request. Returns parsed JSON, or None for a failure that
        only affects this parameter. Raises _Halt when the run must end."""
        nonlocal requests_made, guard_stop, abort_reason, consecutive_fail, last_fail
        if asyncio.get_event_loop().time() - started >= _READINGS_MAX_RUNTIME_S:
            abort_reason = f"wall-clock budget ({_READINGS_MAX_RUNTIME_S}s) reached"
            raise _Halt
        if requests_made >= _READINGS_MAX_REQUESTS:
            abort_reason = f"request ceiling ({_READINGS_MAX_REQUESTS}) reached"
            raise _Halt
        try:
            resp = await openaq_guard.guarded_get(
                client, f"{base}{path}", pacer=pacer, budget=budget, params=params)
        except openaq_guard.OpenAQStop as stop:
            guard_stop = stop.reason
            raise _Halt
        except Exception as exc:  # network error: an upstream failure, not "no data"
            resp, last_fail = None, type(exc).__name__
        requests_made += 1
        if resp is not None and resp.status_code == 200:
            consecutive_fail = 0
            return resp.json()
        if resp is not None:
            last_fail = resp.status_code
        # ⛔ missing and broken never share a path: a failure is recorded as a
        # failure (sync_log), never as an empty result.
        if resp is None or resp.status_code >= 500:
            consecutive_fail += 1
            if consecutive_fail >= _CONSECUTIVE_5XX_ABORT:
                abort_reason = (f"aborted after {consecutive_fail} consecutive upstream "
                                f"failures from OpenAQ (last: {last_fail}; "
                                f"{requests_made} calls this run)")
                raise _Halt
        return None

    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        try:
            catalogue = await _get(client, "/parameters", {"limit": _READINGS_PAGE_LIMIT})
            if catalogue is None:
                abort_reason = f"OpenAQ /parameters unavailable ({last_fail}); nothing fetched"
                raise _Halt
            # name -> [(parameter id, OpenAQ's own unit)]
            by_name: dict[str, list[tuple[int, str | None]]] = {}
            for p in catalogue.get("results") or []:
                if p.get("name") in _READINGS_COLUMNS and p.get("id") is not None:
                    by_name.setdefault(p["name"], []).append((p["id"], p.get("units")))
            missing = [n for n in _READINGS_COLUMNS if n not in by_name]
            if missing:
                log.warning("air_quality_readings: /parameters lists no id for %s", missing)

            # Least recently refreshed first (NULLS = never = first).
            names = sorted(by_name, key=lambda n: (last_by_name.get(n) is not None,
                                                    last_by_name.get(n) or _EPOCH))
            for name in names:
                column, is_conc = _READINGS_COLUMNS[name]
                guard = _concentration_or_none if is_conc else _score_or_none
                best: dict[int, tuple[datetime, float]] = {}
                for param_id, unit in by_name[name]:
                    page = 1
                    while page <= _READINGS_MAX_PAGES_PER_PARAM:
                        data = await _get(client, f"/parameters/{param_id}/latest",
                                          {"limit": _READINGS_PAGE_LIMIT, "page": page})
                        if data is None:
                            failed.append(f"{name}#{param_id}")
                            break
                        results = data.get("results") or []
                        if not results:
                            break
                        param_rows, page_best, seen = [], {}, set()
                        for r in results:
                            loc = r.get("locationsId")
                            if loc not in known:
                                continue
                            seen.add(loc)
                            value = _score_or_none(r.get("value"))
                            if value is None:
                                continue
                            # The reading's OWN time; None stays None. Never NOW().
                            dt = _parse_openaq_dt(r.get("datetime"))
                            sensor_id = r.get("sensorsId")
                            param_rows.append((
                                loc, sensor_id if sensor_id is not None else 0,
                                name, value, unit, dt))
                            gv = guard(value)
                            if gv is None:
                                continue
                            key = dt or _EPOCH
                            cur = page_best.get(loc) or best.get(loc)
                            if cur is None or key >= cur[0]:
                                page_best[loc] = (key, gv)
                        best.update(page_best)
                        async with db.pool.acquire() as conn:
                            if param_rows:
                                await conn.executemany(_READINGS_PARAM_UPSERT, param_rows)
                            if page_best:
                                # `column` comes from the fixed whitelist above.
                                await conn.executemany(
                                    f"UPDATE air_quality_stations SET {column} = $2, "
                                    "last_updated = NOW() WHERE location_id = $1",
                                    [(loc, v) for loc, (_, v) in page_best.items()])
                            if seen:
                                await conn.execute(
                                    "UPDATE air_quality_stations "
                                    "SET readings_attempted_at = NOW(), readings_error = NULL "
                                    "WHERE location_id = ANY($1::int[])", list(seen))
                        touched.update(seen)
                        if len(results) < _READINGS_PAGE_LIMIT:
                            break
                        found = str((data.get("meta") or {}).get("found") or "0")
                        if not found.startswith(">"):
                            digits = "".join(c for c in found if c.isdigit())
                            if page * _READINGS_PAGE_LIMIT >= int(digits or 0):
                                break
                        page += 1
                    else:
                        failed.append(f"{name}#{param_id}:page-cap")
                log.info("air_quality_readings: %s done, %d stations with a value", name, len(best))
        except _Halt:
            pass

    global _air_quality_cache
    _air_quality_cache = None
    updated = len(touched)

    reason = guard_stop or abort_reason
    if reason is None and failed:
        reason = f"incomplete: could not read {', '.join(failed[:10])} ({last_fail})"
    if reason:
        # ⛔ log_sync_skipped, never log_sync: this run did not complete a
        # refresh, and log_sync stamps last_synced_at = NOW().
        log.warning("air_quality_readings: %s — %d requests, %d stations written",
                    reason, requests_made, updated)
        await sync_log.log_sync_skipped("air_quality_readings", reason)
        return updated

    # total_records = stations still without ANY reading (no headline value and
    # no params row) — unchanged meaning; a station OpenAQ has no latest for
    # stays here, so this is not expected to reach 0.
    async with db.pool.acquire() as conn:
        remaining = await conn.fetchval(
            "SELECT COUNT(*) FROM air_quality_stations s "
            "WHERE s.pm25 IS NULL AND s.no2 IS NULL AND s.o3 IS NULL "
            "  AND NOT EXISTS (SELECT 1 FROM air_quality_params p WHERE p.location_id = s.location_id)"
        )
    await _log_land_sync("air_quality_readings", updated, remaining)
    log.info("air_quality_readings: done — %d stations written, %d requests, %d without any reading",
             updated, requests_made, remaining)
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
                        'geometry', ST_AsGeoJSON(s.geom)::json,
                        'properties', json_build_object(
                            'id', s.id,
                            'location_id', s.location_id,
                            'name', s.name,
                            'city', s.city,
                            'country', s.country,
                            'pm25', s.pm25,
                            'so2', s.so2,
                            'no2', s.no2,
                            'o3', s.o3,
                            'co', s.co,
                            'last_updated', s.last_updated::text,
                            'locality', s.locality,
                            'timezone', s.timezone,
                            'is_mobile', s.is_mobile,
                            'is_monitor', s.is_monitor,
                            'provider', s.provider,
                            'owner', s.owner,
                            'datetime_first', s.datetime_first::text,
                            'datetime_last', s.datetime_last::text,
                            'pm10', s.pm10,
                            'bc', s.bc,
                            'no', s.no,
                            'nox', s.nox,
                            'humidity', s.humidity,
                            'temperature', s.temperature,
                            'co2', s.co2,
                            'pm1', s.pm1,
                            'pm4', s.pm4,
                            'ch4', s.ch4,
                            'ufp', s.ufp,
                            'coverage_pct', s.coverage_pct,
                            -- ⛔ The unit OpenAQ published, per pollutant, verbatim.
                            -- Without it every consumer had to guess, and both
                            -- guessed wrong: the panel printed "ppb" on every
                            -- NO2/O3/CO row, and stationAqi() scored them on a
                            -- ppb scale. Measured on production 2026-09-10:
                            --   o3  ppb on     7 of 10,282 stations (0.07%)
                            --   no2 ppb on   586 of 12,793 (4.6%)
                            --   co  ppb on   563 of  7,034 (8.0%)
                            -- The rest report µg/m³ or ppm. Ozone in ppm scored
                            -- as ppb collapses to AQI 0 and drops out of the
                            -- worst-pollutant rule entirely.
                            'units', u.units
                        )
                    )
                ), '[]'::json)
            )::text
            FROM air_quality_stations s
            LEFT JOIN LATERAL (
                SELECT json_object_agg(p.parameter, p.unit) AS units
                FROM air_quality_params p
                WHERE p.location_id = s.location_id AND p.unit IS NOT NULL
            ) u ON TRUE
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
            features = arcgis_features(resp.json(), label="water_risk")
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
