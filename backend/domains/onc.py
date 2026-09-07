# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""ONC (Ocean Networks Canada) family — observatory locations, individual
instrument deployments (with per-device enrichment: deployment dates, status,
citation, latest sensor readings, data products), 72h sensor sparklines, 24h
ADCP depth-binned backscatter strips, CTD cast profiles, and USGS earthquakes
(present here because `/v1/onc/earthquakes-near/{location_code}` — querying
`usgs_earthquakes` by distance from an ONC location — is its only consumer).

Moved verbatim out of backend/main.py (Task 3 of the backend vertical-split
refactor, Phase 3). Only permitted edits applied: `@app.get` -> `@router.get`,
`_pool.acquire()` -> `db.pool.acquire()`, leading underscore dropped from
every moved top-level function name (`_sync_onc_instruments` ->
`sync_onc_instruments`, `_is_raw_beam_sensor` -> `is_raw_beam_sensor`,
`_is_environmental_property` -> `is_environmental_property`,
`_is_housekeeping_label` -> `is_housekeeping_label`, `_humanize_sensor_code`
-> `humanize_sensor_code`, `_prioritize_readings` -> `prioritize_readings`,
`_enrich_onc_instruments` -> `enrich_onc_instruments`, `_sync_onc` ->
`sync_onc`, `_sync_onc_sensors` -> `sync_onc_sensors`, `_sync_onc_sparklines`
-> `sync_onc_sparklines`, `_fetch_adcp_location` -> `fetch_adcp_location`,
`_sync_onc_adcp_strips` -> `sync_onc_adcp_strips`, `_sync_onc_ctd_profiles`
-> `sync_onc_ctd_profiles`, `_sync_usgs_earthquakes` -> `sync_usgs_earthquakes`;
`get_onc_instruments`/`get_onc`/`live_onc`/`get_onc_sparkline`/
`get_onc_adcp_strip`/`get_onc_ctd`/`get_earthquakes_near_onc` already had no
underscore — same rule sensors.py/seafloor.py established), and
imports/docstring. Module-level *constants* (non-callables) keep their
leading underscore, matching that precedent: `_ONC_INSTRUMENTS_WFS`,
`_ONC_RAW_BEAM_PREFIXES`, `_ONC_ENV_PROPERTIES`,
`_ONC_HOUSEKEEPING_LABEL_KEYWORDS`, `_SPARKLINE_PROPERTIES`,
`_SPARKLINE_MAX_SAMPLES`, `_ADCP_WINDOW_H`, `_ADCP_MAX_CONCURRENT`,
`_CTD_PROFILE_PROPERTIES`, `_ONC_CODE_MAP`, `_ONC_LABEL_MAP`, `_ONC_API_BASE`,
`_ONC_DEVICE_CATEGORIES`, and the six cache globals.

## Measured line count vs. the task brief's estimate

The brief estimated 857 lines across 17 symbols. The real move is two
contiguous main.py ranges — lines 534-1478 (constants, helpers, six syncs)
and lines 4228-4549 (seven endpoints, interleaved with four more constants
that `_sync_onc`/`_sync_onc_sensors`/`_sync_onc_ctd_profiles` forward-reference
earlier in the file) — for ~1,267 raw lines before file assembly, closer to
the brief's own "measured ~1,100" correction than to 857. Both ranges were
fully contiguous ONC/USGS content end to end; nothing inside either range
belonged to another family, and nothing outside them needed to move in.

## Five symbols the brief's inventory table didn't name, all moved anyway

Sitting *inside* the two contiguous ranges above, contiguous with the listed
symbols, ONC-only by every caller check:
- `_humanize_sensor_code` (main.py 699-702) — sits between `_is_housekeeping_
  label` and `_prioritize_readings`; its only caller is
  `_enrich_onc_instruments` (line 804 pre-move), which the brief does list.
- `_SPARKLINE_PROPERTIES` / `_SPARKLINE_MAX_SAMPLES` (1036-1045) — consumed
  only by `_sync_onc_sparklines`.
- `_ADCP_WINDOW_H` / `_ADCP_MAX_CONCURRENT` (1156-1157) — consumed only by
  `_sync_onc_adcp_strips`/`_fetch_adcp_location`.
- `_CTD_PROFILE_PROPERTIES` (1324) — consumed only by `_sync_onc_ctd_profiles`
  (assigned but the actual filter list is inlined as a tuple literal at the
  call site — kept anyway since it's declared immediately above the function
  that logically owns it and referenced nowhere else).

## `_parse_year` — NOT moved (zero callers anywhere), since deleted from main.py

`_parse_year` (formerly main.py 514-531) sat immediately above
`_ONC_INSTRUMENTS_WFS`, inside the region this task claimed. A repo-wide grep
for `_parse_year` at the time turned up exactly one other hit family:
`ingestion/seaflea_ingest.py`'s own `_parse_year` (unrelated, module-local,
imported by `test_seaflea_ingest.py`) — main.py's copy had **no callers at
all**, not in main.py, not in any other backend module. The brief's
instruction was binary — move it if ONC is its only consumer, leave it if
anything outside ONC calls it — and this case was neither: there was no
consumer, ONC or otherwise. Read literally ("if ONC is its only consumer,
move it"), a function with zero consumers did not meet that condition, so it
stayed in main.py at that point, untouched and unimported — dead code that
happened to be typed next to `_ONC_INSTRUMENTS_WFS`, not ONC's. A later
cleanup task deleted it from main.py entirely; the only `_parse_year` left in
the codebase is `ingestion/seaflea_ingest.py`'s unrelated one.

## Caches — none swept by `admin_cache_clear`, all six now swept here

`_onc_cache`, `_onc_instruments_cache`, `_onc_sparkline_cache`,
`_onc_adcp_cache`, `_onc_ctd_cache`, `_usgs_eq_cache` were never referenced by
`admin_cache_clear()` before this move (confirmed by grep) — so unlike some
earlier domain extractions, this one adds zero lines' worth of removal from
that function. All six are cache-shaped module globals per
`test_domain_cache_clear.py`'s contract, so `clear_caches()` here empties all
six: `None` for the two scalars (`_onc_cache`, `_onc_instruments_cache`),
`.clear()` for the four location-keyed dicts. This *does* widen
`/admin/cache/clear`'s effective behaviour (it now also drops these six),
matching the sensors.py/geochem.py precedent for caches that were never
hand-cleared pre-move.

## What did NOT move, and why

The six background-loop wrappers (`_onc_sensor_sync_task`,
`_onc_instruments_daily_task`, `_onc_sparkline_task`, `_onc_adcp_task`,
`_onc_ctd_task`, `_usgs_earthquakes_task`) stay in main.py per the brief —
startup orchestration stays centralized, same pattern Phase 2 and Task 2
used. `ONC_SENSOR_SYNC_INTERVAL_SECONDS` (the one ONC-named constant that
configures a task, not a sync) stays with it. All six task bodies were
rewired to call `onc.sync_onc_instruments`/`onc.enrich_onc_instruments`/
`onc.sync_onc_sparklines`/`onc.sync_onc_adcp_strips`/`onc.sync_onc_ctd_profiles`/
`onc.sync_usgs_earthquakes` respectively. `_sync_all_sources`'s weekly chain
and `_SYNC_SOURCES` were rewired the same way for `onc`, `onc-sensors`,
`onc-instruments`, `onc-instruments-enrich`, `onc-sparklines`, `onc-adcp`,
`onc-ctd`, `usgs-earthquakes`.

`_enrich_claim_boundaries` (Task's explicit "different family" list, Phase 4
`isa`) queries `onc_locations` directly in a raw-SQL CTE aliased `onc`
(formerly main.py ~2124-2150, now `isa.enrich_claim_boundaries` in
`domains/isa.py`) — confirmed by grep it calls no function this module owns.
Left exactly where it is. Likewise the dashboard's `SOURCE_LABELS` JS map and the
`_INVENTORY` tuple reference `onc_locations`/`onc_instruments`/
`usgs_earthquakes` only as table-name strings or dashboard labels, never as
function calls into the moved bodies — no rewiring needed there.

## Two ONC data-product ingestion modules imported here, not owned here

`ingestion/onc_adcp_product.py` and `ingestion/onc_dataproduct.py` are ONC's
two-tier-API resolution helpers (see the domain-knowledge section below) —
imported by `fetch_adcp_location`/`sync_onc_adcp_strips`, not moved (they are
service/ingestion modules, not main.py symbols the brief's inventory names).

## Domain knowledge (load-bearing)

- ONC has two API tiers and picking the wrong one produces silence, not
  errors: `scalardata/location` serves scalar sensors only; depth-resolved,
  spectral and audio data live behind `dataProductDelivery`, an asynchronous
  order API (`request` -> `run` -> poll `status` -> `download`).
- The ADCP product code is per-device, not per-frequency: Teledyne RDI
  publishes `RADCPTS`, Nortek publishes `NTS`; ordering the wrong one returns
  HTTP 400 errorCode 127. `onc_dataproduct.pick_product_code`/
  `resolve_adcp_product` resolve it — never infer from frequency.
- The `dataProductDelivery` status payload has no `status` key — the field is
  `searchHdrStatus`. A poller grepping for `"status": "complete"` waits
  forever.
- `onc_acoustic_events` is retired (dropped 2026-07-10) — it held 0 rows for
  its entire life. Do not resurrect it; nothing in this module references it.
- ONC's scalardata JSON contains bare `NaN` tokens (not valid per RFC 8259).
  Python accepts them; Postgres rejects them at the jsonb cast. A missing
  sample must be `null`, never `0.0` — 0 dB is a real backscatter value. See
  the `allow_nan=False` guards in `fetch_adcp_location`'s `json.dumps` calls
  and the `math.isnan` skips throughout the sync functions.
- Match ADCP devices on `'%Doppler%'`, never `'%CURRENT%'` — the stored
  category reads "Acoustic Doppler Current Profiler 75 kHz", so a
  `'%CURRENT%'` predicate also sweeps in plain Current Meters (see
  `sync_onc_adcp_strips`'s SQL comment).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone

import db
import httpx
from auth import get_api_key
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from indexnow import notify_indexnow as _notify_indexnow
from indexnow import SITE_HOST
from ingestion import onc_adcp_product
from ingestion import onc_dataproduct
from sync_log import log_sync as _log_sync

log = logging.getLogger(__name__)
router = APIRouter()

# ── Caches ──────────────────────────────────────────────────────────────────
_onc_cache:             str | None = None
_onc_instruments_cache: str | None = None
_onc_sparkline_cache:   dict[str, str] = {}  # location_code → JSON
_onc_adcp_cache:        dict[str, str] = {}  # location_code → JSON
_onc_ctd_cache:         dict[str, str] = {}  # location_code → JSON
_usgs_eq_cache:         dict[str, str] = {}  # location_code → JSON


def clear_caches() -> None:
    """Drop this domain's cached responses. Called by /admin/cache/clear.

    See module docstring "Caches" section — none of these six were swept by
    `admin_cache_clear()` before this move; all six are swept here now.
    """
    global _onc_cache, _onc_instruments_cache
    _onc_cache = None
    _onc_instruments_cache = None
    _onc_sparkline_cache.clear()
    _onc_adcp_cache.clear()
    _onc_ctd_cache.clear()
    _usgs_eq_cache.clear()


_ONC_INSTRUMENTS_WFS = (
    "https://dservices2.arcgis.com/qRqOFxxnwUHOSocZ/arcgis/services/ONC_Instruments/WFSServer"
    "?service=WFS&version=2.0.0&request=GetFeature&typeNames=ONC_Instruments:ONC_Instruments"
    "&outputFormat=GEOJSON"
)


async def sync_onc_instruments(skip_guard_hours: int = 20) -> int:
    """Fetch ONC instrument deployments from ArcGIS WFS — one point per active device.

    ONC refreshes the ArcGIS feed whenever deployments change. We run daily to
    keep active-device status fresh. The skip guard prevents double-fires if
    manual + scheduled sync collide.
    """
    async with db.pool.acquire() as conn:
        last = await conn.fetchval("SELECT last_synced_at FROM sync_log WHERE source = 'onc_instruments'")
        if last and (datetime.now(tz=timezone.utc) - last).total_seconds() < skip_guard_hours * 3600:
            log.info("onc_instruments: skipping — synced %s", last)
            return 0

    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.get(_ONC_INSTRUMENTS_WFS)
            r.raise_for_status()
            fc = r.json()
    except Exception as exc:
        log.warning("onc_instruments: fetch failed — %s", exc)
        return 0

    features = fc.get("features") or []
    if not features:
        log.warning("onc_instruments: no features returned")
        return 0

    # Preserve previously-enriched fields by keying on device_id
    async with db.pool.acquire() as conn:
        enriched_rows = await conn.fetch(
            """SELECT device_id, deployment_start, deployment_end, status,
                      description, data_products, enriched_at,
                      latest_readings, readings_at
               FROM onc_instruments WHERE enriched_at IS NOT NULL"""
        )
    preserved: dict[int, dict] = {r["device_id"]: dict(r) for r in enriched_rows if r["device_id"] is not None}

    inserted = 0
    async with db.pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE onc_instruments")
        for f in features:
            props = f.get("properties") or {}
            geom = f.get("geometry")
            if not geom or geom.get("type") != "Point":
                continue
            try:
                # ArcGIS WFS returns PascalCase_With_Underscores keys (Device_Category_Name,
                # Device_ID, Depth__metres_, …). Reading lowercase keys silently NULLs every
                # field — and NULL device_id defeats the ON CONFLICT guard, so the table fills
                # with 911 all-NULL rows while sync_log reports success. Don't "simplify" back.
                depth = props.get("Depth__metres_")
                dev_id_raw = props.get("Device_ID")
                dev_id = int(dev_id_raw) if dev_id_raw is not None else None
                dev_code = props.get("Device_Code")
                loc_code = props.get("Location_Code")
                device_link = f"https://data.oceannetworks.ca/DeviceListing?DeviceId={dev_id}" if dev_id else None
                location_link = f"https://data.oceannetworks.ca/LocationDetails?locationCode={loc_code}" if loc_code else None
                prev = preserved.get(dev_id) if dev_id else None
                await conn.execute(
                    """INSERT INTO onc_instruments
                       (device_id, device_code, device_name, device_category,
                        location_code, location_name, site_name, depth_m, image_url,
                        device_link, location_link,
                        deployment_start, deployment_end, status, description,
                        data_products, enriched_at, latest_readings, readings_at, geom)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                               $12, $13, $14, $15, $16, $17, $18, $19,
                               ST_SetSRID(ST_GeomFromGeoJSON($20), 4326))
                       ON CONFLICT (device_id) DO NOTHING""",
                    dev_id,
                    dev_code,
                    props.get("Device_Name"),
                    props.get("Device_Category_Name"),
                    loc_code,
                    props.get("Location_Name"),
                    props.get("Site_Name"),
                    float(depth) if depth is not None else None,
                    props.get("Image_URL"),
                    device_link,
                    location_link,
                    prev["deployment_start"] if prev else None,
                    prev["deployment_end"] if prev else None,
                    prev["status"] if prev else None,
                    prev["description"] if prev else None,
                    prev["data_products"] if prev else None,
                    prev["enriched_at"] if prev else None,
                    prev["latest_readings"] if prev else None,
                    prev["readings_at"] if prev else None,
                    json.dumps(geom),
                )
                inserted += 1
            except Exception as e:
                log.warning("onc_instruments: insert failed: %s", e)
        total = await conn.fetchval("SELECT COUNT(*) FROM onc_instruments")
    global _onc_instruments_cache
    _onc_instruments_cache = None
    await _log_sync("onc_instruments", inserted, total)
    log.info("onc_instruments: %d features, %d total (preserved enrichment for %d)",
             inserted, total, len(preserved))
    return inserted


# Raw acoustic streams (per-beam intensity, correlation, etc.) — useful for
# scientists running their own QC, but noise in a public popup. Skip them.
_ONC_RAW_BEAM_PREFIXES = (
    "amplitude_beam", "correlation_beam", "current_velocity_beam",
    "echo_intensity", "error_velocity", "signal_strength_beam",
    "raw_pressure", "internal_temperature",
)
# Strict allowlist of propertyCodes representing environmental measurements
# users care about. Anything outside this set is dropped — keeps battery,
# accelerometer, junction-box, status-code, voltage, etc. out of the public panel.
_ONC_ENV_PROPERTIES = (
    "seawatertemperature", "temperature",
    "salinity", "practicalsalinity",
    "oxygen", "dissolvedoxygen", "oxygensaturation",
    "ph",
    "seawaterpressure", "pressure", "depth",
    "conductivity",
    "chlorophyll", "fluorescence",
    "turbidity",
    "currentspeed", "currentdirection", "seawatervelocity",
    "density", "sigmatheta",
    "co2", "pco2", "partialpressureofco2", "nitrate",
    "soundspeed", "soundpressurelevel", "soundvelocity",
    "par", "irradiance",
    "airtemperature", "windspeed", "winddirection", "barometricpressure",
    "icethickness", "seawatersalinity",
)
# Even when propertyCode is in the allowlist, ONC labels some board-housekeeping
# channels with environmental properties (e.g. "On board temperature" tagged as
# seawatertemperature). Drop those by label keyword.
_ONC_HOUSEKEEPING_LABEL_KEYWORDS = (
    "on board", "off board", "onboard", "offboard",
    "case", "chassis", "battery", "acceleration",
    "internal", "board temperature", "ground fault",
    "voltage", "current limit", "status", "digital input",
    "junction box", "j1 ", "j2 ", "j3 ", "j4 ", "j5 ", "j6 ",
)


def is_raw_beam_sensor(code: str) -> bool:
    return any(code.startswith(p) for p in _ONC_RAW_BEAM_PREFIXES)


def is_environmental_property(prop: str) -> bool:
    if not prop:
        return False
    return any(prop == p or prop.startswith(p) for p in _ONC_ENV_PROPERTIES)


def is_housekeeping_label(label: str) -> bool:
    if not label:
        return False
    low = label.lower()
    return any(kw in low for kw in _ONC_HOUSEKEEPING_LABEL_KEYWORDS)


def humanize_sensor_code(code: str) -> str:
    """Turn 'current_speed_calculated' → 'Current Speed'. Fallback when sensorName missing."""
    cleaned = code.replace("_calculated", "").replace("_", " ").strip()
    return " ".join(w.capitalize() for w in cleaned.split())


def prioritize_readings(readings: list[dict]) -> list[dict]:
    """Sort by propertyCode rank so temp / salinity / oxygen / current come first."""
    def rank(r: dict) -> int:
        p = r.get("prop") or ""
        for i, pref in enumerate(_ONC_ENV_PROPERTIES):
            if p == pref or p.startswith(pref):
                return i
        return len(_ONC_ENV_PROPERTIES)
    return sorted(readings, key=rank)


async def enrich_onc_instruments(batch_limit: int | None = None) -> int:
    """Enrich cached ONC instruments with deployment dates, status, description,
    and data products from the ONC Oceans 3.0 API. All fields are cached in the
    DB so the map panel never makes live API calls."""
    token = os.getenv("ONC_TOKEN")
    if not token:
        log.warning("onc_instruments enrichment: ONC_TOKEN not set — skipping")
        return 0

    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT device_id, device_code FROM onc_instruments
               WHERE device_code IS NOT NULL
                 AND (enriched_at IS NULL OR enriched_at < NOW() - INTERVAL '7 days')
               ORDER BY enriched_at NULLS FIRST, device_id
               LIMIT $1""",
            batch_limit if batch_limit else 10000,
        )
    if not rows:
        log.info("onc_instruments enrichment: nothing to enrich")
        return 0

    sem = asyncio.Semaphore(8)
    enriched = 0

    async def _fetch_one(client: httpx.AsyncClient, device_id: int, device_code: str) -> dict | None:
        async with sem:
            # Deployments — primary source of truth for status + dates + DOI citation.
            # Older Vemco devices have no /devices entry but DO have deployments;
            # we no longer abandon those devices.
            depl_start = depl_end = None
            status = "unknown"
            description: str | None = None  # citation DOI (most useful per-device prose)
            try:
                dep_r = await client.get(
                    f"{_ONC_API_BASE}/deployments",
                    params={"method": "get", "deviceCode": device_code, "token": token},
                    timeout=20,
                )
                if dep_r.status_code == 200:
                    deps = dep_r.json() or []
                    if isinstance(deps, list) and deps:
                        def _parse(d):
                            v = d.get("begin") or d.get("dateFrom")
                            try: return datetime.fromisoformat(v.replace("Z", "+00:00")) if v else None
                            except Exception: return None
                        deps.sort(key=lambda d: _parse(d) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
                        latest = deps[0]
                        depl_start = _parse(latest)
                        end_raw = latest.get("end") or latest.get("dateTo")
                        try:
                            depl_end = datetime.fromisoformat(end_raw.replace("Z", "+00:00")) if end_raw else None
                        except Exception:
                            depl_end = None
                        status = "active" if depl_end is None else "retired"
                        cit = (latest.get("citation") or {}).get("citation")
                        if cit and isinstance(cit, str):
                            description = cit.strip()
            except Exception as exc:
                log.debug("onc enrich deployments %s: %s", device_code, exc)

            # Latest sensor readings (the actual measured values — what users want)
            readings: list[dict] = []
            try:
                date_to = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                date_from = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                sd_r = await client.get(
                    f"{_ONC_API_BASE}/scalardata/device",
                    params={
                        "method": "getByDevice",
                        "deviceCode": device_code,
                        "dateFrom": date_from,
                        "dateTo": date_to,
                        "rowLimit": 1,
                        "token": token,
                    },
                    timeout=25,
                )
                if sd_r.status_code == 200:
                    for sensor in (sd_r.json().get("sensorData") or []):
                        code = (sensor.get("sensorCode") or "").lower()
                        prop = (sensor.get("propertyCode") or "").lower()
                        if not code or is_raw_beam_sensor(code):
                            continue
                        # Strict allowlist: only keep environmental measurements.
                        if not is_environmental_property(prop):
                            continue
                        # Drop board-housekeeping channels mislabelled as env props.
                        label = sensor.get("sensorName") or humanize_sensor_code(code)
                        if is_housekeeping_label(label):
                            continue
                        data = sensor.get("data") or {}
                        vals = data.get("values") or []
                        times = data.get("sampleTimes") or []
                        v = vals[-1] if vals else None
                        if v is None or (isinstance(v, float) and math.isnan(v)):
                            continue
                        readings.append({
                            "code":  code,
                            "prop":  prop,
                            "label": label,
                            "value": v,
                            "unit":  sensor.get("unitOfMeasure"),
                            "time":  times[-1] if times else None,
                        })
                    readings = prioritize_readings(readings)[:8]
            except Exception as exc:
                log.debug("onc enrich scalardata %s: %s", device_code, exc)

            # Data products available for this device
            products: list[dict] = []
            try:
                dp_r = await client.get(
                    f"{_ONC_API_BASE}/dataProducts",
                    params={"method": "get", "deviceCode": device_code, "token": token},
                    timeout=20,
                )
                if dp_r.status_code == 200:
                    dp_list = dp_r.json() or []
                    if isinstance(dp_list, list):
                        seen_codes: set[str] = set()
                        for dp in dp_list:
                            code = dp.get("dataProductCode")
                            if not code or code in seen_codes:
                                continue
                            seen_codes.add(code)
                            products.append({
                                "code": code,
                                "name": dp.get("dataProductName") or code,
                                "help_url": dp.get("helpDocument"),
                            })
                            if len(products) >= 15:
                                break
            except Exception as exc:
                log.debug("onc enrich dataProducts %s: %s", device_code, exc)

            return {
                "device_id": device_id,
                "deployment_start": depl_start,
                "deployment_end": depl_end,
                "status": status,
                "description": description,
                "data_products": products,
                "latest_readings": readings,
            }

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[_fetch_one(client, r["device_id"], r["device_code"]) for r in rows if r["device_id"]],
            return_exceptions=False,
        )

    now = datetime.now(timezone.utc)
    async with db.pool.acquire() as conn:
        for res in results:
            if not res:
                continue
            try:
                await conn.execute(
                    """UPDATE onc_instruments
                       SET deployment_start = $2,
                           deployment_end   = $3,
                           status           = $4,
                           description      = $5,
                           data_products    = $6::jsonb,
                           enriched_at      = $7,
                           latest_readings  = $8::jsonb,
                           readings_at      = CASE WHEN jsonb_array_length($8::jsonb) > 0 THEN $7 ELSE readings_at END
                       WHERE device_id = $1""",
                    res["device_id"],
                    res["deployment_start"],
                    res["deployment_end"],
                    res["status"],
                    res["description"],
                    json.dumps(res["data_products"]),
                    now,
                    json.dumps(res["latest_readings"]),
                )
                enriched += 1
            except Exception as exc:
                log.warning("onc enrichment update %s: %s", res["device_id"], exc)

    global _onc_instruments_cache
    _onc_instruments_cache = None
    await _log_sync("onc_instruments_enrich", enriched, enriched)
    log.info("onc_instruments enrichment: updated %d / %d devices", enriched, len(rows))
    return enriched


async def sync_onc() -> int:
    """Fetch ONC observatory locations and replace DB contents.

    Full replace (truncate + insert) rather than upsert so that locations
    removed from the oceanographic filter (e.g. AIS-only shore stations) are
    not left as stale rows.
    """
    from ingestion.onc_ingest import fetch_onc_locations
    locations = await fetch_onc_locations()
    if not locations:
        return 0
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("TRUNCATE TABLE onc_locations")
            await conn.executemany(
                """INSERT INTO onc_locations
                   (location_code, name, lat, lon, depth_m, description, geom, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6,
                           ST_SetSRID(ST_MakePoint($4, $3), 4326),
                           NOW())""",
                [(l["location_code"], l["name"], l["lat"], l["lon"],
                  l["depth_m"], l["description"])
                 for l in locations],
            )
        count = await conn.fetchval("SELECT COUNT(*) FROM onc_locations")
    global _onc_cache
    _onc_cache = None
    await _log_sync("onc", len(locations), count)
    asyncio.create_task(_notify_indexnow([f"https://{SITE_HOST}/sitemap.xml"]))
    # Immediately enrich with sensor data so the map is useful on first load
    await sync_onc_sensors()
    return count


async def sync_onc_sensors() -> int:
    """Fetch latest CTD/oxygen readings for every ONC location and cache in DB.

    Runs concurrently (up to 8 parallel requests) to process ~622 locations
    quickly. Locations with no data within the past year are deleted — only
    instruments with actual readings appear on the map.

    Returns count of locations with live sensor data.
    """
    token = os.getenv("ONC_TOKEN")
    if not token:
        log.warning("ONC_TOKEN not set — skipping sensor cache sync")
        return 0

    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT location_code FROM onc_locations")
    codes = [r["location_code"] for r in rows]
    if not codes:
        return 0

    now = datetime.now(timezone.utc)
    date_from = (now - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    date_to   = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    sem = asyncio.Semaphore(8)

    async def _fetch_one(client: httpx.AsyncClient, code: str) -> tuple[str, dict | None]:
        async with sem:
            for category in ("CTD", "OXYSENSOR"):
                params = {
                    "method":             "getByLocation",
                    "locationCode":       code,
                    "deviceCategoryCode": category,
                    "dateFrom":           date_from,
                    "dateTo":             date_to,
                    "rowLimit":           1,
                    "token":              token,
                }
                try:
                    r = await client.get(f"{_ONC_API_BASE}/scalardata/location", params=params, timeout=20)
                    if r.status_code != 200:
                        continue
                    sensors: dict[str, dict] = {}
                    for sensor in r.json().get("sensorData", []):
                        raw = sensor.get("sensorCode", "").lower()
                        friendly = _ONC_CODE_MAP.get(raw)
                        if not friendly:
                            continue
                        vals  = sensor.get("data", {}).get("values", [])
                        times = sensor.get("data", {}).get("sampleTimes", [])
                        val = vals[-1] if vals else None
                        # ONC sometimes returns NaN which is invalid JSON — skip
                        if val is not None and not (isinstance(val, float) and math.isnan(val)):
                            label, unit = _ONC_LABEL_MAP.get(friendly, (friendly, ""))
                            sensors[friendly] = {
                                "value": val,
                                "unit":  sensor.get("unitOfMeasure") or unit,
                                "label": label,
                                "time":  times[-1] if times else None,
                            }
                    if sensors:
                        return code, sensors
                except Exception as exc:
                    log.debug("onc sensor fetch %s/%s: %s", code, category, exc)
        return code, None

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[_fetch_one(client, c) for c in codes])

    with_data    = [(code, json.dumps(sensors)) for code, sensors in results if sensors]
    without_data = [code for code, sensors in results if sensors is None]

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            if with_data:
                await conn.executemany(
                    """UPDATE onc_locations
                       SET latest_sensors = $2::jsonb, sensors_fetched_at = NOW()
                       WHERE location_code = $1""",
                    with_data,
                )
            if without_data:
                await conn.execute(
                    "DELETE FROM onc_locations WHERE location_code = ANY($1::text[])",
                    without_data,
                )

    global _onc_cache
    _onc_cache = None
    log.info("onc sensors: %d with data, %d removed (no data)", len(with_data), len(without_data))
    await _log_sync("onc-sensors", len(with_data), len(with_data))
    return len(with_data)


# ── ONC Sparklines ────────────────────────────────────────────────────────────

# Primary sensor property codes to pull time-series for.
_SPARKLINE_PROPERTIES = [
    ("CTD",        "temperature",  "Temperature"),
    ("CTD",        "salinity",     "Salinity"),
    ("CTD",        "pressure",     "Pressure"),
    ("OXYSENSOR",  "oxygen",       "Oxygen"),
    ("TURBMETER",  "turbidity",    "Turbidity"),
]

# Max samples stored after downsampling (≈432 for 72h/10-min avg)
_SPARKLINE_MAX_SAMPLES = 432


async def sync_onc_sparklines() -> int:
    """Fetch 72-hour 10-min-average time series for primary sensors at every ONC location.

    One row per (location_code, property_code) stored as JSONB [[epoch_ms, value], …].
    Skips locations with no prior sensor data (only queries locations in onc_locations).
    Returns number of (location, property) pairs stored.
    """
    token = os.getenv("ONC_TOKEN")
    if not token:
        log.warning("sync_onc_sparklines: ONC_TOKEN not set — skipping")
        return 0

    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT location_code FROM onc_locations WHERE latest_sensors IS NOT NULL")
    codes = [r["location_code"] for r in rows]
    if not codes:
        return 0

    now = datetime.now(timezone.utc)
    date_from = (now - timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    date_to   = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    sem = asyncio.Semaphore(8)
    inserted = 0

    async def _fetch_one(client: httpx.AsyncClient, code: str, category: str, prop: str):
        async with sem:
            params = {
                "method":             "getByLocation",
                "locationCode":       code,
                "deviceCategoryCode": category,
                "propertyCode":       prop,
                "dateFrom":           date_from,
                "dateTo":             date_to,
                "resampleType":       "avg",
                "resamplePeriod":     600,
                "token":              token,
            }
            try:
                r = await client.get(f"{_ONC_API_BASE}/scalardata/location", params=params, timeout=30)
                if r.status_code != 200:
                    return None
                payload = r.json()
                for sensor in payload.get("sensorData", []):
                    values = sensor.get("data", {}).get("values", [])
                    times  = sensor.get("data", {}).get("sampleTimes", [])
                    unit   = sensor.get("unitOfMeasure", "")
                    if not values or not times:
                        continue
                    samples = [
                        [int(datetime.strptime(t, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp() * 1000), v]
                        for t, v in zip(times, values)
                        if v is not None and not (isinstance(v, float) and math.isnan(v))
                    ]
                    if not samples:
                        continue
                    # Downsample to max
                    if len(samples) > _SPARKLINE_MAX_SAMPLES:
                        step = len(samples) // _SPARKLINE_MAX_SAMPLES
                        samples = samples[::step]
                    return (code, prop, unit, samples)
            except Exception as exc:
                log.debug("sparkline %s/%s/%s: %s", code, category, prop, exc)
            return None

    async with httpx.AsyncClient() as client:
        tasks = [
            _fetch_one(client, code, category, prop)
            for code in codes
            for (category, prop, _) in _SPARKLINE_PROPERTIES
        ]
        results = await asyncio.gather(*tasks)

    rows_to_upsert = [r for r in results if r is not None]

    if rows_to_upsert:
        async with db.pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO onc_sparklines (location_code, property_code, unit, samples,
                       window_start, window_end, updated_at)
                   VALUES ($1, $2, $3, $4::jsonb, $5, $6, NOW())
                   ON CONFLICT (location_code, property_code) DO UPDATE
                   SET unit=EXCLUDED.unit, samples=EXCLUDED.samples,
                       window_start=EXCLUDED.window_start, window_end=EXCLUDED.window_end,
                       updated_at=NOW()""",
                [(loc, prop, unit, json.dumps(samples),
                  datetime.now(timezone.utc) - timedelta(hours=72),
                  datetime.now(timezone.utc))
                 for loc, prop, unit, samples in rows_to_upsert],
            )
        inserted = len(rows_to_upsert)

    global _onc_sparkline_cache
    _onc_sparkline_cache = {}
    await _log_sync("onc-sparklines", inserted, inserted)
    log.info("onc_sparklines: %d series stored", inserted)
    return inserted


# ── ONC ADCP Strips ───────────────────────────────────────────────────────────

# Depth-resolved ADCP data is NOT available from `scalardata/location`: real ADCPs
# publish only engineering scalars there (pressure/pitch/roll/heading/soundspeed),
# and asking for `amplitudebeam1` returns HTTP 400 "does not have propertyCode".
# The profile lives in the RADCPTS data product, ordered via `dataProductDelivery`.
# ONC does the 15-minute ensemble averaging server-side (dpo_ensemblePeriod), so a
# 24 h window arrives as exactly 96 time buckets and ~1 MB instead of 152 MB of raw.

_ADCP_WINDOW_H = 24
_ADCP_MAX_CONCURRENT = 3   # be a good citizen: each location queues a job on ONC


async def fetch_adcp_location(
    client: httpx.AsyncClient,
    token: str,
    location_code: str,
    device_code: str,
    dcc: str,
    date_from: str,
    date_to: str,
    window_start: datetime,
    window_end: datetime,
) -> bool:
    """Order, download and store one location's backscatter strip. True if stored."""
    # Ask ONC which product this device publishes — RDI instruments offer RADCPTS,
    # Nortek ones only NTS. Inferring it from the frequency yields HTTP 400 / 127.
    product = await onc_dataproduct.resolve_adcp_product(
        client, token, location_code, dcc, extension=onc_adcp_product.DATA_PRODUCT_EXT
    )
    if product is None:
        log.info("onc_adcp_strips[%s]: no depth-binned product offered for %s", location_code, dcc)
        return False

    with tempfile.TemporaryDirectory() as tmp:
        dest = os.path.join(tmp, f"{location_code}.nc")
        run_id = await onc_dataproduct.order_product(
            client, token,
            location_code=location_code,
            device_category_code=dcc,
            data_product_code=product,
            extension=onc_adcp_product.DATA_PRODUCT_EXT,
            date_from=date_from,
            date_to=date_to,
            extra={"dpo_ensemblePeriod": onc_adcp_product.ENSEMBLE_PERIOD_S},
        )
        await onc_dataproduct.wait_for_product(client, token, run_id)
        try:
            await onc_dataproduct.download_product(client, token, run_id, dest)
        except onc_dataproduct.NoProductFile:
            log.info("onc_adcp_strips[%s]: no data in the 24 h window", location_code)
            return False
        parsed = await asyncio.to_thread(onc_adcp_product.load_adcp_timeseries, dest)

    strip = parsed["strip"]
    if not strip or not strip[0]:
        log.info("onc_adcp_strips[%s]: product held no bins", location_code)
        return False

    async with db.pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO onc_adcp_strips
               (location_code, device_code, beam_count, bin_count,
                window_start, window_end, strip, depths, variable, units, updated_at)
               VALUES ($1, $2, NULL, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, NOW())
               ON CONFLICT (location_code, device_code) DO UPDATE
               SET beam_count=NULL, bin_count=EXCLUDED.bin_count,
                   window_start=EXCLUDED.window_start, window_end=EXCLUDED.window_end,
                   strip=EXCLUDED.strip, depths=EXCLUDED.depths,
                   variable=EXCLUDED.variable, units=EXCLUDED.units, updated_at=NOW()""",
            location_code, device_code,
            len(parsed["depths"]),
            window_start, window_end,
            # allow_nan=False: a NaN that slipped past the parser must fail here in
            # Python, not as an opaque asyncpg "Token \"NaN\" is invalid".
            json.dumps(strip, allow_nan=False),
            json.dumps(parsed["depths"], allow_nan=False),
            onc_adcp_product.BACKSCATTER_VAR,
            onc_adcp_product.BACKSCATTER_UNITS,
        )
    return True


async def sync_onc_adcp_strips() -> int:
    """Fetch 24 h of depth-binned mean backscatter for every ONC ADCP.

    Stores strip[timeIdx][binIdx] in dB alongside the bin depths in metres.
    Returns the number of (location, device) strips stored.
    """
    token = os.getenv("ONC_TOKEN")
    if not token:
        log.warning("sync_onc_adcp_strips: ONC_TOKEN not set — skipping")
        return 0

    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            # Match on "Doppler", never on "Current": the stored ADCP category reads
            # "Acoustic Doppler Current Profiler 75 kHz", so a '%CURRENT%' predicate
            # also sweeps in plain "Current Meter" devices, which have no depth bins.
            """SELECT DISTINCT ON (location_code) location_code, device_code, device_category
               FROM onc_instruments
               WHERE device_category ILIKE '%Doppler%'
                 AND location_code IS NOT NULL AND location_code <> ''"""
        )
    if not rows:
        log.info("onc_adcp_strips: no ADCP locations found")
        await _log_sync("onc-adcp", 0, 0)
        return 0

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=_ADCP_WINDOW_H)
    date_from = window_start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    date_to   = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    sem = asyncio.Semaphore(_ADCP_MAX_CONCURRENT)

    async def _one(row) -> bool:
        dcc = onc_dataproduct.adcp_device_category_code(row["device_category"])
        if dcc is None:
            log.warning("onc_adcp_strips[%s]: no deviceCategoryCode for %r",
                        row["location_code"], row["device_category"])
            return False
        async with sem:
            return await fetch_adcp_location(
                client, token, row["location_code"], row["device_code"], dcc,
                date_from, date_to, window_start, now,
            )

    # return_exceptions=True: a bare gather() re-raises the first exception while
    # leaving siblings running, and the `async with` then closes the client under
    # them — 1091 bogus "client has been closed" warnings, one real error buried.
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[_one(r) for r in rows], return_exceptions=True)

    inserted = 0
    failed = 0
    for row, res in zip(rows, results):
        if isinstance(res, BaseException):
            failed += 1
            log.warning("onc_adcp_strips[%s]: %r", row["location_code"], res)
        elif res:
            inserted += 1

    # Purge rows no longer in scope. Before the data-product rewrite this table also
    # held Current Meters (1 bin, instrument counts, no depth axis); the new sync
    # never revisits them, so without this they would sit here forever and render as
    # though they were dB backscatter.
    #
    # The primary key is (location_code, device_code), and a location can host BOTH —
    # SCVIP carries a Nortek Vector current meter *and* an RDI 150 kHz ADCP. Purging on
    # location_code alone leaves the stale current-meter row behind. Match the pair.
    # Guarded on inserted > 0 so a total ONC outage can never empty the table.
    if inserted:
        locs = [r["location_code"] for r in rows]
        devs = [r["device_code"] for r in rows]
        async with db.pool.acquire() as conn:
            removed = await conn.execute(
                """DELETE FROM onc_adcp_strips s
                   WHERE NOT EXISTS (
                       SELECT 1 FROM unnest($1::text[], $2::text[]) AS t(loc, dev)
                       WHERE t.loc = s.location_code AND t.dev = s.device_code
                   )""",
                locs, devs,
            )
        if removed and removed != "DELETE 0":
            log.info("onc_adcp_strips: purged out-of-scope rows (%s)", removed)

    global _onc_adcp_cache
    _onc_adcp_cache = {}
    await _log_sync("onc-adcp", inserted, inserted)
    log.info("onc_adcp_strips: %d strips stored, %d/%d locations failed",
             inserted, failed, len(rows))
    return inserted


# ── ONC CTD Profiles ──────────────────────────────────────────────────────────

_CTD_PROFILE_PROPERTIES = ["temperature", "salinity", "oxygen"]


async def sync_onc_ctd_profiles() -> int:
    """Fetch the latest CTD cast (pressure, temp, salinity, O2 vs depth) for each
    ONC location that has a CTD. Stores top 3 most recent casts.

    Returns total profile rows stored.
    """
    token = os.getenv("ONC_TOKEN")
    if not token:
        log.warning("sync_onc_ctd_profiles: ONC_TOKEN not set — skipping")
        return 0

    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT ON (location_code) location_code, device_code FROM onc_instruments "
            # ArcGIS WFS gives descriptive strings, not codes: 'Conductivity Temperature Depth' (56),
            # 'Integrated CTD pH O2 Instrument' (2). Older `= 'CTD'` matched 0 rows.
            "WHERE (device_category ILIKE '%CTD%' OR device_category ILIKE 'Conductivity%') "
            "  AND location_code IS NOT NULL AND location_code <> ''"
        )
    if not rows:
        await _log_sync("onc-ctd", 0, 0)  # visibility — empty-result early return was silent
        return 0

    now = datetime.now(timezone.utc)
    date_from = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    date_to   = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    sem = asyncio.Semaphore(8)
    inserted = 0

    async def _fetch_profile(client: httpx.AsyncClient, location_code: str, device_code: str):
        nonlocal inserted
        async with sem:
            # Fetch pressure as the depth proxy + temperature as scalar
            params_base = {
                "method":             "getByLocation",
                "locationCode":       location_code,
                "deviceCategoryCode": "CTD",
                "dateFrom":           date_from,
                "dateTo":             date_to,
                "token":              token,
            }
            try:
                r = await client.get(
                    f"{_ONC_API_BASE}/scalardata/location", params=params_base, timeout=30
                )
                if r.status_code != 200:
                    return
                # `.get("sensorData", [])` returns None if the key exists with a null value
                # (common when ONC has no data for the period); `or []` keeps iteration safe.
                sensor_data = r.json().get("sensorData") or []
                sensors: dict[str, list] = {}
                for sensor in sensor_data:
                    raw = sensor.get("sensorCode", "").lower()
                    friendly = _ONC_CODE_MAP.get(raw)
                    if friendly and friendly in ("temperature", "salinity", "pressure", "oxygen"):
                        vals  = sensor.get("data", {}).get("values", [])
                        times = sensor.get("data", {}).get("sampleTimes", [])
                        sensors[friendly] = {"values": vals, "times": times,
                                             "unit": sensor.get("unitOfMeasure", "")}

                if "pressure" not in sensors or "temperature" not in sensors:
                    return

                # Use pressure as depth proxy (1 dbar ≈ 1 m)
                depths = [float(v) for v in sensors["pressure"]["values"] if v is not None]
                if not depths:
                    return

                # Cast time = timestamp of first sample. asyncpg rejects ISO strings for
                # TIMESTAMPTZ — must pass a datetime object (same gotcha as USGS earthquakes).
                cast_time_raw = sensors["pressure"]["times"][0] if sensors["pressure"]["times"] else None
                if not cast_time_raw:
                    return
                cast_time = datetime.fromisoformat(cast_time_raw.replace("Z", "+00:00"))

                profile: dict[str, list] = {"depth": depths}
                for key in ("temperature", "salinity", "oxygen"):
                    if key in sensors:
                        profile[key] = [float(v) if v is not None else None
                                        for v in sensors[key]["values"]]

                async with db.pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO onc_ctd_profiles
                           (location_code, device_code, cast_time, profile, updated_at)
                           VALUES ($1, $2, $3, $4::jsonb, NOW())
                           ON CONFLICT (location_code, device_code, cast_time) DO NOTHING""",
                        location_code, device_code, cast_time, json.dumps(profile),
                    )
                    # Keep only the 3 most recent casts per (location, device)
                    await conn.execute(
                        """DELETE FROM onc_ctd_profiles
                           WHERE location_code = $1 AND device_code = $2
                             AND cast_time NOT IN (
                               SELECT cast_time FROM onc_ctd_profiles
                               WHERE location_code = $1 AND device_code = $2
                               ORDER BY cast_time DESC LIMIT 3
                             )""",
                        location_code, device_code,
                    )
                inserted += 1
            except Exception as exc:
                log.warning("onc_ctd_profiles[%s]: %s", location_code, exc)

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[_fetch_profile(client, r["location_code"], r["device_code"]) for r in rows])

    global _onc_ctd_cache
    _onc_ctd_cache = {}
    await _log_sync("onc-ctd", inserted, inserted)
    log.info("onc_ctd_profiles: %d profiles stored", inserted)
    return inserted


# ── USGS Earthquakes ──────────────────────────────────────────────────────────

async def sync_usgs_earthquakes() -> int:
    """Fetch global M≥3 earthquakes (last 30 days) from USGS FDSN and upsert.

    Returns total rows in table after upsert.
    """
    from ingestion.usgs_earthquakes import fetch_usgs_earthquakes
    events = await fetch_usgs_earthquakes(min_magnitude=3.0, lookback_days=30)
    if not events:
        return 0

    async with db.pool.acquire() as conn:
        await conn.executemany(
            """INSERT INTO usgs_earthquakes (usgs_id, occurred_at, magnitude, depth_km, place, geom)
               VALUES ($1, $2, $3, $4, $5,
                       ST_SetSRID(ST_MakePoint($7, $6), 4326)::geography)
               ON CONFLICT (usgs_id) DO UPDATE
               SET occurred_at=EXCLUDED.occurred_at, magnitude=EXCLUDED.magnitude,
                   depth_km=EXCLUDED.depth_km, place=EXCLUDED.place, geom=EXCLUDED.geom""",
            [(e["usgs_id"], e["occurred_at"], e["magnitude"], e["depth_km"],
              e["place"], e["lat"], e["lon"])
             for e in events],
        )
        # Prune events older than 35 days
        await conn.execute(
            "DELETE FROM usgs_earthquakes WHERE occurred_at < NOW() - INTERVAL '35 days'"
        )
        total = await conn.fetchval("SELECT COUNT(*) FROM usgs_earthquakes")

    global _usgs_eq_cache
    _usgs_eq_cache = {}
    await _log_sync("usgs-earthquakes", len(events), total)
    log.info("usgs_earthquakes: %d upserted, %d total", len(events), total)
    return total


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/v1/map/onc-instruments", dependencies=[Depends(get_api_key)])
async def get_onc_instruments():
    """Return ONC individual instrument deployments as GeoJSON point features."""
    global _onc_instruments_cache
    if _onc_instruments_cache:
        return Response(content=_onc_instruments_cache, media_type="application/json")
    sql = """
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geom)::json,
                    'properties', json_build_object(
                        'device_id',       device_id,
                        'device_code',     device_code,
                        'device_name',     device_name,
                        'device_category', device_category,
                        'location_code',   location_code,
                        'location_name',   location_name,
                        'site_name',       site_name,
                        'depth_m',         depth_m,
                        'image_url',       image_url,
                        'device_link',     device_link,
                        'location_link',   location_link,
                        'deployment_start', deployment_start,
                        'deployment_end',   deployment_end,
                        'status',          status,
                        'description',     description,
                        'data_products',   data_products,
                        'latest_readings', latest_readings,
                        'readings_at',     readings_at
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM onc_instruments
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql)
    result = row["geojson"] if isinstance(row["geojson"], str) else json.dumps(row["geojson"])
    _onc_instruments_cache = result
    return Response(content=result, media_type="application/json")


@router.get("/v1/map/onc", dependencies=[Depends(get_api_key)])
async def get_onc():
    """Return ONC observatory locations as GeoJSON FeatureCollection."""
    global _onc_cache
    if _onc_cache:
        return Response(content=_onc_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT l.location_code, l.name, l.lat, l.lon, l.depth_m, l.description,
                   l.latest_sensors, l.sensors_fetched_at,
                   COALESCE(i.categories, ARRAY[]::text[]) AS device_categories
            FROM onc_locations l
            LEFT JOIN LATERAL (
                SELECT array_agg(DISTINCT device_category) AS categories
                FROM onc_instruments
                WHERE location_code = l.location_code AND device_category IS NOT NULL
            ) i ON true
            WHERE l.latest_sensors IS NOT NULL
            ORDER BY l.location_code
        """)

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": {
                "location_code":     r["location_code"],
                "name":              r["name"],
                "depth_m":           r["depth_m"],
                "description":       r["description"],
                "lat":               r["lat"],
                "lon":               r["lon"],
                "latest_sensors":    json.loads(r["latest_sensors"]) if r["latest_sensors"] else None,
                "sensors_fetched_at": r["sensors_fetched_at"].isoformat() if r["sensors_fetched_at"] else None,
                "device_categories": list(r["device_categories"]) if r["device_categories"] else [],
            },
        }
        for r in rows
    ]
    result = json.dumps({"type": "FeatureCollection", "features": features})
    _onc_cache = result
    return Response(content=result, media_type="application/json")


_ONC_CODE_MAP: dict[str, str] = {
    "temp":        "temperature",
    "temperature": "temperature",
    "sal":         "salinity",
    "salinity":    "salinity",
    "pres":        "pressure",
    "pressure":    "pressure",
    "doxy":        "oxygen",
    "oxygen":      "oxygen",
    "o2":          "oxygen",
    "turb":        "turbidity",
    "turbidity":   "turbidity",
    "cdom":        "cdom",
    "par":         "par",
    "fluor":       "fluorescence",
    "chlorophyll": "chlorophyll",
    "cond":        "conductivity",
    "conductivity":"conductivity",
    "density":     "density",
    "sigmat":      "density",
    "sigma_theta": "density",
}

# Human-readable labels and units for display
_ONC_LABEL_MAP: dict[str, tuple[str, str]] = {
    "temperature": ("Temperature",  "°C"),
    "salinity":    ("Salinity",     "PSU"),
    "pressure":    ("Pressure",     "dbar"),
    "oxygen":      ("Oxygen",       "mL/L"),
    "turbidity":   ("Turbidity",    "NTU"),
    "cdom":        ("CDOM",         "ppb"),
    "par":          ("PAR",           "µmol/m²/s"),
    "fluorescence": ("Fluorescence",  "mg/m³"),
    "chlorophyll":  ("Chlorophyll",   "mg/m³"),
    "conductivity": ("Conductivity",  "S/m"),
    "density":      ("Density",       "kg/m³"),
}


_ONC_API_BASE = "https://data.oceannetworks.ca/api"
# Device categories tried in priority order — first with data wins
_ONC_DEVICE_CATEGORIES = ["CTD", "OXYSENSOR", "CURRENTMETER", "THERMISTOR"]


@router.get("/v1/live/onc/{location_code}", dependencies=[Depends(get_api_key)])
async def live_onc(location_code: str):
    """Fetch latest sensor data for an ONC location via Oceans 3.0 API.

    Tries CTD first, then other common sensor categories. Uses a 365-day
    lookback so recent-but-not-current deployments still surface data.
    """
    token = os.getenv("ONC_TOKEN")
    if not token:
        return {"available": False, "reason": "ONC_TOKEN not configured"}
    now = datetime.now(timezone.utc)
    date_from = (now - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    date_to   = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def _parse_sensors(payload: dict) -> dict:
        sensors: dict[str, dict] = {}
        for sensor in payload.get("sensorData", []):
            raw_code = sensor.get("sensorCode", "").lower()
            friendly = _ONC_CODE_MAP.get(raw_code)
            if not friendly:
                continue
            values = sensor.get("data", {}).get("values", [])
            times  = sensor.get("data", {}).get("sampleTimes", [])
            if values and values[-1] is not None:
                label, unit = _ONC_LABEL_MAP.get(friendly, (friendly, ""))
                sensors[friendly] = {
                    "value": values[-1],
                    "unit":  sensor.get("unitOfMeasure") or unit,
                    "label": label,
                    "time":  times[-1] if times else None,
                }
        return sensors

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            for category in _ONC_DEVICE_CATEGORIES:
                params = {
                    "method":             "getByLocation",
                    "locationCode":       location_code,
                    "deviceCategoryCode": category,
                    "dateFrom":           date_from,
                    "dateTo":             date_to,
                    "rowLimit":           1,
                    "token":              token,
                }
                r = await client.get(f"{_ONC_API_BASE}/scalardata/location", params=params)
                if r.status_code != 200:
                    continue
                sensors = _parse_sensors(r.json())
                if sensors:
                    return {"available": True, "sensors": sensors}
        return {"available": False}
    except Exception as exc:
        log.debug("ONC live fetch failed for %s: %s", location_code, exc)
        return {"available": False}


@router.get("/v1/onc/sparkline/{location_code}", dependencies=[Depends(get_api_key)])
async def get_onc_sparkline(location_code: str):
    """Return cached 72-hour sparkline time series for all sensors at an ONC location.

    Response: {property_code: {unit, samples: [[epoch_ms, value], ...]}, ...}
    """
    if location_code in _onc_sparkline_cache:
        return Response(content=_onc_sparkline_cache[location_code], media_type="application/json")
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT property_code, unit, samples FROM onc_sparklines WHERE location_code = $1",
            location_code,
        )
    if not rows:
        return Response(content="{}", media_type="application/json")
    result = {
        r["property_code"]: {
            "unit": r["unit"],
            "samples": json.loads(r["samples"]) if isinstance(r["samples"], str) else (r["samples"] or []),
        }
        for r in rows
    }
    payload = json.dumps(result)
    _onc_sparkline_cache[location_code] = payload
    return Response(content=payload, media_type="application/json")


@router.get("/v1/onc/adcp-strip/{location_code}", dependencies=[Depends(get_api_key)])
async def get_onc_adcp_strip(location_code: str):
    """Return the cached 24-hour ADCP mean-backscatter strip for an ONC location.

    Response: {device_code, bin_count, window_start, window_end, variable, units,
               depths: [m…], strip: [[dB|null …] …]}  — strip[timeIdx][binIdx],
    bins ordered shallow → deep, matching `depths`.
    """
    if location_code in _onc_adcp_cache:
        return Response(content=_onc_adcp_cache[location_code], media_type="application/json")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT device_code, bin_count, window_start, window_end,
                      strip, depths, variable, units
               FROM onc_adcp_strips WHERE location_code = $1""",
            location_code,
        )
    if not row:
        return Response(content="null", media_type="application/json")

    # asyncpg hands back JSONB as `str` (no type codec is registered). Passing it
    # straight to json.dumps yields a JSON-encoded *string*, so the client sees
    # "[[1,2]]" instead of [[1,2]] and `strip.map` throws. Same trap as
    # `_decode_offshore_row` in routers/spatial_v2.py.
    def _jsonb(v):
        return json.loads(v) if isinstance(v, str) else v

    result = {
        "device_code":  row["device_code"],
        "bin_count":    row["bin_count"],
        "window_start": row["window_start"].isoformat(),
        "window_end":   row["window_end"].isoformat(),
        "variable":     row["variable"],
        "units":        row["units"],
        "depths":       _jsonb(row["depths"]) or [],
        "strip":        _jsonb(row["strip"]) or [],
    }
    payload = json.dumps(result, default=str)
    _onc_adcp_cache[location_code] = payload
    return Response(content=payload, media_type="application/json")


@router.get("/v1/onc/ctd/{location_code}", dependencies=[Depends(get_api_key)])
async def get_onc_ctd(location_code: str):
    """Return latest CTD cast profile(s) for an ONC location.

    Response: [{device_code, cast_time, profile: {depth, temperature, salinity, oxygen}}, ...]
    """
    if location_code in _onc_ctd_cache:
        return Response(content=_onc_ctd_cache[location_code], media_type="application/json")
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT device_code, cast_time, profile
               FROM onc_ctd_profiles WHERE location_code = $1
               ORDER BY cast_time DESC LIMIT 3""",
            location_code,
        )
    result = [{"device_code": r["device_code"],
               "cast_time":   r["cast_time"].isoformat(),
               "profile":     r["profile"]} for r in rows]
    payload = json.dumps(result, default=str)
    _onc_ctd_cache[location_code] = payload
    return Response(content=payload, media_type="application/json")


@router.get("/v1/onc/earthquakes-near/{location_code}", dependencies=[Depends(get_api_key)])
async def get_earthquakes_near_onc(
    location_code: str,
    radius_km: float = Query(default=200.0, ge=10, le=1000),
    days: int = Query(default=30, ge=1, le=90),
):
    """Return USGS earthquakes near an ONC observatory within radius_km and last N days.

    Response: [{usgs_id, occurred_at, magnitude, depth_km, place, distance_km}, ...]
    """
    cache_key = f"{location_code}:{radius_km}:{days}"
    if cache_key in _usgs_eq_cache:
        return Response(content=_usgs_eq_cache[cache_key], media_type="application/json")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT geom FROM onc_locations WHERE location_code = $1", location_code
        )
        if not row:
            return Response(content="[]", media_type="application/json")
        rows = await conn.fetch(
            """SELECT usgs_id, occurred_at, magnitude, depth_km, place,
                      ROUND((ST_Distance(geom, $1::geometry::geography) / 1000)::numeric, 1)
                          AS distance_km
               FROM usgs_earthquakes
               WHERE ST_DWithin(geom, $1::geometry::geography, $2)
                 AND occurred_at >= NOW() - ($3 * INTERVAL '1 day')
               ORDER BY magnitude DESC
               LIMIT 50""",
            row["geom"], radius_km * 1000, days,
        )
    result = [{"usgs_id":    r["usgs_id"],
               "occurred_at": r["occurred_at"].isoformat(),
               "magnitude":  r["magnitude"],
               "depth_km":   r["depth_km"],
               "place":      r["place"],
               "distance_km": float(r["distance_km"])} for r in rows]
    payload = json.dumps(result, default=str)
    _usgs_eq_cache[cache_key] = payload
    return Response(content=payload, media_type="application/json")
