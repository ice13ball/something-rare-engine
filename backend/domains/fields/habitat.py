# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""VME + Seabed Lithology + Cumulative Human Impact — three habitat/pressure
field layers grouped in the Analysis subgroup. VME is a *modelled* MaxEnt
coral-suitability hex layer (baked out-of-process by `vme-bake.service`, never
inside `abyssal-api`). Seabed Lithology is a categorical raster (Dutkiewicz
et al. 2015, CC-BY-NC). CHI is NCEAS/Halpern 2025's global cumulative human
pressure index, a single-id `TileLayer` raster.

Moved verbatim out of backend/main.py (Task 5 of the backend vertical-split
refactor, Phase 3). Only permitted edits applied: `@app.get` -> `@router.get`,
`_pool.acquire()` -> `db.pool.acquire()`, leading underscore dropped from
every moved top-level function name (`_sync_vme` -> `sync_vme`, `_sync_seabed`
-> `sync_seabed`, `_sync_chi_impact` -> `sync_chi_impact`,
`_seabed_raster_path` -> `seabed_raster_path`, `_clear_seabed_raster_cache` ->
`clear_seabed_raster_cache`, `_chi_raster_path` -> `chi_raster_path`,
`_clear_chi_raster_cache` -> `clear_chi_raster_cache`; every endpoint already
had no underscore), every internal call site to a renamed function rewired to
the bare form, and imports/docstring. Module-level constants and the three
cache globals keep their leading underscore, matching precedent:
`_SEABED_RASTER_DIR`, `_CHI_RASTER_DIR`, `_seabed_meta_cache`,
`_vme_meta_cache`, `_chi_meta_cache`.

## `sync_seabed`'s `globals()` lookup — string key rewired, not simplified away

`sync_seabed` originally called its raster-cache-clear helper indirectly:
`if "_clear_seabed_raster_cache" in globals(): globals()["_clear_seabed_raster_
cache"]()`, a defensive guard (main.py's own comment: "defined in Task 4
(raster cache)" — actually Task 5's, per `arctic.py`'s own note correcting
that). Both the sync function and the helper move into this module together,
so the guard still works exactly as before — Python resolves `globals()`
against the *module's* namespace at call time, and both names now live in
this module's namespace regardless of definition order. The string key was
rewired to match the renamed function (`"clear_seabed_raster_cache"`) so the
lookup still finds it; the guard itself was left in place rather than
simplified to a direct call, to keep the edit mechanical (rename + rewire
call sites) rather than a behavioural change. `sync_chi_impact`'s equivalent
call, `_clear_chi_raster_cache()`, was already a direct call (no `globals()`
indirection) and was rewired the same way every other renamed call site was:
to `clear_chi_raster_cache()`.

## `_HEX_CELLS_SQL` — imported from `_common.py`, not duplicated

`seabed_hexes` and `chi_hexes` are two of eight consumers of the same 2-line
SQL constant shared with `carbon.py` and `climatology.py`. See `_common.py`'s
docstring — one definition, `from ._common import _HEX_CELLS_SQL` here.

## What did NOT move, and why

- **`_seabed_startup_bake`, `_chi_startup_bake`** — startup orchestration,
  stay in `main.py` per the brief, rewired to call
  `fields.habitat.sync_seabed()` / `fields.habitat.sync_chi_impact()`.
- **VME has no startup-bake wrapper** — the heavy MaxEnt bake runs
  out-of-process in `vme-bake.service` (cgroup-capped), picked up by
  `vme-bake.timer`; `sync_vme` here only flips a `force_requested` flag in
  `vme_bake_control` for the timer to notice. Nothing to rewire.
- **`_BAKE_STARTUP_DELAY`** stays in `main.py` — shared by every field-layer
  bake, not owned by this module alone.

## Domain knowledge (load-bearing)

- VME is **modelled, not observed** — the panel/legend framing must stay
  that way. Its Dutkiewicz et al. 2015 substrate predictor is CC-BY-NC,
  which is why the layer is publishable only while the platform stays
  non-monetised.
- `vme_cells`/`vme_models` are written by the out-of-process bake worker; this
  module only reads them (`vme_meta`/`vme_hexes`/`vme_point`) and requests a
  re-bake (`sync_vme`).
- CHI is **total human pressure**; seabed mining is a minor component and ISA
  claims sit in relatively low-CHI abyssal zones — context, not accusation.
- The CHI raster is a **single-id `TileLayer`**, not sliced `BitmapLayer`s, so
  `DECK_TO_TOGGLE` matches on the frontend and it sorts *under* claims.
  `pickable: false` — both CHI and seabed rasters resolve clicks via the
  `<DeckGL onClick>` empty-click branch + a `/point` lookup, never by making
  the raster itself pickable (a pickable
  raster picks its entire tile quad, including transparent pixels, and
  silently shadows every layer beneath it).
"""

from __future__ import annotations

import asyncio
import json
import logging
from disk_cache import empty_dir
import os
from datetime import datetime, timedelta, timezone

import db
from auth import get_api_key
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from services import chi_impact, oxygen_deox, seabed_lithology, vme_sdm
from sync_log import log_sync as _log_sync

from ._common import _HEX_CELLS_SQL

log = logging.getLogger(__name__)
router = APIRouter()

# ── Constants ─────────────────────────────────────────────────────────────
_SEABED_RASTER_DIR = os.getenv("SEABED_RASTER_DIR", "/var/cache/abyssal-seabed-raster")
_CHI_RASTER_DIR = os.getenv("CHI_RASTER_DIR", "/var/cache/abyssal-chi-raster")

# ── Caches ──────────────────────────────────────────────────────────────────
_seabed_meta_cache: str | None = None  # serialized /v1/seabed/meta payload
_vme_meta_cache: str | None = None  # serialized /v1/vme/meta payload
_chi_meta_cache: str | None = None


def clear_caches() -> None:
    """Drop this domain's cached responses. Called by /admin/cache/clear."""
    global _seabed_meta_cache, _vme_meta_cache, _chi_meta_cache
    _seabed_meta_cache = None
    _vme_meta_cache = None
    _chi_meta_cache = None


async def sync_vme(force: bool = False) -> int:
    """Admin/scheduled trigger: request the isolated vme-bake worker to run.
    The heavy MaxEnt bake runs OUT-OF-PROCESS in vme-bake.service (cgroup-capped),
    picked up by vme-bake.timer within ~5 min. We never bake inside abyssal-api."""
    global _vme_meta_cache
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE vme_bake_control SET force_requested=TRUE, requested_at=now() WHERE id")
    _vme_meta_cache = None
    log.info("vme-sdm: bake requested (force=%s) — vme-bake.timer will pick it up", force)
    return 0


async def sync_seabed(force: bool = False) -> int:
    """Download (once) the Dutkiewicz seabed lithology grid; clear baked raster cache."""
    global _seabed_meta_cache
    if not force:
        async with db.pool.acquire() as conn:
            last = await conn.fetchval("SELECT last_synced_at FROM sync_log WHERE source = 'seabed'")
        if last is not None and (datetime.now(timezone.utc) - last) < timedelta(days=30):
            log.info("seabed: recent holdings — skipping"); return 0
    ok = await asyncio.to_thread(seabed_lithology.ensure_holdings, force)
    if not ok:
        log.warning("seabed: holdings download failed — keeping previous")
        await _log_sync("seabed", 0, 0); return 0
    if "clear_seabed_raster_cache" in globals():
        globals()["clear_seabed_raster_cache"]()  # defined in this module (raster cache)
    seabed_lithology._GRID = None   # force reload on next request
    _seabed_meta_cache = None
    await _log_sync("seabed", 1, 1)
    log.info("seabed: holdings ready")
    return 1


async def sync_chi_impact(force: bool = False) -> int:
    global _chi_meta_cache
    if not force:
        async with db.pool.acquire() as conn:
            last = await conn.fetchval("SELECT last_synced_at FROM sync_log WHERE source='chi'")
        if last is not None and (datetime.now(timezone.utc) - last) < timedelta(days=30):
            log.info("chi: recent bake — skipping"); return 0
    try:
        n = await asyncio.to_thread(chi_impact.bake_all)
    except Exception as exc:
        log.warning("chi bake failed — keeping previous: %s", exc)
        await _log_sync("chi", 0, 0); return 0
    clear_chi_raster_cache()   # grid changed → drop stale rendered tiles
    _chi_meta_cache = None
    await _log_sync("chi", n, n)
    return n


# ── Seabed Lithology raster helpers ──────────────────────────────────────────

def seabed_raster_path(z: int, x: int, y: int) -> str:
    return f"{_SEABED_RASTER_DIR}/{z}/{x}/{y}.png"


def clear_seabed_raster_cache() -> None:
    empty_dir(_SEABED_RASTER_DIR)


def chi_raster_path(z: int, x: int, y: int) -> str:
    return os.path.join(_CHI_RASTER_DIR, str(z), str(x), f"{y}.png")


def clear_chi_raster_cache() -> None:
    empty_dir(_CHI_RASTER_DIR)


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/v1/chi/raster/{z}/{x}/{y}.png", dependencies=[Depends(get_api_key)])
async def chi_raster(z: int, x: int, y: int):
    path = chi_raster_path(z, x, y)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as f:
            return Response(content=f.read(), media_type="image/png",
                            headers={"Cache-Control": "public, max-age=86400"})
    png = await asyncio.to_thread(chi_impact.render_tile, z, x, y)
    if png is None:
        return Response(status_code=204)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(png)
    os.replace(tmp, path)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/seabed/raster/{z}/{x}/{y}.png", dependencies=[Depends(get_api_key)])
async def seabed_raster(z: int, x: int, y: int):
    path = seabed_raster_path(z, x, y)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as f:
            return Response(content=f.read(), media_type="image/png",
                            headers={"Cache-Control": "public, max-age=86400"})
    png = await asyncio.to_thread(seabed_lithology.render_tile, z, x, y)
    if png is None:
        return Response(status_code=204)            # holdings not ready yet
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(png)
    os.replace(tmp, path)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/seabed/point", dependencies=[Depends(get_api_key)])
async def seabed_point(lat: float, lon: float):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="lat/lon out of range")
    code = await asyncio.to_thread(seabed_lithology.sample, lat, lon)
    if code is None:
        return {"lat": lat, "lon": lon, "class_code": None, "class_name": None,
                "class_key": None, "citation": seabed_lithology.CITATION,
                "license": seabed_lithology.LICENSE}
    return {"lat": lat, "lon": lon, "class_code": code,
            "class_name": seabed_lithology.LITHOLOGY_CLASSES[code],
            "class_key": seabed_lithology.CLASS_KEYS[code],
            "citation": seabed_lithology.CITATION, "license": seabed_lithology.LICENSE}


@router.get("/v1/seabed/hexes", dependencies=[Depends(get_api_key)])
async def seabed_hexes():
    """Seabed lithology class per hex cell (clickable hexagon view)."""
    async with db.pool.acquire() as conn:
        cells = await conn.fetch(_HEX_CELLS_SQL)

    def _build():
        feats = []
        for r in cells:
            code = seabed_lithology.sample(float(r["lat"]), float(r["lon"]))
            if code is None:
                continue
            feats.append({
                "type": "Feature",
                "geometry": json.loads(r["gj"]),
                "properties": {
                    "class_code": code,
                    "class_name": seabed_lithology.LITHOLOGY_CLASSES[code],
                    "class_key": seabed_lithology.CLASS_KEYS[code],
                    "lat": float(r["lat"]),
                    "lon": float(r["lon"]),
                },
            })
        return feats

    features = await asyncio.to_thread(_build)
    return Response(
        content=json.dumps({"type": "FeatureCollection", "features": features}),
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/v1/seabed/meta", dependencies=[Depends(get_api_key)])
async def seabed_meta():
    """Metadata for the seabed lithology layer: 13 classes, citation, license."""
    global _seabed_meta_cache
    if _seabed_meta_cache is None:
        _seabed_meta_cache = json.dumps(seabed_lithology.build_meta())
    return Response(content=_seabed_meta_cache, media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/chi/meta", dependencies=[Depends(get_api_key)])
async def chi_meta():
    global _chi_meta_cache
    if _chi_meta_cache is None:
        _chi_meta_cache = json.dumps(chi_impact.build_meta())
    return Response(content=_chi_meta_cache, media_type="application/json")


@router.get("/v1/chi/hexes", dependencies=[Depends(get_api_key)])
async def chi_hexes():
    try:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(_HEX_CELLS_SQL)
    except Exception:
        rows = []
    def _build():
        feats = []
        for r in rows:
            lat, lon = float(r["lat"]), float(r["lon"])
            val = chi_impact.sample(lat, lon)
            if val is None:
                continue                      # skip land / no-data cells
            feats.append(oxygen_deox.hex_feature(lat, lon, val, json.loads(r["gj"])))
        return feats
    features = await asyncio.to_thread(_build)
    return Response(content=json.dumps({"type": "FeatureCollection", "variable": "impact",
                    "features": features}), media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/chi/point", dependencies=[Depends(get_api_key)])
async def chi_point(lat: float, lon: float):
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise HTTPException(400, "lat/lon out of range")
    val = await asyncio.to_thread(chi_impact.sample, lat, lon)
    return Response(content=json.dumps({"lat": lat, "lon": lon, "impact": val,
                    "citation": chi_impact.CITATION}), media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/vme/meta")
async def vme_meta(_auth=Depends(get_api_key)):
    global _vme_meta_cache
    if _vme_meta_cache is None:
        m = None
        last = None
        fetch_ok = True
        try:
            async with db.pool.acquire() as conn:
                m = await conn.fetchrow(
                    "SELECT auc, boyce, var_importance, aphia_ids, n_occurrences, trained_at, published"
                    " FROM vme_models WHERE taxon_set=$1 AND published ORDER BY trained_at DESC LIMIT 1",
                    vme_sdm.TAXON_SET)
                last = await conn.fetchval("SELECT last_synced_at FROM sync_log WHERE source='vme-sdm'")
        except Exception:
            fetch_ok = False
            m = None
            last = None
        meta = {
            "taxon_set": vme_sdm.TAXON_SET,
            "taxa": vme_sdm.TAXON_NAMES,
            "vmin": vme_sdm.SUITABILITY_VMIN, "vmax": vme_sdm.SUITABILITY_VMAX,
            "ramp": vme_sdm.RAMP_HEX,
            "predictors": vme_sdm.FEATURE_ORDER,
            "auc": (float(m["auc"]) if m and m["auc"] is not None else None),
            "boyce": (float(m["boyce"]) if m and m["boyce"] is not None else None),
            "var_importance": (json.loads(m["var_importance"]) if m and m["var_importance"] else {}),
            "n_occurrences": (int(m["n_occurrences"]) if m else 0),
            "trained_at": (m["trained_at"].isoformat() if m and m["trained_at"] else None),
            "last_synced_at": (last.isoformat() if last else None),
            "citation": vme_sdm.CITATION,
        }
        if fetch_ok:
            _vme_meta_cache = json.dumps(meta)
            return Response(_vme_meta_cache, media_type="application/json")
        return Response(json.dumps(meta), media_type="application/json")
    return Response(_vme_meta_cache, media_type="application/json")


@router.get("/v1/vme/hexes")
async def vme_hexes(view: str = "suitability", _auth=Depends(get_api_key)):
    col = "uncertainty" if view == "uncertainty" else "suitability"
    try:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT d.cell_id, ST_Y(ST_Centroid(d.geom)) AS lat, ST_X(ST_Centroid(d.geom)) AS lon,
                           ST_AsGeoJSON(d.geom) AS gj, v.{col} AS val
                      FROM vme_cells v JOIN density_hex_cells d USING (cell_id)
                     WHERE v.taxon_set=$1""",
                vme_sdm.TAXON_SET)
    except Exception:
        rows = []

    def _build():
        feats = []
        for r in rows:
            if r["val"] is None:
                continue
            val = float(r["val"])
            feats.append(oxygen_deox.hex_feature(float(r["lat"]), float(r["lon"]), val, json.loads(r["gj"])))
        return feats
    features = await asyncio.to_thread(_build)
    return Response(json.dumps({"type": "FeatureCollection", "view": view, "features": features}),
                    media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/vme/point")
async def vme_point(lat: float, lon: float, _auth=Depends(get_api_key)):
    try:
        async with db.pool.acquire() as conn:
            r = await conn.fetchrow(
                """SELECT v.suitability, v.uncertainty, v.extrapolated, v.top_predictors
                     FROM density_hex_cells d JOIN vme_cells v USING (cell_id)
                    WHERE v.taxon_set=$1
                      AND ST_Contains(d.geom, ST_SetSRID(ST_Point($3,$2),4326))
                    LIMIT 1""",
                vme_sdm.TAXON_SET, lat, lon)
    except Exception:
        r = None
    if r is None:
        return {"lat": lat, "lon": lon, "suitability": None, "uncertainty": None,
                "extrapolated": None, "top_predictors": [], "citation": vme_sdm.CITATION}
    _top = json.loads(r["top_predictors"]) if r["top_predictors"] else {}
    return {"lat": lat, "lon": lon,
            "suitability": (None if r["suitability"] is None else float(r["suitability"])),
            "uncertainty": (None if r["uncertainty"] is None else float(r["uncertainty"])),
            "extrapolated": r["extrapolated"],
            "top_predictors": vme_sdm.format_top_predictors(_top),
            "citation": vme_sdm.CITATION}
