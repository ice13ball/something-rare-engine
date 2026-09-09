# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Sensors — Argo profiling floats and OceanSITES moorings: the two
autonomous in-situ ocean sensor networks the platform ingests directly (as
opposed to aggregated archives like WOD/PANGAEA). Argo: sync from ArgoVis,
per-platform float/trail caches, WOA climatology enrichment. OceanSITES:
mooring locations plus a two-stage observation pipeline (NDBC/PMEL/GDAC cached
in DB, and a separate live NDBC passthrough).

Moved verbatim out of backend/main.py (Task 2 of the backend vertical-split
refactor, Phase 3). Only permitted edits applied: `@app.get` -> `@router.get`,
`_pool.acquire()` -> `db.pool.acquire()`, leading underscore dropped from
every moved top-level function name (`_extract_argo_measurements` ->
`extract_argo_measurements`, `_woa_enrich` -> `woa_enrich`,
`_argo_row_to_float_props` -> `argo_row_to_float_props`,
`_argo_row_to_trail_props` -> `argo_row_to_trail_props`,
`_populate_argo_cache` -> `populate_argo_cache`, `_refresh_argo_platforms` ->
`refresh_argo_platforms`, `_build_argo_geojson` -> `build_argo_geojson`,
`_sync_argo_profiles` -> `sync_argo_profiles`, `_sync_oceansites` ->
`sync_oceansites`, `_sync_oceansites_obs` -> `sync_oceansites_obs`;
`get_argo`/`get_argo_trails`/`get_oceansites`/`live_oceansites` already had no
underscore — same rule seo.py/geochem.py established, not just the `sync_*`
ones), and imports/docstring. Module-level *constants* (non-callables) keep
their leading underscore, matching that precedent: `_ARGO_FLOAT_SQL`,
`_ARGO_TRAIL_SQL`, and the three cache globals.

## Two SQL constants the task brief's line-range table didn't name

`_ARGO_FLOAT_SQL`/`_ARGO_TRAIL_SQL` (main.py lines 686-723, between
`_argo_row_to_trail_props` and `_populate_argo_cache`) were not listed as
their own row in the brief's inventory table, but `populate_argo_cache`/
`refresh_argo_platforms` both `.format()` them directly — leaving them in
main.py would have forced this module to `import main`, exactly the
dependency-closure trap the brief's Task 1 postmortem calls out. Moved
verbatim in their original position, immediately before `populate_argo_cache`.

## Question 1 — `_woa_enrich` moved here in Task 2, moved onward to `woa_climatology.py` in Task 5

Task 2 (this module) moved `woa_enrich` out of main.py, reasoning that it was
"Argo's" because Argo was its only caller at the time. Task 5 (`domains/
fields/climatology.py`) surfaced that this was a symptom, not a fix: the
function is a ten-line pure wrapper over `services.woa_climatology.sample(...)`
with nothing Argo-specific beyond its return keys' `woa_*` naming, and
`/v1/woa/sample` (`main.py`'s `woa_sample` endpoint, moving into
`fields/climatology.py`) calls the exact same function. Leaving it here would
have forced a permanent `fields -> sensors` domain-to-domain import for one
endpoint. **Task 5 moved it again, this time to its true home: `services/
woa_climatology.py::enrich_profile`** — the WOA service module both remaining
callers (`sensors.sync_argo_profiles` here, and `fields.climatology.woa_sample`)
already import directly. This module's own call site was rewired:
`woa_enrich(...)` -> `woa_climatology.enrich_profile(...)`; the
`from services import woa_climatology` import stays (still needed for this
one call). No `sensors -> fields` edge was created or is needed.

`_backfill_woa_anomalies` (`main.py`) stayed in main.py through both moves —
it is a one-shot admin/startup-task helper (driven by `_woa_backfill_task`,
which is not in any task's move list) and costs nothing to leave there. Its
call was rewired again in Task 5: `sensors.woa_enrich(...)` ->
`woa_climatology.enrich_profile(...)` (its `await sensors.populate_argo_cache
(conn)` call, from Task 2, is unaffected).

## Question 2 — `live_oceansites` confirmed as the `/v1/live/...` route

Two OceanSITES-station-by-ref routes exist: `GET /v1/live/oceansites/{ref}`
(`live_oceansites`, main.py 5044-5119 — live NDBC passthrough, no DB, no
cache) and `GET /v1/seo/oceansites/{ref}` (`seo_oceansites`, moved to
`domains/seo.py` in Task 1 — bot-facing pre-rendered page data, reads
`oceansites_stations`). Verified by decorator string at the move site: this
module takes only the `/v1/live/...` one; `seo.py`'s `/v1/seo/...` route was
not touched.

## Caches — `_oceansites_cache` is newly swept here (a deliberate widening)

Three cache globals live in this module: `_argo_float_cache`/
`_argo_trail_cache` (per-platform dicts, keyed by `platform_id`) and
`_oceansites_cache` (single serialized GeoJSON string). Before this move,
`main.py`'s `admin_cache_clear()` hand-cleared only the two Argo dicts —
`_oceansites_cache` was never in that function's body (confirmed by grep
before this task started). This module's `clear_caches()` clears all three,
which **does** change `/admin/cache/clear`'s effective behaviour: it now also
drops `_oceansites_cache`. This is not an oversight — `backend/tests/
test_domain_cache_clear.py`'s `test_clear_caches_is_idempotent_and_empties_
module_caches` asserts every cache-shaped module global is falsy after
`clear_caches()` runs, so a domain module cannot declare a cache and leave it
out of its own sweep. It also matches the geochem.py precedent: that module's
three caches were "never among the hand-cleared lines in `admin_cache_clear`"
either, and all three still live in its `clear_caches()`. `_oceansites_cache`
self-heals within one sync cycle regardless (every write sets it to `None`),
so the practical effect is limited to `/admin/cache/clear` now also covering
one more (harmless) case than it used to.

## What did NOT move, and why

`ARGO_SYNC_INTERVAL_SECONDS` / `OCEANSITES_OBS_SYNC_INTERVAL_SECONDS` stay in
main.py — they configure `_argo_sync_task`/`_oceansites_obs_sync_task`, the
two background-loop wrappers the brief explicitly keeps in main.py (same
pattern Phase 2 used for bake tasks: startup orchestration stays centralized,
the sync body it calls does not). Both tasks were rewired to call
`sensors.sync_argo_profiles`/`sensors.sync_oceansites_obs` respectively.

`_sync_all_sources`, `_SYNC_SOURCES`, `_SOURCE_TO_ACTION`, `_startup_data_
check`, and the `_INVENTORY` tuple all reference `argo`/`oceansites` only as
table names or sync-log keys — never as function calls into the moved bodies
except where noted above (`_sync_all_sources`'s per-source loop and
`_SYNC_SOURCES`, both rewired to `sensors.*`). Nothing else needed a change.

`get_vent_mining_conflicts`, `get_plume_history`, and `correlate_plume` all
query the `argo_profiles` table directly in raw SQL (near-mining Argo floats
feed vent risk scoring and plume back-tracking) but never call any function
this module owns — confirmed by grep before editing. Left exactly where they
are, per the brief's "different families entirely" list.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone

import db
import httpx
from auth import get_api_key, require_admin_token
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from indexnow import notify_indexnow as _notify_indexnow
from indexnow import SITE_HOST
from services import woa_climatology
from sync_log import log_sync as _log_sync

log = logging.getLogger(__name__)
router = APIRouter()

# ── Caches ──────────────────────────────────────────────────────────────────
# Per-float Argo caches — keyed by platform_id so sync only invalidates affected floats
_argo_float_cache: dict[str, dict] = {}   # platform_id → latest-profile feature properties
_argo_trail_cache: dict[str, list] = {}   # platform_id → list of trail feature properties
_oceansites_cache: str | None = None


def clear_caches() -> None:
    """Drop this domain's cached responses. Called by /admin/cache/clear.

    See module docstring "Caches" section — `_oceansites_cache` is swept here
    even though the pre-move `admin_cache_clear()` never hand-cleared it.
    """
    global _oceansites_cache
    _argo_float_cache.clear()
    _argo_trail_cache.clear()
    _oceansites_cache = None


def extract_argo_measurements(profile: dict) -> dict:
    """Parse a single ArgoVis profile into flat measurement values.

    ArgoVis data is column-major: data[i] holds all depth-level values for
    variable i (as listed in data_info[0]). Each variable column has the same
    length — one entry per depth level.
    """
    data_info = profile.get("data_info") or []
    var_names: list[str] = data_info[0] if data_info else []
    data_cols: list[list] = profile.get("data") or []

    def col(name: str) -> list | None:
        i = var_names.index(name) if name in var_names else None
        return data_cols[i] if i is not None and i < len(data_cols) else None

    temps     = col("temperature")
    sals      = col("salinity")
    pressures = col("pressure")
    o2s       = col("doxy")
    phs       = col("ph_in_situ_total")
    temps_qc  = col("temperature_argoqc")
    sals_qc   = col("salinity_argoqc")
    o2s_qc    = col("doxy_argoqc")
    phs_qc    = col("ph_in_situ_total_argoqc")

    def _qc_at(flags: list | None, idx: int) -> int | None:
        if not flags or idx >= len(flags):
            return None
        v = flags[idx]
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    surface_temp = surface_sal = deep_temp = deep_sal = deep_press = None
    oxygen = ph = max_depth = None
    temp_qc = sal_qc = oxygen_qc = ph_qc = None

    if pressures:
        n = len(pressures)
        valid_pressures = [p for p in pressures if p is not None]
        if valid_pressures:
            max_depth = max(valid_pressures)

        # Surface: shallowest level at or above 50 dbar
        for j in range(n):
            if pressures[j] is not None and pressures[j] <= 50:
                if surface_temp is None and temps and temps[j] is not None:
                    surface_temp = temps[j]
                if surface_sal is None and sals and sals[j] is not None:
                    surface_sal = sals[j]

        # Deep: deepest level with a valid pressure reading
        for j in range(n - 1, -1, -1):
            if pressures[j] is not None:
                deep_press = pressures[j]
                deep_temp  = temps[j]  if temps else None
                deep_sal   = sals[j]   if sals  else None
                temp_qc    = _qc_at(temps_qc, j)
                sal_qc     = _qc_at(sals_qc,  j)
                break

        # O2 and pH: deepest valid value — capture paired QC flag
        if o2s:
            for j in range(n - 1, -1, -1):
                if o2s[j] is not None:
                    oxygen = o2s[j]; oxygen_qc = _qc_at(o2s_qc, j); break
        if phs:
            for j in range(n - 1, -1, -1):
                if phs[j] is not None:
                    ph = phs[j]; ph_qc = _qc_at(phs_qc, j); break

    return dict(
        surface_temp=surface_temp, surface_sal=surface_sal,
        deep_temp=deep_temp, deep_sal=deep_sal, deep_press=deep_press,
        oxygen=oxygen, ph=ph, max_depth=max_depth,
        temp_qc=temp_qc, sal_qc=sal_qc, oxygen_qc=oxygen_qc, ph_qc=ph_qc,
    )


def argo_row_to_float_props(row) -> dict:
    return {
        "profile_id":            row["profile_id"],
        "platform_id":           row["platform_id"],
        "profile_date":          row["profile_date"],
        "max_depth_m":           row["max_depth_m"],
        "surface_temp_c":        row["surface_temp_c"],
        "surface_salinity":      row["surface_salinity"],
        "deep_temp_c":           row["deep_temp_c"],
        "deep_salinity":         row["deep_salinity"],
        "deep_pressure_m":       row["deep_pressure_m"],
        "oxygen_umol_kg":        row["oxygen_umol_kg"],
        "ph":                    row["ph"],
        "temp_qc":               row["temp_qc"],
        "sal_qc":                row["sal_qc"],
        "oxygen_qc":             row["oxygen_qc"],
        "ph_qc":                 row["ph_qc"],
        "woa_surface_temp_c":    row["woa_surface_temp_c"],
        "woa_surface_sal":       row["woa_surface_sal"],
        "woa_deep_temp_c":       row["woa_deep_temp_c"],
        "woa_deep_sal":          row["woa_deep_sal"],
        "woa_deep_oxygen_umol_kg": row["woa_deep_oxygen_umol_kg"],
        "woa_deep_aou":          row["woa_deep_aou"],
        "woa_deep_o2sat":        row["woa_deep_o2sat"],
        "woa_deep_phosphate":    row["woa_deep_phosphate"],
        "woa_deep_silicate":     row["woa_deep_silicate"],
        "woa_deep_nitrate":      row["woa_deep_nitrate"],
        "near_mining":           row["near_mining"],
        "mining_zone":           row["mining_zone"],
        "mining_dist_km":        row["mining_dist_km"],
        "nearest_contract_lon":  row["nearest_contract_lon"],
        "nearest_contract_lat":  row["nearest_contract_lat"],
        "mining_zones":          json.loads(row["mining_zones"]) if row["mining_zones"] else [],
        "_geojson":              row["geojson"],
    }


def argo_row_to_trail_props(row) -> dict:
    return {
        "profile_id":       row["profile_id"],
        "platform_id":      row["platform_id"],
        "profile_date":     row["profile_date"],
        "near_mining":      row["near_mining"],
        "mining_zone":      row["mining_zone"],
        "mining_dist_km":   row["mining_dist_km"],
        "max_depth_m":      row["max_depth_m"],
        "surface_temp_c":   row["surface_temp_c"],
        "surface_salinity": row["surface_salinity"],
        "deep_temp_c":      row["deep_temp_c"],
        "deep_salinity":    row["deep_salinity"],
        "deep_pressure_m":  row["deep_pressure_m"],
        "oxygen_umol_kg":   row["oxygen_umol_kg"],
        "ph":               row["ph"],
        "temp_qc":          row["temp_qc"],
        "sal_qc":           row["sal_qc"],
        "oxygen_qc":        row["oxygen_qc"],
        "ph_qc":            row["ph_qc"],
        "woa_surface_temp_c":      row["woa_surface_temp_c"],
        "woa_surface_sal":         row["woa_surface_sal"],
        "woa_deep_temp_c":         row["woa_deep_temp_c"],
        "woa_deep_sal":            row["woa_deep_sal"],
        "woa_deep_oxygen_umol_kg": row["woa_deep_oxygen_umol_kg"],
        "woa_deep_aou":            row["woa_deep_aou"],
        "woa_deep_o2sat":          row["woa_deep_o2sat"],
        "woa_deep_phosphate":      row["woa_deep_phosphate"],
        "woa_deep_silicate":       row["woa_deep_silicate"],
        "woa_deep_nitrate":        row["woa_deep_nitrate"],
        "_geojson":         row["geojson"],
    }


_ARGO_FLOAT_SQL = """
    SELECT DISTINCT ON (platform_id)
        profile_id, platform_id,
        to_char(profile_date, 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS profile_date,
        max_depth_m, surface_temp_c, surface_salinity,
        deep_temp_c, deep_salinity, deep_pressure_m,
       -- Argo QC: 1 good, 2 probably good, 3 probably bad, 4 bad, 8 interpolated,
       -- 9 missing. A reading the source flagged bad is not a measurement, so it
       -- is served as NULL rather than filtered out of the row - the profile's
       -- position and date are still real. A NULL flag means the source's
       -- assessment was never recorded (profiles predating the QC request fix);
       -- those are withheld too, because we cannot assert what we never asked for.
       CASE WHEN oxygen_qc IS NOT NULL AND oxygen_qc NOT IN (3, 4, 9)
            THEN oxygen_umol_kg END AS oxygen_umol_kg,
       CASE WHEN ph_qc IS NOT NULL AND ph_qc NOT IN (3, 4, 9)
            THEN ph END AS ph,
        temp_qc, sal_qc, oxygen_qc, ph_qc,
        woa_surface_temp_c, woa_surface_sal,
        woa_deep_temp_c, woa_deep_sal, woa_deep_oxygen_umol_kg,
        woa_deep_aou, woa_deep_o2sat,
        woa_deep_phosphate, woa_deep_silicate, woa_deep_nitrate,
        near_mining, mining_zone,
        mining_dist_km, nearest_contract_lon, nearest_contract_lat,
        COALESCE(mining_zones::text, '[]') AS mining_zones,
        ST_AsGeoJSON(geom) AS geojson
    FROM argo_profiles
    {where}
    ORDER BY platform_id, profile_date DESC
"""

_ARGO_TRAIL_SQL = """
    SELECT profile_id, platform_id,
        to_char(profile_date, 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS profile_date,
        near_mining, mining_zone, mining_dist_km,
        max_depth_m, surface_temp_c, surface_salinity,
        deep_temp_c, deep_salinity, deep_pressure_m,
       -- Argo QC: 1 good, 2 probably good, 3 probably bad, 4 bad, 8 interpolated,
       -- 9 missing. A reading the source flagged bad is not a measurement, so it
       -- is served as NULL rather than filtered out of the row - the profile's
       -- position and date are still real. A NULL flag means the source's
       -- assessment was never recorded (profiles predating the QC request fix);
       -- those are withheld too, because we cannot assert what we never asked for.
       CASE WHEN oxygen_qc IS NOT NULL AND oxygen_qc NOT IN (3, 4, 9)
            THEN oxygen_umol_kg END AS oxygen_umol_kg,
       CASE WHEN ph_qc IS NOT NULL AND ph_qc NOT IN (3, 4, 9)
            THEN ph END AS ph,
        temp_qc, sal_qc, oxygen_qc, ph_qc,
        woa_surface_temp_c, woa_surface_sal,
        woa_deep_temp_c, woa_deep_sal, woa_deep_oxygen_umol_kg,
        woa_deep_aou, woa_deep_o2sat,
        woa_deep_phosphate, woa_deep_silicate, woa_deep_nitrate,
        ST_AsGeoJSON(geom) AS geojson
    FROM argo_profiles
    {where}
    ORDER BY platform_id, profile_date ASC
"""



# argo_profiles no longer has a rolling-window DELETE (2026-09-09 — history is
# the point; see sync_argo_profiles_backfill). The float/trail *caches* still
# have to be bounded, though: DISTINCT ON(platform_id) over full history is
# fine (one row per float, ever), but the trail cache is one row PER PROFILE,
# and at ~3.3M rows total that blows straight through Cloud Run's 32 MiB
# response cap at the proxy — a 200 in the service log, a 500 in the browser.
# Bounding both to a recent window keeps `/v1/map/argo` and
# `/v1/map/argo/trails` answering "current state of the ocean" (which is what
# a live map wants) instead of silently trying to serve the whole archive.
_ARGO_CACHE_WINDOW_DAYS = 90


async def populate_argo_cache(conn) -> None:
    """Cold-start: load recent floats into per-platform dicts.

    Bounded to `_ARGO_CACHE_WINDOW_DAYS` — see the module note above the
    constant for why an unbounded cache is not an option now that history
    persists indefinitely."""
    where = f"WHERE profile_date > NOW() - INTERVAL '{_ARGO_CACHE_WINDOW_DAYS} days'"
    float_rows  = await conn.fetch(_ARGO_FLOAT_SQL.format(where=where))
    trail_rows  = await conn.fetch(_ARGO_TRAIL_SQL.format(where=where))
    _argo_float_cache.clear()
    _argo_trail_cache.clear()
    for row in float_rows:
        _argo_float_cache[row["platform_id"]] = argo_row_to_float_props(row)
    for row in trail_rows:
        pid = row["platform_id"]
        _argo_trail_cache.setdefault(pid, []).append(argo_row_to_trail_props(row))


async def refresh_argo_platforms(conn, platform_ids: set[str]) -> None:
    """After a sync, update only the floats that received new profiles."""
    if not platform_ids:
        return
    pid_list = list(platform_ids)
    # ⛔ The SAME window populate_argo_cache uses. Without it this path was the
    # hole in the bound: populate_argo_cache runs once, on the first sync, and
    # every later sync comes through here — so a float's ENTIRE lifetime trail
    # was re-loaded into the in-memory cache each time it surfaced. Harmless
    # while the table held 2,303 rows and 180 days; with global history at
    # ~3.3 M profiles across thousands of floats it walks straight back to the
    # 32 MiB Cloud Run proxy ceiling this windowing exists to avoid — and it
    # does it in RAM first, where nothing reports it.
    _window = f"AND profile_date > NOW() - INTERVAL '{_ARGO_CACHE_WINDOW_DAYS} days'"
    float_rows = await conn.fetch(
        _ARGO_FLOAT_SQL.format(where=f"WHERE platform_id = ANY($1::text[]) {_window}"),
        pid_list,
    )
    trail_rows = await conn.fetch(
        _ARGO_TRAIL_SQL.format(where=f"WHERE platform_id = ANY($1::text[]) {_window}"),
        pid_list,
    )
    for row in float_rows:
        _argo_float_cache[row["platform_id"]] = argo_row_to_float_props(row)
    # Replace trail entries for affected platforms
    for pid in platform_ids:
        _argo_trail_cache.pop(pid, None)
    for row in trail_rows:
        pid = row["platform_id"]
        _argo_trail_cache.setdefault(pid, []).append(argo_row_to_trail_props(row))


def build_argo_geojson(float_props: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": json.loads(float_props["_geojson"]),
        "properties": {k: v for k, v in float_props.items() if k != "_geojson"},
    }


_ARGO_API = "https://argovis-api.colorado.edu/argo"

# Recent-window for the *periodic* sync. Argo floats profile roughly every
# 10 days, so 30 days comfortably covers 2-3 cycles per float even allowing
# for ArgoVis's own ingest lag — wide enough that a float that missed one
# sync still gets picked up by the next, without re-walking full history on
# every 12h run (that job is sync_argo_profiles_backfill, below).
_ARGO_RECENT_WINDOW_DAYS = 30

_argo_param_vocab_cache: list[str] | None = None


async def _fetch_argo_param_vocabulary(client: httpx.AsyncClient) -> list[str]:
    """The full list of `data` names ArgoVis currently offers (base
    variables and their `*_argoqc` companions alike) — fetched once per
    process and cached, since the vocabulary changes rarely and every sync
    would otherwise pay for it twice."""
    global _argo_param_vocab_cache
    if _argo_param_vocab_cache is not None:
        return _argo_param_vocab_cache
    r = await client.get(f"{_ARGO_API}/vocabulary", params={"parameter": "data"})
    r.raise_for_status()
    _argo_param_vocab_cache = list(r.json())
    return _argo_param_vocab_cache


async def _fetch_argo_window(
    client: httpx.AsyncClient, start: datetime, end: datetime, params: list[str]
) -> list[dict]:
    """One global (no polygon — Truncation (a) removed) ArgoVis query for
    [start, end). Raises on transport/HTTP failure so the caller can treat
    the whole run as failed rather than silently partial."""
    r = await client.get(
        _ARGO_API,
        params={
            "startDate": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endDate":   end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            # ⛔ `data` IS A FILTER, NOT A COLUMN SELECTION. Naming parameters
            # returns only profiles carrying ALL of them. Measured against the
            # live API on 2026-09-09, one day of global profiles:
            #     no `data` at all ................. 464 profiles
            #     data=all ......................... 464 profiles
            #     data=temperature ................. 460
            #     data=temperature,salinity ........ 426
            #     the five this ingest used to ask . 36   ← 7.8 %
            # So the old five-parameter request was a fifth, unnoticed
            # truncation on top of the four we knew about: it silently kept
            # only floats carrying oxygen AND pH AND the rest. It is why all
            # 2,303 rows in production had both oxygen and pH — 100 %, which no
            # real fleet looks like.
            # ⚠️ Enumerating the whole vocabulary is WORSE, not better: it means
            # "carrying every parameter that exists", which matches nothing —
            # the live API answers HTTP 400 or an empty 404.
            # `all` is the documented way to say "every measurement, whatever
            # this float carries": same 464 profiles, 42 distinct parameters
            # returned, 15.9 MB for one global day.
            "data": "all",
        },
    )
    r.raise_for_status()
    seen: set[str] = set()
    profiles: list[dict] = []
    for p in r.json():
        if p["_id"] not in seen:
            seen.add(p["_id"])
            profiles.append(p)
    return profiles


def extract_argo_long_form(profile: dict, base_params: list[str]) -> list[dict]:
    """Long-form surface/deep values for every requested parameter, for
    `argo_profile_values`.

    Uses the exact same level selection `extract_argo_measurements` uses —
    surface = shallowest level at or above 50 dbar, deep = the deepest level
    with a valid pressure reading. That selection is Michal's decision to
    keep (2026-09-09); only parameter breadth changed here, not depth
    resolution.

    ArgoVis is column-major: data[i] is every depth level for the variable
    named at data_info[0][i]. Each parameter's own column is looked up and
    indexed independently below — never index one variable's column with
    another variable's offset, and never assume two columns share a length
    (the WOD-oxygen ragged-array trap this repo has already paid for once).
    """
    data_info = profile.get("data_info") or []
    var_names: list[str] = data_info[0] if data_info else []
    data_cols: list[list] = profile.get("data") or []

    def col(name: str) -> list | None:
        i = var_names.index(name) if name in var_names else None
        return data_cols[i] if i is not None and i < len(data_cols) else None

    pressures = col("pressure")
    if not pressures:
        return []
    n = len(pressures)
    surface_idx = next(
        (j for j in range(n) if pressures[j] is not None and pressures[j] <= 50), None
    )
    deep_idx = next(
        (j for j in range(n - 1, -1, -1) if pressures[j] is not None), None
    )
    if surface_idx is None and deep_idx is None:
        return []

    rows: list[dict] = []
    # ⭐ Iterate what THIS PROFILE actually carries, not a vocabulary list.
    # With `data=all` the response names its own variables in data_info[0], so
    # the profile is the authority on its own contents. Walking a fetched
    # vocabulary instead would silently skip any parameter a float reports that
    # the vocabulary endpoint has not caught up with — the same "we only see
    # what we thought to ask for" failure that hid ONC's oxygen for months.
    # `base_params` is kept only as a caller-supplied restriction for tests.
    names = list(var_names) if not base_params else [
        n for n in var_names if n in set(base_params)
    ]
    for param in names:
        if param == "pressure" or param.endswith("_argoqc"):
            continue
        values = col(param)
        if not values:
            continue  # this profile doesn't carry this parameter — no row, not a 0
        qc_values = col(f"{param}_argoqc")
        for level, idx in (("surface", surface_idx), ("deep", deep_idx)):
            if idx is None or idx >= len(values):
                continue
            v = values[idx]
            if v is None:
                continue
            qc = None
            if qc_values is not None and idx < len(qc_values) and qc_values[idx] is not None:
                try:
                    qc = int(qc_values[idx])
                except (TypeError, ValueError):
                    qc = None
            rows.append({"level": level, "param": param, "value": float(v), "qc": qc})
    return rows


async def _upsert_argo_profiles(profiles: list[dict], params: list[str]) -> tuple[int, set[str]]:
    """Shared insert path for both the periodic sync and the backfill:
    legacy argo_profiles row (5-column surface/deep summary, unchanged),
    long-form argo_profile_values rows (upsert, not blind insert — a re-run
    of the same chunk must not duplicate), then near_mining/mining_zone
    enrichment scoped to only the profile_ids touched THIS call. Scoping the
    enrichment queries this way (rather than the old `WHERE near_mining =
    FALSE` / `WHERE near_mining = TRUE` full-table predicates) is what keeps
    them bounded now that argo_profiles can hold the full ~3.3M-row history:
    an UPDATE that scans the whole table on every run is not bounded, one
    that touches only the rows just written is."""
    inserted = 0
    touched_ids: list[str] = []
    new_platform_ids: set[str] = set()
    async with db.pool.acquire() as conn:
        for profile in profiles:
            geo = (profile.get("geolocation") or {}).get("coordinates") or []
            if len(geo) < 2:
                continue
            lon, lat = geo[0], geo[1]
            ts = profile.get("timestamp")
            if not ts:
                continue
            profile_date = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            m = extract_argo_measurements(profile)
            # Skip profiles with no temperature data at all
            if m["surface_temp"] is None and m["deep_temp"] is None:
                continue
            profile_id = profile["_id"]
            platform_id = profile_id.split("_")[0]
            w = await asyncio.to_thread(
                woa_climatology.enrich_profile, float(lat), float(lon), profile_date.month,
                0.0, m["deep_press"],
            )
            result = await conn.execute(
                """INSERT INTO argo_profiles
                       (profile_id, platform_id, profile_date, max_depth_m,
                        surface_temp_c, surface_salinity,
                        deep_temp_c, deep_salinity, deep_pressure_m,
                        oxygen_umol_kg, ph,
                        temp_qc, sal_qc, oxygen_qc, ph_qc,
                        woa_surface_temp_c, woa_surface_sal,
                        woa_deep_temp_c, woa_deep_sal, woa_deep_oxygen_umol_kg,
                        woa_deep_aou, woa_deep_o2sat,
                        woa_deep_phosphate, woa_deep_silicate, woa_deep_nitrate,
                        geom)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,
                           $12,$13,$14,$15,
                           $16,$17,$18,$19,$20,$21,$22,$23,$24,$25,
                           ST_SetSRID(ST_MakePoint($26,$27),4326))
                   ON CONFLICT (profile_id) DO NOTHING""",
                profile_id, platform_id, profile_date, m["max_depth"],
                m["surface_temp"], m["surface_sal"],
                m["deep_temp"], m["deep_sal"], m["deep_press"],
                m["oxygen"], m["ph"],
                m["temp_qc"], m["sal_qc"], m["oxygen_qc"], m["ph_qc"],
                w["woa_surface_temp_c"], w["woa_surface_sal"],
                w["woa_deep_temp_c"], w["woa_deep_sal"], w["woa_deep_oxygen_umol_kg"],
                w["woa_deep_aou"], w["woa_deep_o2sat"],
                w["woa_deep_phosphate"], w["woa_deep_silicate"], w["woa_deep_nitrate"],
                float(lon), float(lat),
            )
            touched_ids.append(profile_id)
            if result == "INSERT 0 1":
                inserted += 1
                new_platform_ids.add(platform_id)

            long_rows = extract_argo_long_form(profile, params)
            if long_rows:
                await conn.executemany(
                    """INSERT INTO argo_profile_values (profile_id, level, param, value, qc)
                       VALUES ($1,$2,$3,$4,$5)
                       ON CONFLICT (profile_id, level, param) DO UPDATE
                       SET value = EXCLUDED.value, qc = EXCLUDED.qc""",
                    [(profile_id, r["level"], r["param"], r["value"], r["qc"]) for r in long_rows],
                )

        if touched_ids:
            # Cap spatial enrichment at 30 min — prevents runaway queries
            # that hold locks and block startup DDL on mining_contracts
            await conn.execute("SET statement_timeout = '30min'")

            # Step 1: mark newly-qualifying touched floats as near_mining
            await conn.execute(
                """
                UPDATE argo_profiles a
                SET near_mining = TRUE
                WHERE near_mining = FALSE
                  AND a.profile_id = ANY($1::text[])
                  AND EXISTS (
                      SELECT 1 FROM mining_contracts mc
                      WHERE ST_DWithin(a.geom::geography, mc.geom::geography, 200000)
                  )
                """,
                touched_ids,
            )

            # Step 2: refresh nearest zone + all zones for touched near-mining floats
            await conn.execute(
                """
                UPDATE argo_profiles a
                SET
                    mining_zone          = sub.contractor_name,
                    mining_dist_km       = ROUND((sub.d / 1000)::numeric, 1),
                    nearest_contract_lon = ST_X(ST_ClosestPoint(sub.geom, a.geom)),
                    nearest_contract_lat = ST_Y(ST_ClosestPoint(sub.geom, a.geom))
                FROM (
                    SELECT
                        ap.profile_id,
                        mc.contractor_name,
                        mc.geom,
                        ST_Distance(ap.geom::geography, mc.geom::geography) AS d
                    FROM argo_profiles ap
                    JOIN LATERAL (
                        SELECT mc2.contractor_name, mc2.geom,
                               ST_Distance(ap.geom::geography, mc2.geom::geography) AS dd
                        FROM   mining_contracts mc2
                        WHERE  ST_DWithin(ap.geom::geography, mc2.geom::geography, 200000)
                        ORDER  BY dd
                        LIMIT  1
                    ) mc ON TRUE
                    WHERE ap.near_mining = TRUE AND ap.profile_id = ANY($1::text[])
                ) sub
                WHERE a.profile_id = sub.profile_id
                """,
                touched_ids,
            )

            # Step 3: refresh mining_zones for touched near-mining floats
            await conn.execute(
                """
                UPDATE argo_profiles a
                SET mining_zones = sub.zones
                FROM (
                    SELECT ap.profile_id,
                           JSONB_AGG(
                               JSONB_BUILD_OBJECT(
                                   'name',    closest.contractor_name,
                                   'dist_km', closest.dist_km,
                                   'lon',     closest.lon,
                                   'lat',     closest.lat
                               ) ORDER BY closest.dist_km
                           ) AS zones
                    FROM argo_profiles ap
                    JOIN LATERAL (
                        SELECT
                            mc.contractor_name,
                            ROUND((MIN(ST_Distance(ap.geom::geography, mc.geom::geography))/1000)::numeric, 1) AS dist_km,
                            (SELECT ST_X(ST_ClosestPoint(mc2.geom, ap.geom))
                             FROM mining_contracts mc2
                             WHERE mc2.contractor_name = mc.contractor_name
                               AND ST_DWithin(ap.geom::geography, mc2.geom::geography, 200000)
                             ORDER BY ST_Distance(ap.geom::geography, mc2.geom::geography) LIMIT 1) AS lon,
                            (SELECT ST_Y(ST_ClosestPoint(mc2.geom, ap.geom))
                             FROM mining_contracts mc2
                             WHERE mc2.contractor_name = mc.contractor_name
                               AND ST_DWithin(ap.geom::geography, mc2.geom::geography, 200000)
                             ORDER BY ST_Distance(ap.geom::geography, mc2.geom::geography) LIMIT 1) AS lat
                        FROM mining_contracts mc
                        WHERE ST_DWithin(ap.geom::geography, mc.geom::geography, 200000)
                        GROUP BY mc.contractor_name
                    ) closest ON TRUE
                    WHERE ap.near_mining = TRUE AND ap.profile_id = ANY($1::text[])
                    GROUP BY ap.profile_id
                ) sub
                WHERE a.profile_id = sub.profile_id
                """,
                touched_ids,
            )
            await conn.execute("SET statement_timeout = '0'")  # reset for normal queries
    return inserted, new_platform_ids


async def sync_argo_profiles() -> int:
    """Periodic Argo sync: global coverage (no ISA-zone polygon filter —
    Truncation (a) removed), a recent time window only (Truncation (b)'s
    destructive DELETE removed entirely — see sync_argo_profiles_backfill
    for how full history gets filled in instead), and every parameter
    ArgoVis's vocabulary currently offers (Truncation (c) removed). The
    fourth truncation — reducing each profile to a surface and a deep
    sample — stays, by Michal's 2026-09-09 decision; see
    extract_argo_measurements / extract_argo_long_form.
    """
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=_ARGO_RECENT_WINDOW_DAYS)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            params = await _fetch_argo_param_vocabulary(client)
            profiles = await _fetch_argo_window(client, start, end, params)
    except httpx.HTTPError as e:
        # FAILED sync — do not call _log_sync, so last_synced_at is not
        # stamped and the monitor can tell "ran, found nothing" (which DOES
        # call _log_sync, below) apart from "never ran / failed".
        log.error("argo_profiles: ArgoVis fetch failed, sync aborted: %s", type(e).__name__)
        return 0

    inserted, new_platform_ids = await _upsert_argo_profiles(profiles, params)

    async with db.pool.acquire() as conn:
        total      = await conn.fetchval("SELECT COUNT(*) FROM argo_profiles")
        near_count = await conn.fetchval("SELECT COUNT(*) FROM argo_profiles WHERE near_mining")
        # Refresh only the floats that received new profiles; cold-start if cache is empty
        if _argo_float_cache:
            await refresh_argo_platforms(conn, new_platform_ids)
        else:
            await populate_argo_cache(conn)
    await _log_sync("argo_profiles", inserted, total)
    log.info(
        "argo_profiles: %d new / %d total (%d near mining zones) — %d parameter(s) requested, cache updated for %d floats",
        inserted, total, near_count, len(params), len(new_platform_ids),
    )
    return inserted


# ── Resumable full-history backfill ─────────────────────────────────────────
# sync_argo_profiles above only ever refreshes the last _ARGO_RECENT_WINDOW_DAYS.
# Filling in the rest of Argo's ~3.3M-profile history is a separate,
# admin-triggered job, chunked by calendar MONTH, with its cursor persisted in
# argo_backfill_state.done_through — safe to stop and restart at any point,
# and a restart re-processes (upserts, never duplicates) rather than skips.
#
# Pacing: one ArgoVis request per month-chunk plus a 2s sleep between chunks.
# ArgoVis documents no rate limit, but this job has no natural pause point of
# its own (unlike the periodic sync, which only runs every 12h) — 2s keeps it
# polite without materially slowing down completion.
#
# Wall-clock budget: 20 minutes (1200s) per invocation, chosen because Argo's
# ~27-year history at one month per chunk is ~330 chunks — multiple
# invocations are required regardless of budget, so the number only has to be
# comfortably short of any HTTP/proxy timeout an admin caller might have
# (well under Cloud Run's 60-minute ceiling) while still making many months
# of progress per call. Re-invoke (e.g. via a cron hitting the admin
# endpoint) until `done_through` reaches today.
ARGO_BACKFILL_START = date(1999, 1, 1)  # Argo programme's earliest profiles
ARGO_BACKFILL_DEFAULT_BUDGET_SECONDS = 1200
_ARGO_BACKFILL_CHUNK_PACING_SECONDS = 5
# ArgoVis answers 429 with no Retry-After. Measured 2026-09-09: a ~20s pause
# cleared it, so start there and double. ⛔ These retries are what stop a
# rate-limited run from looking like a permanent chunk failure.
_ARGO_429_BASE_WAIT_SECONDS = 20.0
_ARGO_429_MAX_WAIT_SECONDS = 300.0
_ARGO_429_MAX_ATTEMPTS = 5


def _next_month_start(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


async def sync_argo_profiles_backfill(budget_seconds: int = ARGO_BACKFILL_DEFAULT_BUDGET_SECONDS) -> dict:
    """Resumable, chunked-by-month walk over full Argo history. See the
    module note above ARGO_BACKFILL_START for pacing/budget/resumability."""
    started = time.monotonic()
    months_done = 0
    total_inserted = 0
    rate_limited_waits = 0
    failed_chunk: str | None = None

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT done_through FROM argo_backfill_state WHERE id = 1")
    cursor: date = row["done_through"] if row and row["done_through"] else ARGO_BACKFILL_START
    today = datetime.now(timezone.utc).date()

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            params = await _fetch_argo_param_vocabulary(client)
        except httpx.HTTPError as e:
            log.error("argo backfill: vocabulary fetch failed, no chunk attempted: %s", type(e).__name__)
            return {
                "months_done": 0, "inserted": 0,
                "done_through": cursor.isoformat(), "error": "vocabulary_fetch_failed",
            }

        while cursor < today and (time.monotonic() - started) < budget_seconds:
            month_start = cursor
            month_end = min(_next_month_start(month_start), today)
            try:
                start_dt = datetime(month_start.year, month_start.month, month_start.day, tzinfo=timezone.utc)
                end_dt   = datetime(month_end.year, month_end.month, month_end.day, tzinfo=timezone.utc)
                # ⛔ ArgoVis rate-limits, and it says so with 429 and NO
                # Retry-After header. Measured on the first production run
                # 2026-09-09: the very first backfill invocation walked two
                # months and then every request came back 429, while the run
                # still returned HTTP 200 with months_done=0 — a silent stall
                # reporting success. Waiting ~20s cleared it. So: back off and
                # RETRY the same month; a 429 is "come back later", never a
                # reason to abandon the chunk.
                profiles = None
                wait = _ARGO_429_BASE_WAIT_SECONDS
                for attempt in range(1, _ARGO_429_MAX_ATTEMPTS + 1):
                    try:
                        profiles = await _fetch_argo_window(client, start_dt, end_dt, params)
                        break
                    except httpx.HTTPStatusError as he:
                        if he.response is None or he.response.status_code != 429:
                            raise
                        if attempt == _ARGO_429_MAX_ATTEMPTS:
                            raise
                        rate_limited_waits += 1
                        log.info(
                            "argo backfill: 429 on %s, waiting %.0fs (attempt %d/%d)",
                            month_start, wait, attempt, _ARGO_429_MAX_ATTEMPTS,
                        )
                        await asyncio.sleep(wait)
                        wait = min(wait * 2, _ARGO_429_MAX_WAIT_SECONDS)
                inserted, _ = await _upsert_argo_profiles(profiles, params)
            except Exception as e:
                # Chunk failed — the cursor must NOT advance, so a restart
                # retries exactly this month rather than silently skipping it.
                # ⚠️ Log the MESSAGE, not just the type. Logging only
                # type(e).__name__ made a real NameError unreadable on
                # 2026-09-09 — "NameError" alone says nothing about which name.
                # ArgoVis needs no credential, so its URL is safe to surface;
                # the message is truncated so a huge body cannot flood the log.
                log.error(
                    "argo backfill: chunk %s..%s failed, cursor NOT advanced: %s: %.300s",
                    month_start, month_end, type(e).__name__, e,
                )
                failed_chunk = f"{month_start}..{month_end}: {type(e).__name__}"
                break

            async with db.pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO argo_backfill_state (id, done_through, updated_at)
                       VALUES (1, $1, NOW())
                       ON CONFLICT (id) DO UPDATE SET done_through = $1, updated_at = NOW()""",
                    month_end,
                )
            cursor = month_end
            months_done += 1
            total_inserted += inserted
            if cursor < today:
                await asyncio.sleep(_ARGO_BACKFILL_CHUNK_PACING_SECONDS)

    if months_done:
        async with db.pool.acquire() as conn:
            await populate_argo_cache(conn)  # bounded — see populate_argo_cache
    log.info(
        "argo backfill: %d month(s) processed, %d row(s) inserted, done_through=%s",
        months_done, total_inserted, cursor,
    )
    return {
        "months_done": months_done,
        "inserted": total_inserted,
        "done_through": cursor.isoformat(),
        "rate_limited_waits": rate_limited_waits,
        # ⛔ A run that walked zero months is NOT a success. Saying so here is
        # what stops an operator (or a cron) from reading a silent stall as
        # healthy — the shape this exact endpoint shipped with.
        "stalled": months_done == 0,
        "failed_chunk": failed_chunk,
    }


# A shrink of more than this fraction of the currently-stored row count is
# refused rather than applied — same guard class used for the ONC widening
# (2026-09-08). OceanOPS is the sole source and this ingest now keeps every
# status (not just OPERATIONAL), so a healthy fetch should only ever grow or
# hold steady; a >20% drop is far more likely a bad filter, a truncated page,
# or an upstream outage than 1,000+ real platforms vanishing between syncs.
_OCEANSITES_SHRINK_GUARD_FRACTION = 0.20


async def _upsert_oceansites_deployments(conn, deployments: list[dict]) -> int:
    """Write one row per OceanOPS deployment record.

    ⛔ Carries its own shrink guard, separate from the station one. The two
    counts move independently — a station can lose every deployment but one
    without the station count changing at all — so a guard on stations says
    nothing about this table.

    ⛔ Not a TRUNCATE. Same reasoning as the ONC locations fix (2026-09-08):
    re-creating the table every run destroys anything later enrichment adds to
    these rows, and a run that dies halfway leaves the table empty rather than
    stale. UPSERT, then delete only refs OceanOPS has stopped returning.
    """
    from datetime import date as _date

    if not deployments:
        log.error("oceansites: parse yielded zero deployment rows — table left untouched")
        return 0

    existing = await conn.fetchval("SELECT COUNT(*) FROM oceansites_deployments") or 0
    if existing and len(deployments) < existing * (1 - _OCEANSITES_SHRINK_GUARD_FRACTION):
        log.error(
            "oceansites: refusing deployment write — parse returned %d rows against %d "
            "already stored (%.0f%% shrink guard). Existing rows kept.",
            len(deployments), existing, _OCEANSITES_SHRINK_GUARD_FRACTION * 100,
        )
        return existing

    await conn.executemany(
        """INSERT INTO oceansites_deployments
           (ref, base_ref, deploy_num, name, lat, lon, position_flag, status, network,
            deploy_date, deploy_ship, age_days, model, wigos_id, country, sensor_models,
            oceanops_id, geom, updated_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
                   $16, $17,
                   -- ⛔ Casts are load-bearing. `$5 IS NULL` gives Postgres
                   -- nothing to infer a type from, and the same parameter is
                   -- used again inside ST_MakePoint, so the prepare fails with
                   -- AmbiguousParameterError rather than a wrong result.
                   CASE WHEN $5::double precision IS NULL
                          OR $6::double precision IS NULL THEN NULL
                        ELSE ST_SetSRID(
                            ST_MakePoint($6::double precision, $5::double precision), 4326)
                   END,
                   NOW())
           ON CONFLICT (ref) DO UPDATE
           SET base_ref=EXCLUDED.base_ref, deploy_num=EXCLUDED.deploy_num,
               name=EXCLUDED.name, lat=EXCLUDED.lat, lon=EXCLUDED.lon,
               position_flag=EXCLUDED.position_flag, status=EXCLUDED.status,
               network=EXCLUDED.network, deploy_date=EXCLUDED.deploy_date,
               deploy_ship=EXCLUDED.deploy_ship, age_days=EXCLUDED.age_days,
               model=EXCLUDED.model, wigos_id=EXCLUDED.wigos_id,
               country=EXCLUDED.country, sensor_models=EXCLUDED.sensor_models,
               oceanops_id=EXCLUDED.oceanops_id, geom=EXCLUDED.geom, updated_at=NOW()""",
        [(d["ref"], d["base_ref"], d["deploy_num"], d["name"], d["lat"], d["lon"],
          d["position_flag"], d["status"], d["network"],
          (_date.fromisoformat(d["deploy_date"]) if d.get("deploy_date") else None),
          d["deploy_ship"], d["age_days"], d["model"], d["wigos_id"], d["country"],
          d["sensor_models"], d["oceanops_id"])
         for d in deployments],
    )
    removed = await conn.fetchval(
        "WITH d AS (DELETE FROM oceansites_deployments WHERE ref != ALL($1::text[]) RETURNING 1) "
        "SELECT COUNT(*) FROM d",
        [d["ref"] for d in deployments],
    )
    total = await conn.fetchval("SELECT COUNT(*) FROM oceansites_deployments")
    log.info("oceansites: %d deployment rows stored (%d removed, %d without a position)",
             total, removed or 0,
             sum(1 for d in deployments if d["position_flag"]))
    return total


async def sync_oceansites() -> int:
    """Fetch ALL OceanSITES mooring platforms (every status) and upsert.

    Status changes (e.g. OPERATIONAL -> CLOSED) update the row in place; a
    row is only removed when OceanOPS stops returning that ref at all —
    "no longer operational" and "no longer exists" are different facts and
    must not share a code path (see module docstring / task brief).
    """
    from datetime import date as _date

    import ingestion.oceansites_ingest as _os_ingest
    from ingestion.oceansites_ingest import fetch_oceansites_stations
    stations = await fetch_oceansites_stations()
    # ⛔ Read BOTH module globals from the same call. They are overwritten by
    # the next fetch, and `from ... import last_sentinel_count` would bind the
    # value at import time — always 0 — instead of the one this fetch set.
    last_sentinel_count = _os_ingest.last_sentinel_count
    deployments = _os_ingest.last_deployments
    if not stations:
        # FAILED sync — do not stamp last_synced_at (rule: a failed sync must
        # not look like a successful one to the monitor).
        log.error("oceansites: OceanOPS returned zero stations, skipping sync")
        return 0

    current_refs = [s["ref"] for s in stations]

    async with db.pool.acquire() as conn:
        existing_count = await conn.fetchval("SELECT COUNT(*) FROM oceansites_stations")

        if existing_count and len(stations) < existing_count * (1 - _OCEANSITES_SHRINK_GUARD_FRACTION):
            # FAILED sync (refused) — do not stamp last_synced_at.
            log.error(
                "oceansites: refusing sync — fetch returned %d stations, stored has %d "
                "(%.0f%% shrink guard)",
                len(stations), existing_count, _OCEANSITES_SHRINK_GUARD_FRACTION * 100,
            )
            return existing_count

        await conn.executemany(
            """INSERT INTO oceansites_stations
               (ref, name, lat, lon, status, network, deploy_date, age_days, model,
                wigos_id, country, sensor_models, deploy_ship, deployment_count,
                geom, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                       ST_SetSRID(ST_MakePoint($4, $3), 4326),
                       NOW())
               ON CONFLICT (ref) DO UPDATE
               SET name=EXCLUDED.name, lat=EXCLUDED.lat, lon=EXCLUDED.lon,
                   status=EXCLUDED.status, network=EXCLUDED.network,
                   deploy_date=EXCLUDED.deploy_date, age_days=EXCLUDED.age_days,
                   model=EXCLUDED.model, wigos_id=EXCLUDED.wigos_id,
                   country=EXCLUDED.country, sensor_models=EXCLUDED.sensor_models,
                   deploy_ship=EXCLUDED.deploy_ship,
                   deployment_count=EXCLUDED.deployment_count,
                   geom=EXCLUDED.geom, updated_at=NOW()""",
            [(s["ref"], s["name"], s["lat"], s["lon"],
              s["status"], s["network"],
              (_date.fromisoformat(s["deploy_date"]) if s.get("deploy_date") else None),
              s.get("age_days"), s.get("model"),
              s.get("wigos_id"), s.get("country"), s.get("sensor_models"),
              s.get("deploy_ship"), s.get("deployment_count"))
             for s in stations],
        )
        await _upsert_oceansites_deployments(conn, deployments)
        # A ref is removed only when OceanOPS stops returning it entirely —
        # NOT merely when its status changes (that's an UPDATE above).
        deleted = await conn.fetchval(
            "WITH d AS (DELETE FROM oceansites_stations WHERE ref != ALL($1::text[]) RETURNING 1) "
            "SELECT COUNT(*) FROM d",
            current_refs,
        )
        count = await conn.fetchval("SELECT COUNT(*) FROM oceansites_stations")

    if deleted:
        log.info("oceansites: removed %d refs no longer present in OceanOPS at all", deleted)

    global _oceansites_cache
    _oceansites_cache = None
    log.info("oceansites: %d sentinel (1900-01-01) deploy dates rejected to NULL this sync",
              last_sentinel_count)
    await _log_sync("oceansites", len(stations), count)
    asyncio.create_task(_notify_indexnow([f"https://{SITE_HOST}/sitemap.xml"]))
    await sync_oceansites_obs()
    return count


async def sync_oceansites_obs() -> int:
    """Fetch latest observations for every OceanSITES station and cache in DB.

    Source priority (first hit wins):
      1. NDBC — US-operated buoys, ~1-3h fresh
      2. PMEL ERDDAP — TAO/TRITON/PIRATA/RAMA, daily QC'd, days-to-weeks lag
      3. OceanSITES GDAC THREDDS — IFREMER NetCDF backstop for stations PMEL
         missed and a handful of regional moorings (Stratus, etc.)

    Stations with no source data are set to NULL and hidden from the map endpoint.
    Returns count of stations with cached observations.
    """
    from ingestion.oceansites_gdac import fetch_gdac_observations
    from ingestion.pmel_erddap import fetch_pmel_observations

    # 2026-09-08: oceansites_stations widened from 65 OPERATIONAL-only rows to
    # every OceanOPS status (~5,795). Fetching live observations for a
    # platform closed since the 1990s cannot return anything and would fan
    # this out from ~65 HTTP requests per sync to ~5,795 — a network-load
    # regression this loop's `Semaphore(10)` was never sized for. Live obs
    # are only meaningful for currently OPERATIONAL platforms.
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT ref, name FROM oceansites_stations WHERE status = 'OPERATIONAL'"
        )
    refs_with_names = [(r["ref"], r["name"]) for r in rows]
    refs = [ref for ref, _ in refs_with_names]
    if not refs:
        return 0

    sem = asyncio.Semaphore(10)

    def _parse_float(v: str) -> float | None:
        return None if v in ("MM", "N/A", "", "9999.0", "999.0", "99.0") else float(v)

    async def _fetch_obs(client: httpx.AsyncClient, ref: str) -> tuple[str, dict | None]:
        async with sem:
            for url in (
                f"https://www.ndbc.noaa.gov/data/latest_obs/{ref.upper()}.txt",
                f"https://www.ndbc.noaa.gov/data/realtime2/{ref.upper()}.txt",
            ):
                try:
                    r = await client.get(url, timeout=12)
                    if r.status_code != 200:
                        continue
                    lines = [ln for ln in r.text.strip().splitlines()
                              if ln.strip() and not ln.startswith("#")]
                    if not lines:
                        continue
                    # latest_obs is a single-line format (last line = only line)
                    # realtime2 is newest-first — take lines[0] to get the most recent
                    parts = (lines[-1] if "latest_obs" in url else lines[0]).split()
                    if "latest_obs" in url:
                        if len(parts) < 19:
                            continue
                        obs = {
                            "obs_time": f"{parts[3]}-{parts[4]}-{parts[5]} {parts[6]}:{parts[7]}Z",
                            "wtmp": _parse_float(parts[18]),
                            "atmp": _parse_float(parts[17]),
                            "wspd": _parse_float(parts[9]),
                            "wdir": _parse_float(parts[8]),
                            "wvht": _parse_float(parts[11]),
                            "pres": _parse_float(parts[15]),
                        }
                    else:
                        if len(parts) < 15:
                            continue
                        yr = parts[0] if len(parts[0]) == 4 else f"20{parts[0]}"
                        obs = {
                            "obs_time": f"{yr}-{parts[1]}-{parts[2]} {parts[3]}:{parts[4]}Z",
                            "wdir": _parse_float(parts[5]),
                            "wspd": _parse_float(parts[6]),
                            "wvht": _parse_float(parts[8]),
                            "pres": _parse_float(parts[12]),
                            "atmp": _parse_float(parts[13]),
                            "wtmp": _parse_float(parts[14]),
                        }
                    if any(v is not None for k, v in obs.items() if k != "obs_time"):
                        return ref, obs
                except Exception as exc:
                    log.debug("oceansites NDBC fetch %s: %s", ref, exc)
        return ref, None

    async with httpx.AsyncClient() as client:
        ndbc_results = await asyncio.gather(*[_fetch_obs(client, r) for r in refs])

    # Source 1: NDBC (primary)
    obs_by_ref: dict[str, tuple[dict, str]] = {
        ref: (obs, "NDBC") for ref, obs in ndbc_results if obs
    }

    # Source 2: PMEL ERDDAP — fill gaps for TAO/TRITON/PIRATA/RAMA stations.
    # PMEL keys are lowercase station names (e.g. "9n140w"); OceanSITES `name` is "9N140W".
    try:
        pmel_obs = await fetch_pmel_observations()
    except Exception:
        log.exception("PMEL ERDDAP fetch failed; continuing with NDBC only")
        pmel_obs = {}

    if pmel_obs:
        for ref, name in refs_with_names:
            if ref in obs_by_ref or not name:
                continue
            pmel_match = pmel_obs.get(name.lower())
            if pmel_match:
                obs_by_ref[ref] = (pmel_match, "PMEL")

    # Source 3: OceanSITES GDAC THREDDS — only probe stations still missing.
    # Each lookup costs ~10 small OPeNDAP requests, so cap to remaining gaps.
    gdac_targets = [name for ref, name in refs_with_names
                    if name and ref not in obs_by_ref]
    if gdac_targets:
        try:
            gdac_obs = await fetch_gdac_observations(gdac_targets)
        except Exception:
            log.exception("GDAC fetch failed; continuing with NDBC + PMEL only")
            gdac_obs = {}
        if gdac_obs:
            for ref, name in refs_with_names:
                if ref in obs_by_ref or not name:
                    continue
                match = gdac_obs.get(name)
                if match:
                    obs_by_ref[ref] = (match, "GDAC")

    with_data    = [
        (ref, json.dumps(obs), source) for ref, (obs, source) in obs_by_ref.items()
    ]
    without_data = [ref for ref in refs if ref not in obs_by_ref]

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            if with_data:
                await conn.executemany(
                    """UPDATE oceansites_stations
                       SET latest_obs = $2::jsonb,
                           obs_source = $3,
                           obs_fetched_at = NOW()
                       WHERE ref = $1""",
                    with_data,
                )
            if without_data:
                await conn.execute(
                    """UPDATE oceansites_stations
                       SET latest_obs = NULL,
                           obs_source = NULL,
                           obs_fetched_at = NOW()
                       WHERE ref = ANY($1::text[])""",
                    without_data,
                )

    global _oceansites_cache
    _oceansites_cache = None
    by_source: dict[str, int] = {}
    for _, _, source in with_data:
        by_source[source] = by_source.get(source, 0) + 1
    log.info(
        "oceansites obs: %d total (%s), %d without",
        len(with_data),
        ", ".join(f"{k}={v}" for k, v in sorted(by_source.items())),
        len(without_data),
    )
    await _log_sync("oceansites-obs", len(with_data), len(with_data))
    return len(with_data)


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/v1/admin/argo-backfill", dependencies=[Depends(require_admin_token)])
async def admin_argo_backfill(
    budget_seconds: int = Query(
        ARGO_BACKFILL_DEFAULT_BUDGET_SECONDS, ge=60, le=3600,
        description="Wall-clock budget for this invocation; re-call until done_through reaches today.",
    ),
):
    """Advance the resumable Argo full-history backfill by up to
    `budget_seconds`. Safe to call repeatedly — see sync_argo_profiles_backfill."""
    return await sync_argo_profiles_backfill(budget_seconds=budget_seconds)


@router.get("/v1/map/argo", dependencies=[Depends(get_api_key)])
async def get_argo():
    """Latest profile per float. Windowed to `_ARGO_CACHE_WINDOW_DAYS` — see
    populate_argo_cache. `windowed`/`window_days` in the payload say so
    explicitly rather than truncating silently."""
    if not _argo_float_cache:
        async with db.pool.acquire() as conn:
            await populate_argo_cache(conn)
    features = [build_argo_geojson(p) for p in _argo_float_cache.values()]
    return Response(
        content=json.dumps({
            "type": "FeatureCollection",
            "features": features,
            "windowed": True,
            "window_days": _ARGO_CACHE_WINDOW_DAYS,
        }),
        media_type="application/json",
    )


@router.get("/v1/map/argo/trails", dependencies=[Depends(get_api_key)])
async def get_argo_trails():
    """All Argo profiles in the `_ARGO_CACHE_WINDOW_DAYS` window, not
    deduplicated by platform. Used to render drift trails showing float
    movement over time. Returns minimal properties to keep payload small.
    `windowed`/`window_days` in the payload say this is a subset, not the
    full argo_profiles history (which now persists indefinitely)."""
    if not _argo_trail_cache:
        async with db.pool.acquire() as conn:
            await populate_argo_cache(conn)
    features = [
        {"type": "Feature", "geometry": json.loads(p["_geojson"]),
         "properties": {k: v for k, v in p.items() if k != "_geojson"}}
        for trail in _argo_trail_cache.values()
        for p in trail
    ]
    return Response(
        content=json.dumps({
            "type": "FeatureCollection",
            "features": features,
            "windowed": True,
            "window_days": _ARGO_CACHE_WINDOW_DAYS,
        }),
        media_type="application/json",
    )


@router.get("/v1/map/oceansites", dependencies=[Depends(get_api_key)])
async def get_oceansites():
    """Return OceanSITES mooring station locations as GeoJSON FeatureCollection."""
    global _oceansites_cache
    if _oceansites_cache:
        return Response(content=_oceansites_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT ref, name, lat, lon, status, network, deploy_date,
                   age_days, model, latest_obs, obs_source, obs_fetched_at,
                   wigos_id, country, sensor_models, deploy_ship, deployment_count
            FROM oceansites_stations
            ORDER BY ref
        """)

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": {
                "ref":            r["ref"],
                "name":           r["name"],
                "status":         r["status"],
                "network":        r["network"],
                # ⛔ json.dumps cannot serialise a datetime.date. This column
                # was TEXT until the 2026-09-08 OceanOPS widening migrated it to
                # DATE; the endpoint kept passing the raw value, so every rebuild has
                # raised TypeError since. It survived review because the
                # module-level cache serves the last string built while the
                # column was still TEXT — the 500 only appears after a restart
                # clears the cache, which is exactly when nobody is looking.
                "deploy_date":    r["deploy_date"].isoformat() if r["deploy_date"] else None,
                "age_days":       r["age_days"],
                "model":          r["model"],
                "lat":            r["lat"],
                "lon":            r["lon"],
                "latest_obs":     json.loads(r["latest_obs"]) if r["latest_obs"] else None,
                "obs_source":     r["obs_source"],
                "obs_fetched_at": r["obs_fetched_at"].isoformat() if r["obs_fetched_at"] else None,
                # All scalars — five short strings and an int per station over
                # 1,072 features. The deployment ROWS are deliberately not here:
                # 5,795 of them would more than quintuple this payload for data
                # only ever looked at one station at a time. They live behind
                # /v1/oceansites/{ref}/deployments.
                "wigos_id":         r["wigos_id"],
                "country":          r["country"],
                "sensor_models":    r["sensor_models"],
                "deploy_ship":      r["deploy_ship"],
                "deployment_count": r["deployment_count"],
            },
        }
        for r in rows
    ]
    result = json.dumps({"type": "FeatureCollection", "features": features})
    _oceansites_cache = result
    return Response(content=result, media_type="application/json")


@router.get("/v1/oceansites/{ref}/deployments", dependencies=[Depends(get_api_key)])
async def get_oceansites_deployments(ref: str):
    """Every deployment OceanOPS holds for one mooring, newest first.

    `ref` is the STATION ref (no _NNN suffix) — the same value the map serves.
    One mooring can carry dozens: 5100007 has 61, from 1988 to 2026.
    """
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT ref, deploy_num, name, lat, lon, position_flag, status, network,
                      deploy_date, deploy_ship, age_days, model, wigos_id, country,
                      sensor_models, oceanops_id
               FROM oceansites_deployments
               WHERE base_ref = $1
               ORDER BY deploy_num DESC""",
            ref,
        )
    if not rows:
        # ⛔ 404 means "no such station", and that is what this is: the station
        # table and this one are filled by the same sync from the same fetch,
        # so a known ref always has at least its own row. Never a 200 with an
        # empty list — that would read as "this mooring was never deployed".
        raise HTTPException(status_code=404, detail=f"No OceanSITES station '{ref}'")
    return {
        "ref": ref,
        "count": len(rows),
        "deployments": [
            {
                "ref":           r["ref"],
                "deploy_num":    r["deploy_num"],
                "name":          r["name"],
                "lat":           r["lat"],
                "lon":           r["lon"],
                "position_flag": r["position_flag"],
                "status":        r["status"],
                "network":       r["network"],
                "deploy_date":   r["deploy_date"].isoformat() if r["deploy_date"] else None,
                "deploy_ship":   r["deploy_ship"],
                "age_days":      r["age_days"],
                "model":         r["model"],
                "wigos_id":      r["wigos_id"],
                "country":       r["country"],
                "sensor_models": r["sensor_models"],
                "oceanops_id":   r["oceanops_id"],
            }
            for r in rows
        ],
    }


@router.get("/v1/live/oceansites/{ref}", dependencies=[Depends(get_api_key)])
async def live_oceansites(ref: str):
    """Fetch latest NDBC buoy observation for an OceanSITES station.

    Tries two NDBC sources:
    1. /data/latest_obs/{ref}.txt   — fast, current only
    2. /data/realtime2/{ref}.txt    — 45-day rolling archive (5-min/hourly)

    Returns {"available": false} for supplemental stations not in NDBC
    (e.g., PAP-SO, ESTOC, DYFAMED — European/non-US moorings).
    """
    def _f(v: str) -> float | None:
        return None if v in ("MM", "N/A", "", "9999.0", "999.0", "99.0") else float(v)

    # --- Source 1: latest_obs (single-row snapshot) ---
    url1 = f"https://www.ndbc.noaa.gov/data/latest_obs/{ref.upper()}.txt"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url1)
        if r.status_code == 200:
            lines = [ln for ln in r.text.strip().splitlines() if ln.strip() and not ln.startswith("#")]
            if lines:
                parts = lines[0].split()
                # Column layout: stn lat lon yyyy mm dd hh mm wdir wspd gst wvht dpd apd mwd pres ptdy atmp wtmp
                if len(parts) >= 19:
                    obs_time = f"{parts[3]}-{parts[4]}-{parts[5]} {parts[6]}:{parts[7]}Z"
                    result = {
                        "available": True,
                        "obs_time":  obs_time,
                        "wtmp": _f(parts[18]),
                        "atmp": _f(parts[17]),
                        "wspd": _f(parts[9]),
                        "wdir": _f(parts[8]),
                        "wvht": _f(parts[11]),
                        "pres": _f(parts[15]),
                    }
                    # Only return available if at least one measurement is non-null
                    if any(v is not None for k, v in result.items() if k != "obs_time" and k != "available"):
                        return result
    except Exception as exc:
        log.debug("NDBC latest_obs failed for %s: %s", ref, exc)

    # --- Source 2: realtime2 (45-day archive, last data row) ---
    url2 = f"https://www.ndbc.noaa.gov/data/realtime2/{ref.upper()}.txt"
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(url2)
        if r.status_code != 200:
            return {"available": False}
        # Header lines start with #, data rows follow
        data_lines = [ln for ln in r.text.strip().splitlines()
                      if ln.strip() and not ln.startswith("#")]
        if not data_lines:
            return {"available": False}
        # Columns: YY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP DEWP VIS PTDY TIDE
        parts = data_lines[-1].split()  # most recent row
        if len(parts) < 15:
            return {"available": False}
        yr = parts[0] if len(parts[0]) == 4 else f"20{parts[0]}"
        obs_time = f"{yr}-{parts[1]}-{parts[2]} {parts[3]}:{parts[4]}Z"
        result = {
            "available": True,
            "obs_time":  obs_time,
            "wdir": _f(parts[5]),
            "wspd": _f(parts[6]),
            "wvht": _f(parts[8]),
            "pres": _f(parts[12]),
            "atmp": _f(parts[13]),
            "wtmp": _f(parts[14]),
        }
        if any(v is not None for k, v in result.items() if k != "obs_time" and k != "available"):
            return result
        return {"available": False}
    except Exception as exc:
        log.debug("NDBC realtime2 failed for %s: %s", ref, exc)
        return {"available": False}
