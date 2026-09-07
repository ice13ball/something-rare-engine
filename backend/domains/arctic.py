# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Arctic family — ARCADE pan-Arctic catchments (raster choropleth), CASCADE
Arctic sediment carbon (stations + raster field), SIOS Svalbard observing
datasets, plus the two logged wrappers that front `land_layers.py`'s Arctic
river-input and permafrost-thaw syncs (those implementations stay in
`land_layers.py` — only the `sync_log`/IndexNow wrapper moves here).

Moved verbatim out of backend/main.py (Task 4 of the backend vertical-split
refactor, Phase 3). Only permitted edits applied: `@app.get` -> `@router.get`,
`_pool.acquire()` -> `db.pool.acquire()`, `assert _pool is not None` ->
`assert db.pool is not None`, leading underscore dropped from every moved
top-level *function* name (`_sync_arctic_rivers_logged` ->
`sync_arctic_rivers_logged`, `_sync_permafrost_thaw_logged` ->
`sync_permafrost_thaw_logged`, `_sync_arcade` -> `sync_arcade`, `_sync_cascade`
-> `sync_cascade`, `_sync_sios` -> `sync_sios`, `_arctic_raster_path` ->
`arctic_raster_path`, `_clear_arctic_raster_cache` ->
`clear_arctic_raster_cache`, `_cascade_raster_path` -> `cascade_raster_path`,
`_clear_cascade_raster_cache` -> `clear_cascade_raster_cache`,
`_cascade_render_sync` -> `cascade_render_sync`; `get_cascade_stations`/
`get_sios`/`arctic_catchments_raster`/`arctic_catchments_by_point`/
`cascade_raster`/`cascade_point`/`cascade_meta` already had no underscore —
same rule prior domain modules established), every internal call site to a
renamed function rewired to the bare form, and imports/docstring. Module-level
*constants* (non-callables) keep their leading underscore, matching that
precedent: `_ARCTIC_RASTER_DIR`, `_CASCADE_RASTER_DIR`, and the three cache
globals.

## Two things Phases 2 and 3 explicitly parked here — both arrived

- **`sync_arcade`** (93 raw lines in main.py, unchanged in the move) — was
  deleted from main.py by an over-wide range cut during Phase 2, restored by
  Phase 2's Critical fix, and left in main.py *on purpose* pending this task.
  It is ARCADE pan-Arctic catchments sync logic, and this module is its home.
- **`_cascade_stations_cache` / `_cascade_meta_cache`** — nearly deleted by
  that same over-wide Phase 2 cut, restored alongside `sync_arcade`, and
  belong here for the same reason: they are CASCADE's own response caches.

Both are confirmed present in this file (see the caches section and
`sync_arcade` below) and confirmed absent from `main.py` post-move (see the
task report's `hasattr` checks).

## Measured line count vs. the task brief's estimate

The brief inventoried ~515 raw main.py lines plus 3 caches across 5
non-contiguous ranges. All 5 ranges were verified line-for-line against the
live file before cutting (see the task report's range-accuracy table) — every
boundary matched exactly, including the brief's own line-count parentheticals
(which count trailing blank separator lines, e.g. "284–289 (6)" for a 5-line
function plus one blank line before the next symbol). Nothing inside any of
the 5 ranges belonged to another family, and nothing outside them needed to
move in — each was cut as one contiguous verbatim block, in file order.

## Two module constants moved that the brief's inventory didn't name

`_ARCTIC_RASTER_DIR` and `_CASCADE_RASTER_DIR` (main.py's original top-of-file
"Constants" block, alongside `_SEABED_RASTER_DIR`/`_CHI_RASTER_DIR`, which
stay in main.py — seabed is Task 5's, CHI is main.py's own). A repo-wide grep
confirmed both are referenced **only** inside the raster-path/cache-clear
helper functions this task claims (`arctic_raster_path`,
`clear_arctic_raster_cache`, `cascade_raster_path`,
`clear_cascade_raster_cache`) — nowhere else in main.py, no other domain
module. Same "sole-consumer constant sitting outside the brief's named
ranges" pattern `onc.py` documented for `_SPARKLINE_PROPERTIES` et al. — moved
with their consumers rather than left as orphaned main.py globals.

## Caches — none swept by `admin_cache_clear` before this move, all three now swept here

`_cascade_stations_cache`, `_cascade_meta_cache`, `_sios_cache` were never
referenced by `admin_cache_clear()` before this move (confirmed by grep — at
that point the function only ever cleared `_cache`, `_grid_cache`,
`_claims_risk_cache` plus the domain registry loop; `_grid_cache` has since
moved to `domains/biodiversity.py` and `_claims_risk_cache` to
`domains/isa.py` — only `_cache` is still main's own). `clear_caches()` here
empties all three to `None`.
This widens `/admin/cache/clear`'s effective behaviour by three more entries,
matching the onc.py/sensors.py/geochem.py precedent for caches that were
never hand-cleared pre-move — see `domains/__init__.py`'s module docstring
and `test_domain_cache_clear.py`.

## What did NOT move, and why

- **`land_layers._sync_arctic_rivers` / `land_layers._sync_permafrost_thaw`**
  stay exactly where they are, in `land_layers.py`. Only the thin
  `sync_log`/IndexNow *wrappers* around them moved here — imported directly
  (`from land_layers import _sync_arctic_rivers, _sync_permafrost_thaw`),
  called with their original underscored names (they are `land_layers`'
  names, not this module's, so the "drop the leading underscore" rule does
  not apply to them).
- **`_cascade_startup_bake`** stays in `main.py` per the brief — startup
  orchestration for baked/field layers stays centralized in `lifespan()`,
  the same pattern every prior Phase-3 task used for its own startup-bake
  wrapper. It was rewired to call `arctic.sync_cascade()`.
- **`_sync_all_sources`'s weekly per-source list and `_SYNC_SOURCES`** were
  rewired for all 4 keys this module owns (`arctic-rivers`,
  `permafrost-thaw`, `sios`, `arcade`) to call
  `arctic.sync_arctic_rivers_logged`, `arctic.sync_permafrost_thaw_logged`,
  `arctic.sync_sios`, `arctic.sync_arcade` respectively. `_SOURCE_TO_ACTION`
  needed no change — it is a string→string action-key map with no function
  references.
- **`_seabed_raster_path`/`_clear_seabed_raster_cache`/`_chi_raster_path`/
  `_clear_chi_raster_cache`** (Task 5 / main.py's own, respectively) sit
  physically adjacent to the arctic/cascade raster helpers in main.py's
  original layout but were confirmed by name and by the brief's explicit
  "DO NOT MOVE" list to belong to other owners. Left exactly where they are.
- **`_bake_all_currents`, `_sync_oxygen_deox`, `woa_hexes`, `seabed_meta`,
  `_clear_seabed_raster_cache`** — Task 5 (`fields`) owns these; confirmed by
  grep none reference any symbol this module owns.
- **`_resource_type`, `_sync_arcgis_group`, `_upsert_dwc_archive_and_stations`**
  — Phase 4 territory at the time; confirmed by grep, no reference to
  anything here. Since landed: the first two are now `isa.resource_type` /
  `isa.sync_arcgis_group` in `domains/isa.py`, the third is now
  `biodiversity.upsert_dwc_archive_and_stations` in `domains/biodiversity.py`.

## Domain knowledge (load-bearing)

- **CASCADE's grid CRS is a bespoke polar stereographic with `lat_ts=75` — it
  is NOT EPSG:3995** (which uses `lat_ts=71`). Using the EPSG code would
  silently misplace every sample. `services/cascade_grid.py`'s module `PROJ4`
  constant is the only correct source for this projection string.
- **CASCADE NODATA is a `-9990` threshold check (`v <= -9990`), not an exact
  `-9999` match** — that sentinel belongs to WRI Aqueduct, a different layer
  entirely.
- **CASCADE's station text file is latin-1, not UTF-8** — the per-mil symbol
  (‰) in the isotope column headers is not valid UTF-8 in the source file;
  `sync_cascade` decodes it explicitly (`z.read(...).decode("latin-1")`).
- **ARCADE's `t_2m_mean` is stored in Kelvin, verbatim from source** — convert
  to °C only at display time in the click panel, never store the converted
  value.
- **ARCADE ingests tile 36 only** (`arcade_ingest.SOURCE_FILES`). Tiles 36
  and 37 describe the *same* 47,054 catchments; ingesting both would download
  ~130 MB twice and inflate the logged insert count to 94,108 for a table
  that correctly holds 47,054.
- **Antimeridian-crossing catchments are dropped at ingest** (the `WHERE
  (ST_XMax(g) - ST_XMin(g)) <= 180` guard in `sync_arcade`'s INSERT) —
  reprojecting EASE-Grid polar polygons that straddle ±180° yields a
  4326 ring spanning the globe the long way, which renders as a full-width
  horizontal band. Only ~10 tiny Bering-Strait basins; once wrapped the
  winding is unrecoverable, so they are dropped rather than "fixed".
- **The arctic-catchments raster must stay `pickable: false`** on the
  frontend; clicks resolve via `arctic_catchments_by_point` (`/by-point`). A
  pickable raster picks its *entire* tile quad including transparent pixels
  and silently shadows every layer beneath it.
- **SIOS ingest is a throttled term-sweep, not full enumeration** — the
  `data.json` endpoint paginates the entire ~68k METSIS catalogue, but full
  page-enumeration gets HTTP 403 after ~150 rapid requests. `sync_sios`
  instead queries a curated list of Svalbard place/station terms
  (`_SIOS_TERMS`, local to the function) with a 1.5 s delay between every
  request. Do not "optimise" this back to page enumeration.
- **`geographic_extent_ectangle_east` is an upstream SIOS typo** (`ectangle`,
  no leading `r`) for the east bound of a dataset's bbox — read verbatim
  (with a `rectangle_east` fallback) in `ingestion/sios_ingest.py`, or
  longitude silently comes back `None`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from disk_cache import empty_dir
import os
import re

import db
import httpx
from auth import get_api_key
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from indexnow import notify_indexnow as _notify_indexnow
from indexnow import SITE_HOST
from land_layers import _sync_arctic_rivers, _sync_permafrost_thaw
from sync_log import log_sync as _log_sync

log = logging.getLogger(__name__)
router = APIRouter()

# ── Caches ──────────────────────────────────────────────────────────────────
_cascade_stations_cache: str | None = None
_cascade_meta_cache: dict | None = None
_sios_cache: str | None = None


def clear_caches() -> None:
    """Drop this domain's cached responses. Called by /admin/cache/clear.

    See module docstring "Caches" section — none of these three were swept
    by `admin_cache_clear()` before this move; all three are swept here now.
    """
    global _cascade_stations_cache, _cascade_meta_cache, _sios_cache
    _cascade_stations_cache = None
    _cascade_meta_cache = None
    _sios_cache = None


# ── Constants ─────────────────────────────────────────────────────────────
# Moved out of main.py's top-of-file constants block alongside
# _SEABED_RASTER_DIR/_CHI_RASTER_DIR, which stay there (seabed is Task 5's,
# CHI is main.py's own) — see module docstring.
_ARCTIC_RASTER_DIR = os.getenv("ARCTIC_RASTER_DIR", "/var/cache/abyssal-arctic-raster")
_CASCADE_RASTER_DIR = os.getenv("CASCADE_RASTER_DIR", "/var/cache/abyssal-cascade-raster")


# ── Arctic Rivers / Permafrost Thaw — sync_log/IndexNow wrappers around land_layers.py ──

async def sync_arctic_rivers_logged() -> int:
    n = await _sync_arctic_rivers()
    await _log_sync("arctic-rivers", n, n)
    asyncio.create_task(_notify_indexnow([f"https://{SITE_HOST}/sitemap.xml"]))
    return n

async def sync_permafrost_thaw_logged(force: bool = False) -> int:
    n = await _sync_permafrost_thaw(force=force)
    await _log_sync("permafrost-thaw", n, n)
    return n


async def sync_arcade(force: bool = False) -> int:
    """ARCADE v1 pan-Arctic catchments (EASE-Grid 2.0 North → EPSG:4326).

    Static frozen dataset: skip if table is already populated unless force=True.
    Admin Force Sync passes force=True. Downloads two ~50 MB shapefiles via curl.
    """
    import zipfile as _zip, subprocess, tempfile, os as _os
    from ingestion import arcade_ingest  # sys.path is rooted in backend/

    assert db.pool is not None
    async with db.pool.acquire() as conn:
        if not force:
            n = await conn.fetchval("SELECT COUNT(*) FROM arctic_catchments")
            if n and n > 0:
                log.info("arcade: %s rows present, skip (force=False)", n)
                return 0

    # Resolve numeric Dataverse file IDs from the dataset metadata
    async with httpx.AsyncClient(timeout=60) as client:
        meta_resp = await client.get(
            "https://dataverse.nl/api/datasets/:persistentId/"
            "?persistentId=" + arcade_ingest.DATAVERSE_DOI)
        meta = meta_resp.json()
    name_to_id = {f["dataFile"]["filename"]: f["dataFile"]["id"]
                  for f in meta["data"]["latestVersion"]["files"]}

    all_rows: list[dict] = []
    fetched = 0
    for stem in arcade_ingest.SOURCE_FILES:
        fid = name_to_id.get(stem + ".zip")
        if not fid:
            log.warning("arcade: %s.zip not found in dataset listing — skipping", stem)
            continue
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
            zp = tf.name
        try:
            url = f"https://dataverse.nl/api/access/datafile/{fid}"
            subprocess.run(["/usr/bin/curl", "-4", "-sL", "-o", zp, url],
                           check=True, timeout=900)
            with _zip.ZipFile(zp) as z:
                rows = arcade_ingest.build_catchment_rows(
                    z.read(stem + ".shp"), z.read(stem + ".shx"), z.read(stem + ".dbf"))
            all_rows.extend(rows)
            fetched += len(rows)
            log.info("arcade: parsed %s rows from %s", len(rows), stem)
        except Exception as e:  # per-file isolation — one bad zip keeps the other
            log.warning("arcade: failed %s: %s", stem, e)
        finally:
            try:
                _os.unlink(zp)
            except OSError:
                pass

    if not all_rows:
        log.warning("arcade: 0 rows parsed — preserving existing data, no TRUNCATE")
        return 0

    inserted = 0
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("TRUNCATE arctic_catchments")
            for r in all_rows:
                try:
                    async with conn.transaction():  # nested = SAVEPOINT per row
                        await conn.execute("""
                            INSERT INTO arctic_catchments
                              (gid,name,stream_order,continent,area_km2,center_lat,center_lon,
                               ocs_mean,oc_tot,runoff_mean,pf_frac,t_2m_mean,params,geom)
                            SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13, g
                            FROM (SELECT ST_Multi(ST_CollectionExtract(
                                 ST_MakeValid(ST_Transform(ST_SetSRID(ST_GeomFromText($14),6931),4326)),3)) AS g) sub
                            -- Skip antimeridian-crossing catchments: reprojecting EASE-Grid polar
                            -- polygons that straddle +-180 yields a 4326 ring spanning the globe the
                            -- long way (bbox width ~360), which renders as a full-width horizontal
                            -- band. Only ~10 tiny Bering-Strait basins; once wrapped the winding is
                            -- unrecoverable, so we drop them (documented in the legend limitations).
                            WHERE (ST_XMax(g) - ST_XMin(g)) <= 180
                            ON CONFLICT (gid) DO NOTHING
                        """, r["gid"], r["name"], r["stream_order"], r["continent"],
                            r["area_km2"], r["center_lat"], r["center_lon"], r["ocs_mean"],
                            r["oc_tot"], r["runoff_mean"], r["pf_frac"], r["t_2m_mean"],
                            json.dumps(r["params"]), r["wkt"])
                    inserted += 1
                except Exception as e:
                    log.warning("arcade: skip gid=%s: %s", r.get("gid"), e)
    from routers.spatial_v2 import clear_tile_cache
    clear_tile_cache()
    clear_arctic_raster_cache()
    await _log_sync("arcade", fetched, inserted)
    log.info("arcade: inserted %s/%s catchments", inserted, fetched)
    return inserted


async def sync_cascade(force: bool = False) -> int:
    """CASCADE v2 (Circum-Arctic Sediment Carbon). Static dataset.
    Loads ~4,496 surface-sediment stations; ensures raster holdings (Task 5)."""
    global _cascade_stations_cache
    import zipfile as _zip, subprocess, os as _os
    from ingestion import cascade_ingest

    if not force:
        async with db.pool.acquire() as conn:
            n = await conn.fetchval("SELECT count(*) FROM cascade_stations")
        if n and n > 0:
            log.info("cascade: stations populated (%s) — skipping", n)
            return 0

    raw_dir = os.getenv("CASCADE_RAW_DIR", "/var/cache/abyssal-cascade/raw")
    _os.makedirs(raw_dir, exist_ok=True)
    zip_path = _os.path.join(raw_dir, "cascade-surface-sediment-2.zip")
    subprocess.run(["/usr/bin/curl", "-4", "-fsSL", "-o", zip_path,
                    "https://bolin.su.se/data/uploads/cascade-surface-sediment-2.zip"],
                   check=True, timeout=600)
    with _zip.ZipFile(zip_path) as z:
        text = z.read("CASCADEsurfsed_v2.txt").decode("latin-1")
    rows = cascade_ingest.build_station_rows(text)
    if not rows:
        log.warning("cascade: 0 station rows parsed — preserving existing data")
        return 0

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("TRUNCATE cascade_stations")
            for r in rows:
                await conn.execute(
                    """INSERT INTO cascade_stations
                       (id, station, lat, lon, water_depth_m, expedition, year, decade,
                        oc_pct, tn_pct, oc_tn, d13c, d14c, hmw_alkanes, hmw_acids, lignin,
                        params, geom)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,
                               ST_SetSRID(ST_MakePoint($4,$3),4326))
                       ON CONFLICT (id) DO NOTHING""",
                    r["id"], r["station"], r["lat"], r["lon"], r["water_depth_m"],
                    r["expedition"], r["year"], r["decade"], r["oc_pct"], r["tn_pct"],
                    r["oc_tn"], r["d13c"], r["d14c"], r["hmw_alkanes"], r["hmw_acids"],
                    r["lignin"], json.dumps(r["params"]))
    _cascade_stations_cache = None
    global _cascade_meta_cache
    from services import cascade_grid
    ok = await asyncio.to_thread(cascade_grid.ensure_holdings, force)
    if ok:
        clear_cascade_raster_cache()
        cascade_grid.reset_cache()
        _cascade_meta_cache = None
    else:
        log.warning("cascade: grid holdings unavailable")
    await _log_sync("cascade", len(rows), len(rows))
    log.info("cascade: %s stations loaded", len(rows))
    return len(rows)


async def sync_sios(force: bool = False) -> int:
    """Harvest mappable (in-situ, Open, Svalbard-region point) datasets from the
    SIOS Station REST catalogue via a THROTTLED term-sweep.  Admin-only / weekly
    chain — no startup task.

    NOTE: full page-enumeration (4577 pages) gets HTTP 403 rate-limited after
    ~150 rapid requests, so we instead query a curated set of Svalbard place /
    station / programme terms (each a few pages) with a polite per-request delay
    and dedupe by metadata_identifier.  ~50-80 requests total at <1 req/s — well
    under the rate cap, so we are never banned.  Broad terms that also match
    satellite products are harmless: the parser keeps only in-situ Svalbard
    points."""
    import httpx
    from ingestion import sios_ingest as si
    from ingestion import sios_opendap as so
    from datetime import datetime

    def _ts(s: str | None):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None

    global _sios_cache
    assert db.pool is not None
    base = "https://sios-svalbard.org/rest/stations/data.json"
    # Svalbard place / station / programme terms that surface in-situ datasets.
    _SIOS_TERMS = [
        "Spitsbergen", "Svalbard", "Hornsund", "Ny-Alesund", "Ny-Ålesund",
        "Kongsfjorden", "Isfjorden", "Adventdalen", "Adventfjorden",
        "Longyearbyen", "Barentsburg", "Zeppelin", "Janssonhaugen",
        "Storfjorden", "Rijpfjorden", "Billefjorden", "Bjørnøya",
        "Bear Island", "Barents", "permafrost Svalbard", "glacier Svalbard",
        "SCD", "SIOS Core Data", "Polish Polar Station",
    ]
    _SIOS_DELAY = 1.5    # seconds between EVERY request (<1 req/s; rate cap is ~20 req/s)
    _SIOS_PAGE_CAP = 12  # max pages per term (15 rows/page → ≤180 rows/term)
    kept: dict[str, dict] = {}
    failures = 0
    async with httpx.AsyncClient(
        timeout=60,
        headers={"User-Agent": "abyssal-claims/1.0 (research; https://something-rare.com)"},
    ) as client:
        for term in _SIOS_TERMS:
            page, total_pages = 0, 1
            while page < total_pages and page < _SIOS_PAGE_CAP:
                try:
                    resp = await client.get(base, params={"fulltext": term, "page": page})
                    resp.raise_for_status()
                    body = resp.json()
                    if page == 0:
                        total_pages = int(body.get("pager", {}).get("total_pages", 1)) or 1
                    for row in body.get("rows", []):
                        rec = si.parse_record(row)
                        if rec and rec["metadata_id"]:
                            kept[rec["metadata_id"]] = rec
                except Exception as exc:
                    failures += 1
                    log.warning("sios: term %r page %d failed: %s", term, page, exc)
                    if "403" in str(exc):
                        await asyncio.sleep(10)  # backed off — wait before continuing
                page += 1
                await asyncio.sleep(_SIOS_DELAY)
    log.info("sios: term-sweep done — %d unique mappable datasets (%d request failures)",
             len(kept), failures)

    if not kept:
        log.warning("sios: 0 mappable datasets — preserving existing data")
        return 0

    # Enrich with downsampled OPeNDAP time series (per-dataset, throttled, tolerant)
    TARGET_PTS = 700
    async with httpx.AsyncClient(
        timeout=20,  # tight per-request cap so an unresponsive Hyrax can't stall the weekly sync
        headers={"User-Agent": "abyssal-claims/1.0 (research; https://something-rare.com)"},
    ) as oc:
        for rec in kept.values():
            url = rec.get("url_opendap")
            rec["series"] = rec["series_var"] = rec["series_units"] = rec["series_long_name"] = None
            if not url:
                continue
            try:
                dds = (await oc.get(url + ".dds")).text
                var = so.parse_data_variable(dds)
                n = so.time_dim_size(dds)
                if not var or not n:
                    continue
                stride = max(1, n // TARGET_PTS)
                await asyncio.sleep(1.2)
                ascii_txt = (await oc.get(f"{url}.ascii?{var}%5B0:{stride}:{n-1}%5D")).text
                s = so.build_series(dds, ascii_txt)
                if s:
                    rec["series"] = json.dumps(s["points"])
                    rec["series_var"] = s["var"]
                    await asyncio.sleep(1.2)
                    das = (await oc.get(url + ".das")).text
                    mu = re.search(rf'{re.escape(var)} \{{.*?units "([^"]+)"', das, re.S)
                    ml = re.search(rf'{re.escape(var)} \{{.*?long_name "([^"]+)"', das, re.S)
                    rec["series_units"] = mu.group(1) if mu else None
                    rec["series_long_name"] = ml.group(1) if ml else None
            except Exception as exc:
                log.warning("sios: opendap series failed for %s: %s", rec.get("metadata_id"), exc)
            await asyncio.sleep(1.2)
    log.info("sios: opendap enrichment done for %d candidates", len(kept))

    rows = list(kept.values())
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("TRUNCATE sios_datasets")
            for rec in rows:
                await conn.execute(
                    """
                    INSERT INTO sios_datasets
                      (metadata_id, title, abstract, is_core_data, collections,
                       activity_type, iso_topic, keywords, platform_short, platform_long,
                       platform_url, institution, pi_name, time_start, time_end,
                       license, license_url, url_http, url_opendap, url_wms,
                       url_landing, lat, lon,
                       series, series_var, series_units, series_long_name, geom)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,
                            $16,$17,$18,$19,$20,$21,$22,$23,
                            $24::jsonb,$25,$26,$27,
                            ST_SetSRID(ST_MakePoint($23,$22),4326))
                    ON CONFLICT (metadata_id) DO NOTHING
                    """,
                    rec["metadata_id"], rec["title"], rec["abstract"],
                    rec["is_core_data"], rec["collections"], rec["activity_type"],
                    rec["iso_topic"], rec["keywords"], rec["platform_short"],
                    rec["platform_long"], rec["platform_url"], rec["institution"],
                    rec["pi_name"], _ts(rec["time_start"]), _ts(rec["time_end"]),
                    rec["license"], rec["license_url"], rec["url_http"],
                    rec["url_opendap"], rec["url_wms"], rec["url_landing"],
                    rec["lat"], rec["lon"],
                    rec["series"], rec["series_var"], rec["series_units"], rec["series_long_name"],
                )

    _sios_cache = None
    await _log_sync("sios", len(rows), len(rows))
    log.info("sios: inserted %d datasets", len(rows))
    return len(rows)


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/v1/map/cascade/stations")
async def get_cascade_stations(_: str = Depends(get_api_key)):
    global _cascade_stations_cache
    if _cascade_stations_cache is not None:
        return Response(content=_cascade_stations_cache, media_type="application/json")
    async with db.pool.acquire() as conn:
        js = await conn.fetchval("""
            SELECT json_build_object(
              'type','FeatureCollection',
              'features', COALESCE(json_agg(json_build_object(
                'type','Feature',
                'geometry', ST_AsGeoJSON(geom)::json,
                'properties', json_build_object(
                  'station_id', id::text, 'station', station, 'expedition', expedition,
                  'year', year, 'decade', decade, 'water_depth_m', water_depth_m,
                  'oc_pct', oc_pct, 'tn_pct', tn_pct, 'oc_tn', oc_tn,
                  'd13c', d13c, 'd14c', d14c,
                  'hmw_alkanes', hmw_alkanes, 'hmw_acids', hmw_acids, 'lignin', lignin,
                  'params', params)
              )), '[]'::json))::text
            FROM cascade_stations WHERE geom IS NOT NULL""")
    _cascade_stations_cache = js or '{"type":"FeatureCollection","features":[]}'
    return Response(content=_cascade_stations_cache, media_type="application/json")


@router.get("/v1/map/sios", dependencies=[Depends(get_api_key)])
async def get_sios():
    """SIOS Svalbard observing datasets (GeoJSON). View filtering is client-side."""
    global _sios_cache
    if _sios_cache:
        return Response(content=_sios_cache, media_type="application/json")
    assert db.pool is not None
    async with db.pool.acquire() as conn:
        txt = await conn.fetchval("""
            SELECT json_build_object(
              'type','FeatureCollection',
              'features', COALESCE(json_agg(json_build_object(
                'type','Feature',
                'geometry', ST_AsGeoJSON(geom)::json,
                'properties', json_build_object(
                  'metadata_id',   metadata_id,
                  'title',         title,
                  'abstract',      abstract,
                  'is_core_data',  is_core_data,
                  'activity_type', activity_type,
                  'iso_topic',     iso_topic,
                  'keywords',      to_json(keywords),
                  'platform_short',platform_short,
                  'platform_long', platform_long,
                  'platform_url',  platform_url,
                  'institution',   institution,
                  'pi_name',       pi_name,
                  'time_start',    time_start,
                  'time_end',      time_end,
                  'license',       license,
                  'license_url',   license_url,
                  'url_http',      url_http,
                  'url_opendap',   url_opendap,
                  'url_wms',       url_wms,
                  'url_landing',   url_landing,
                  'series',        series,
                  'series_var',    series_var,
                  'series_units',  series_units,
                  'series_long_name', series_long_name
                )
              )), '[]'::json)
            )::text
            FROM sios_datasets
        """)
    _sios_cache = txt or '{"type":"FeatureCollection","features":[]}'
    return Response(content=_sios_cache, media_type="application/json")


# ── Arctic Catchments raster endpoints ──────────────────────────────────────

def arctic_raster_path(variable: str, z: int, x: int, y: int) -> str:
    return f"{_ARCTIC_RASTER_DIR}/{variable}/{z}/{x}/{y}.png"


def clear_arctic_raster_cache() -> None:
    # No try/except here: empty_dir already treats a missing directory as
    # nothing-to-do and logs anything it genuinely cannot remove. Wrapping it
    # again would only re-hide what this commit exists to expose.
    empty_dir(_ARCTIC_RASTER_DIR)


@router.get("/v1/map/arctic-catchments/raster/{z}/{x}/{y}.png", dependencies=[Depends(get_api_key)])
async def arctic_catchments_raster(z: int, x: int, y: int, variable: str = "ocs_mean"):
    from services.arctic_ramp import ARCTIC_VARS
    if variable not in ARCTIC_VARS:
        variable = "ocs_mean"
    path = arctic_raster_path(variable, z, x, y)
    # disk cache HIT
    try:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path, "rb") as f:
                data = f.read()
            return Response(content=data, media_type="image/png",
                            headers={"Cache-Control": "public, max-age=86400"})
    except Exception:
        pass
    # render
    from raster_tiles import render_arctic_tile, EMPTY_PNG
    assert db.pool is not None
    render_ok = True
    try:
        async with db.pool.acquire() as conn:
            png = await render_arctic_tile(z, x, y, variable, conn)
    except Exception as e:
        log.warning("arctic raster render failed %s/%s/%s %s: %s", z, x, y, variable, e)
        png = EMPTY_PNG
        render_ok = False
    # atomic cache write — only on success (failed renders must not poison the cache)
    if render_ok:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(png)
            os.replace(tmp, path)
        except Exception as e:
            log.warning("arctic raster cache write failed: %s", e)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/map/arctic-catchments/by-point", dependencies=[Depends(get_api_key)])
async def arctic_catchments_by_point(lat: float, lon: float):
    """Smallest arctic catchment containing the given point (most specific)."""
    assert db.pool is not None
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT gid, name, stream_order, continent, area_km2, center_lat, center_lon,
                   ocs_mean, oc_tot, runoff_mean, pf_frac, t_2m_mean, params
            FROM arctic_catchments
            WHERE ST_Contains(geom, ST_SetSRID(ST_Point($1,$2),4326))
            ORDER BY area_km2 ASC LIMIT 1
        """, lon, lat)
    if not row:
        raise HTTPException(status_code=404, detail="no catchment at point")
    d = dict(row)
    if isinstance(d.get("params"), str):
        d["params"] = json.loads(d["params"])
    return d


def cascade_raster_path(variable: str, z: int, x: int, y: int) -> str:
    return f"{_CASCADE_RASTER_DIR}/{variable}/{z}/{x}/{y}.png"


def clear_cascade_raster_cache() -> None:
    empty_dir(_CASCADE_RASTER_DIR)


# ── CASCADE Arctic sediment carbon raster/point/meta endpoints ──────────────

@router.get("/v1/cascade/raster/{z}/{x}/{y}.png")
async def cascade_raster(z: int, x: int, y: int, variable: str = "oc", _: str = Depends(get_api_key)):
    from services.cascade_ramp import CASCADE_VARS as _V
    if variable not in _V:
        variable = "oc"
    path = cascade_raster_path(variable, z, x, y)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as f:
            return Response(content=f.read(), media_type="image/png",
                            headers={"Cache-Control": "public, max-age=86400"})
    png = await asyncio.to_thread(cascade_render_sync, z, x, y, variable)
    if png is None:
        return Response(status_code=204)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(png)
    os.replace(tmp, path)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


def cascade_render_sync(z, x, y, variable):
    from services import cascade_grid
    return cascade_grid.render_tile(z, x, y, variable)


@router.get("/v1/cascade/point")
async def cascade_point(lat: float, lon: float, variable: str = "oc", _: str = Depends(get_api_key)):
    from services.cascade_ramp import CASCADE_VARS
    if variable not in CASCADE_VARS:
        variable = "oc"
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="lat/lon out of range")
    from services import cascade_grid
    val = await asyncio.to_thread(cascade_grid.sample, lat, lon, variable)
    _units = {"oc": "%", "tn": "%", "d13c": "‰", "d14c": "‰"}

    ctx = None
    if db.pool is not None:
        async with db.pool.acquire() as conn:
            r = await conn.fetchrow(
                """SELECT count(*)::int                                    AS n_samples,
                          min(year)                                        AS year_min,
                          max(year)                                        AS year_max,
                          percentile_cont(0.5) WITHIN GROUP (ORDER BY year)::int AS year_median,
                          count(*) FILTER (WHERE year IS NULL)::int        AS n_undated
                   FROM cascade_stations
                   WHERE ST_DWithin(geom::geography,
                                    ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                                    50000)""",
                float(lon), float(lat))
        if r and r["n_samples"]:
            ctx = {"radius_km": 50, "n_samples": r["n_samples"],
                   "year_min": r["year_min"], "year_max": r["year_max"],
                   "year_median": r["year_median"], "n_undated": r["n_undated"],
                   "caveat_key": "samplingContext.notInterpolationInputs"}

    return {"variable": variable, "value": val, "unit": _units[variable],
            "lat": lat, "lon": lon,
            "citation": "Martens et al. 2021, ESSD 13:2561 (CC-BY 4.0)",
            "sampling_context": ctx}


@router.get("/v1/cascade/meta")
async def cascade_meta(_: str = Depends(get_api_key)):
    global _cascade_meta_cache
    if _cascade_meta_cache is None:
        from services import cascade_grid
        _cascade_meta_cache = cascade_grid.build_meta()
    return _cascade_meta_cache
