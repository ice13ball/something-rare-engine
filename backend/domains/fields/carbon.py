# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Ocean Carbon family — GLODAP interior carbon (DIC/TAlk/pH/Cant), SOCAT
surface CO2, GLODAP-derived Ocean Acidification (aragonite/calcite saturation
+ platform-derived saturation-horizon depth), Coral Acidification Exposure
(VME suitability x horizon shift), and the Unified Marine Carbon synthesis hex
layer that co-locates all of the above plus WOA/ISAS/GEBCO/seabed substrate
at one point. The largest of the four `domains/fields/` sub-modules — 21
endpoints across four `/v1/*` path families that all read from
`services/glodap_carbon.py`, `services/socat_co2.py`, `services/
acidification.py`, `services/coral_acid_exposure.py` and `services/
marine_carbon.py`.

Moved verbatim out of backend/main.py (Task 5 of the backend vertical-split
refactor, Phase 3). Only permitted edits applied: `@app.get` -> `@router.get`,
`_pool.acquire()` -> `db.pool.acquire()` (and the one bare `_pool` argument in
`_sync_coral_exposure` -> `db.pool`), leading underscore dropped from every
moved top-level function name (`_sync_glodap_carbon` -> `sync_glodap_carbon`,
`_sync_acidification` -> `sync_acidification`, `_sync_coral_exposure` ->
`sync_coral_exposure`, `_sync_socat_co2` -> `sync_socat_co2`, `_mc_sample` ->
`mc_sample`; every endpoint already had no underscore), every internal call
site to a renamed function rewired to the bare form, and imports/docstring.
Module-level constants and the four cache globals keep their leading
underscore, matching precedent: `_MARINE_CARBON_DECADE`, `_GEBCO_CITATION`,
`_carbon_meta_cache`, `_co2_meta_cache`, `_acid_meta_cache`,
`_coral_exposure_cache`.

## `_HEX_CELLS_SQL` — imported from `_common.py`, not duplicated

`carbon_hexes`, `acid_hexes`, `co2_hexes` and `carbon_unified_hexes` are four
of eight consumers of the same 2-line SQL constant shared with `habitat.py`
and `climatology.py`. See `_common.py`'s docstring — one definition,
`from ._common import _HEX_CELLS_SQL` here.

## Domain knowledge (load-bearing)

- **GLODAP longitude runs 20.5->379.5** (20°E corner origin, wrapping past
  360°) — `services.glodap_carbon`'s own `normalize_lon` handles this; nothing
  in this module needs to know, but a future direct-grid touch would.
- **`OmegaA`/`OmegaC` are read verbatim from GLODAP, never recomputed via
  PyCO2SYS** (unlike `vme-suitability`, which does run PyCO2SYS as one of its
  SDM predictors) — `acid_point`/`acid_hexes` sample `acidification.sample`
  directly, no PyCO2SYS call anywhere in this module. The saturation-horizon
  depth *is* platform-derived; `acid_point` discloses both `horizon_no_data`
  and `always_supersaturated` explicitly rather than collapsing them to a
  bare number.
- **The horizon-shift feature uses a reconstructed pair for BOTH epochs** —
  `acidification.sample("horizon-shift", ...)` never differences
  published-today against reconstructed-preindustrial, or the PyCO2SYS/GLODAP
  solver bias would stop cancelling. This module doesn't compute the shift;
  it only serves the pre-computed value.
- **`math.inf` horizons must never reach `json.dumps` as a bare float.**
  `acid_point` converts an infinite/`None` horizon to explicit
  `horizon_no_data`/`always_supersaturated` booleans; `acid_hexes` skips
  infinite cells outright (`_m.isinf(val)`); `mc_sample`'s `arag_horizon`/
  `arag_horizon_shift` branch coerces any non-finite value to `None` before it
  can reach the unified-hexes/unified-point JSON response — `Infinity` is not
  valid per RFC 8259.
- **SOCAT is sparse and non-gap-filled** — only ~21% of cells have data.
  `services.socat_co2`'s `_ramp_hex` emits **`pos`** keys (the frontend reads
  `.pos`, not `.value`) — this module just passes the ramp through
  `co2_meta`/`build_meta()` unchanged.
- **`carbon_unified_hexes` renders a cell if EITHER the selected variable OR
  WOA temperature has data** — keeps the co-located grid dense and clickable
  even where the selected source is sparse; value=None cells still render
  (muted) on the client, only true land cells (no WOA temperature) are
  dropped.
- Mandatory citations, surfaced verbatim from the service modules, never
  edited here: Lauvset et al. 2016 + Key et al. 2015 (GLODAP); Bakker et al.
  2026 + Sabine et al. 2013 (SOCAT).

## What did NOT move, and why

- **`_carbon_startup_bake`, `_acidification_startup_bake`, `_chi_startup_bake`
  (CHI is `habitat.py`'s, not this module's — its startup bake stays with
  it), `_coral_exposure_startup_bake`, `_socat_startup_bake`** —
  startup orchestration, stay in `main.py` per the brief. Rewired to call
  `fields.carbon.sync_glodap_carbon()`, `fields.carbon.sync_acidification()`,
  `fields.carbon.sync_coral_exposure()`, `fields.carbon.sync_socat_co2()`
  respectively.
- **`_BAKE_STARTUP_DELAY`** stays in `main.py` — shared by every field-layer
  bake, not owned by this module alone.
- **`nearest_obs.OBS_SOURCES`/`nearest_obs.shape_rows`** (used by
  `carbon_nearest_obs`) are a stable public API of `services/nearest_obs.py`
  — a service import, not a domain dependency. That service module queries
  8 GIST-indexed tables directly by raw SQL/table-name, spanning several
  other domains' tables (e.g. MEMENTO, GEOTRACES); it does not call into any
  other domain module's functions, so importing it here creates no
  domain-to-domain edge.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import datetime, timedelta, timezone

import db
from auth import get_api_key
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from services import (
    acidification,
    bathymetry_grid_export,
    glodap_carbon,
    marine_carbon,
    nearest_obs,
    oxygen_deox,
    seabed_lithology,
    socat_co2,
    vme_sdm,
    woa_climatology,
)
from sync_log import log_sync as _log_sync

from ._common import _HEX_CELLS_SQL

log = logging.getLogger(__name__)
router = APIRouter()

# ── Caches ──────────────────────────────────────────────────────────────────
_carbon_meta_cache: str | None = None  # serialized /v1/carbon/meta payload
_co2_meta_cache: str | None = None    # serialized /v1/co2/meta payload (SOCAT)
_acid_meta_cache: str | None = None
_coral_exposure_cache: str | None = None  # serialized coral-acid-exposure response payload


def clear_caches() -> None:
    """Drop this domain's cached responses. Called by /admin/cache/clear."""
    global _carbon_meta_cache, _co2_meta_cache, _acid_meta_cache, _coral_exposure_cache
    _carbon_meta_cache = None
    _co2_meta_cache = None
    _acid_meta_cache = None
    _coral_exposure_cache = None


async def sync_glodap_carbon(force: bool = False) -> int:
    """Download GLODAP grids (once) + bake all colour PNGs. Static dataset: a 30-day
    sync_log guard skips re-bakes unless force=True (admin Force Sync passes force)."""
    global _carbon_meta_cache
    if not force:
        async with db.pool.acquire() as conn:
            last = await conn.fetchval("SELECT last_synced_at FROM sync_log WHERE source = 'glodap-carbon'")
        if last is not None and (datetime.now(timezone.utc) - last) < timedelta(days=30):
            log.info("glodap-carbon: recent bake found — skipping")
            return 0
    try:
        n = await asyncio.to_thread(glodap_carbon.bake_all)
    except Exception as exc:
        log.warning("glodap-carbon bake failed — keeping previous: %s", exc)
        await _log_sync("glodap-carbon", 0, 0)
        return 0
    _carbon_meta_cache = None
    await _log_sync("glodap-carbon", n, n)
    log.info("glodap-carbon: baked %d colour PNGs", n)
    return n


async def sync_acidification(force: bool = False) -> int:
    global _acid_meta_cache
    if not force:
        async with db.pool.acquire() as conn:
            last = await conn.fetchval("SELECT last_synced_at FROM sync_log WHERE source='acidification'")
        if last is not None and (datetime.now(timezone.utc) - last) < timedelta(days=30):
            log.info("acidification: recent bake — skipping"); return 0
    try:
        n = await asyncio.to_thread(acidification.bake_all)
    except Exception as exc:
        log.warning("acidification bake failed — keeping previous: %s", exc)
        await _log_sync("acidification", 0, 0); return 0
    _acid_meta_cache = None
    await _log_sync("acidification", n, n)
    return n


async def sync_coral_exposure(force: bool = False):
    from services import coral_acid_exposure as cae
    try:
        res = await cae.bake_exposure(db.pool)
    except Exception:
        log.exception("coral-acid-exposure bake failed")
        await _log_sync("coral-acid-exposure", 0, 0)
        return
    if res["skipped"]:
        log.warning("coral-acid-exposure: skipped — %s", res["skipped"])
    global _coral_exposure_cache
    _coral_exposure_cache = None
    await _log_sync("coral-acid-exposure", res["cells"], res["cells"])


async def sync_socat_co2(force: bool = False) -> int:
    """Download SOCAT grids (once) + bake all colour PNGs. Static dataset: a 30-day
    sync_log guard skips re-bakes unless force=True (admin Force Sync passes force)."""
    global _co2_meta_cache
    if not force:
        async with db.pool.acquire() as conn:
            last = await conn.fetchval("SELECT last_synced_at FROM sync_log WHERE source = 'socat-co2'")
        if last is not None and (datetime.now(timezone.utc) - last) < timedelta(days=30):
            log.info("socat-co2: recent bake found — skipping")
            return 0
    try:
        n = await asyncio.to_thread(socat_co2.bake_all)
    except Exception as exc:
        log.warning("socat-co2 bake failed — keeping previous: %s", exc)
        await _log_sync("socat-co2", 0, 0)
        return 0
    _co2_meta_cache = None
    await _log_sync("socat-co2", n, n)
    log.info("socat-co2: baked %d colour PNGs", n)
    return n


# ── Endpoints — GLODAP ocean carbon (mirrors the WOA idiom) ─────────────────

@router.get("/v1/carbon/meta", dependencies=[Depends(get_api_key)])
async def carbon_meta():
    """Metadata for the GLODAP ocean-carbon layer: variables, ranges, palettes, depths."""
    global _carbon_meta_cache
    if _carbon_meta_cache is None:
        _carbon_meta_cache = json.dumps(glodap_carbon.build_meta())
    return Response(content=_carbon_meta_cache, media_type="application/json")


@router.get("/v1/carbon/{var_key}/{depth_m}.png", dependencies=[Depends(get_api_key)])
async def carbon_texture(var_key: str, depth_m: int):
    """Serve a baked GLODAP colour-map PNG for a variable + depth level."""
    if var_key not in glodap_carbon.CARBON_VARS:
        raise HTTPException(status_code=404, detail="Unknown variable")
    p = glodap_carbon.baked_png_path(var_key, depth_m)
    if p is None:
        raise HTTPException(status_code=404, detail="Not baked yet")
    return Response(content=p.read_bytes(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/carbon/hexes", dependencies=[Depends(get_api_key)])
async def carbon_hexes(variable: str = "dic", depth: float = 0.0):
    """Field value per hex cell (clickable hexagon view of the GLODAP carbon layer)."""
    if variable not in glodap_carbon.CARBON_VARS:
        raise HTTPException(status_code=400, detail="unknown variable")
    try:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(_HEX_CELLS_SQL)
    except Exception:
        rows = []
    def _build():
        feats = []
        for r in rows:
            lat, lon = float(r["lat"]), float(r["lon"])
            val = glodap_carbon.sample(variable, lat, lon, float(depth))
            if val is None:
                continue
            feats.append(oxygen_deox.hex_feature(lat, lon, val, json.loads(r["gj"])))
        return feats
    features = await asyncio.to_thread(_build)
    return Response(content=json.dumps({"type": "FeatureCollection", "variable": variable,
                                        "depth_m": depth, "features": features}),
                    media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/carbon/point", dependencies=[Depends(get_api_key)])
async def carbon_point(lat: float, lon: float, depth: float = 0.0):
    """All GLODAP carbon variables at the nearest cell — powers the field click panel."""
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise HTTPException(status_code=400, detail="lat/lon out of range")
    def _build():
        out = []
        for k, cfg in glodap_carbon.CARBON_VARS.items():
            out.append({"key": k, "label": cfg["label"], "units": cfg["units"],
                        "value": glodap_carbon.sample(k, float(lat), float(lon), float(depth)),
                        "n_observations": glodap_carbon.sample_count(k, float(lat), float(lon), float(depth))})
        return out
    variables = await asyncio.to_thread(_build)
    return Response(content=json.dumps({"lat": lat, "lon": lon, "depth_m": depth,
                                        "variables": variables,
                                        "citation": glodap_carbon.CITATION}),
                    media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


# ── Endpoints — Ocean Acidification (modeled; mirrors the GLODAP carbon idiom) ──

@router.get("/v1/acidification/meta", dependencies=[Depends(get_api_key)])
async def acid_meta():
    global _acid_meta_cache
    if _acid_meta_cache is None:
        _acid_meta_cache = json.dumps(acidification.build_meta())
    return Response(content=_acid_meta_cache, media_type="application/json")


@router.get("/v1/acidification/horizon.png", dependencies=[Depends(get_api_key)])
async def acid_horizon_png():
    p = acidification.baked_png_path("horizon", 0)
    if p is None:
        raise HTTPException(404, "Not baked yet")
    return Response(content=p.read_bytes(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/acidification/horizon-shift.png", dependencies=[Depends(get_api_key)])
async def acid_horizon_shift_png():
    p = acidification.baked_png_path("horizon-shift", None)
    if p is None:
        raise HTTPException(404, "Not baked yet")
    return Response(content=p.read_bytes(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/acidification/{var_key}/{depth_m}.png", dependencies=[Depends(get_api_key)])
async def acid_png(var_key: str, depth_m: int):
    if var_key not in acidification.ACID_VARS or var_key in ("horizon", "horizon-shift"):
        raise HTTPException(404, "Unknown variable")
    p = acidification.baked_png_path(var_key, depth_m)
    if p is None:
        raise HTTPException(404, "Not baked yet")
    return Response(content=p.read_bytes(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/acidification/hexes", dependencies=[Depends(get_api_key)])
async def acid_hexes(variable: str = "aragonite", depth: float = 0.0):
    if variable not in acidification.ACID_VARS:
        raise HTTPException(400, "unknown variable")
    try:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(_HEX_CELLS_SQL)
    except Exception:
        rows = []
    def _build():
        import math as _m
        feats = []
        for r in rows:
            lat, lon = float(r["lat"]), float(r["lon"])
            val = acidification.sample(variable, lat, lon, float(depth))
            if val is None or (isinstance(val, float) and _m.isinf(val)):
                continue     # skip land + always-supersaturated (no finite horizon to colour)
            feats.append(oxygen_deox.hex_feature(lat, lon, val, json.loads(r["gj"])))
        return feats
    features = await asyncio.to_thread(_build)
    return Response(content=json.dumps({"type": "FeatureCollection", "variable": variable,
                    "depth_m": depth, "features": features}), media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/acidification/point", dependencies=[Depends(get_api_key)])
async def acid_point(lat: float, lon: float, depth: float = 0.0):
    import math as _m
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise HTTPException(400, "lat/lon out of range")
    def _build():
        arag = acidification.sample("aragonite", lat, lon, depth)
        calc = acidification.sample("calcite", lat, lon, depth)
        hz   = acidification.sample("horizon", lat, lon, 0.0)
        return {
            "aragonite": arag, "calcite": calc,
            "horizon_m": (None if (hz is None or (isinstance(hz, float) and _m.isinf(hz))) else hz),
            "always_supersaturated": bool(isinstance(hz, float) and _m.isinf(hz)),
            "horizon_no_data": hz is None,
            "horizon_shift_m": acidification.sample("horizon-shift", lat, lon, None),
            "qc": acidification.qc_omega_vs_published(),
        }
    body = await asyncio.to_thread(_build)
    body.update({"lat": lat, "lon": lon, "depth_m": depth, "citation": acidification.CITATION})
    return Response(content=json.dumps(body), media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


# ── Endpoints — Coral Acidification Exposure (VME suitability x aragonite horizons) ──

@router.get("/v1/coral-exposure/meta")
async def coral_exposure_meta(_: str = Depends(get_api_key)):
    from services import coral_acid_exposure as cae
    return {
        "states": [{"key": s, "color": list(cae.STATE_COLORS[s])} for s in cae.STATES],
        "taxon_set": vme_sdm.TAXON_SET,
        "reference_year": "~2002 (GLODAP v2.2016b mapped reference year)",
        "citation": cae.CITATION,
    }


@router.get("/v1/coral-exposure/hexes")
async def coral_exposure_hexes(_: str = Depends(get_api_key)):
    global _coral_exposure_cache
    if _coral_exposure_cache is not None:
        return Response(content=_coral_exposure_cache, media_type="application/json",
                        headers={"Cache-Control": "public, max-age=86400"})
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT cell_id, suitability, state, ST_AsGeoJSON(geom) AS gj
            FROM vme_exposure_cells
            """
        )
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": json.loads(r["gj"]),          # asyncpg returns ST_AsGeoJSON as str
         "properties": {"cell_id": r["cell_id"],
                        "suitability": r["suitability"],
                        "state": r["state"]}}
        for r in rows]}
    _coral_exposure_cache = json.dumps(fc)
    return Response(content=_coral_exposure_cache, media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/coral-exposure/point")
async def coral_exposure_point(lat: float, lon: float, _: str = Depends(get_api_key)):
    from services import coral_acid_exposure as cae
    async with db.pool.acquire() as conn:
        r = await conn.fetchrow(
            """
            SELECT cell_id, taxon_set, suitability, uncertainty, lat, lon,
                   seafloor_m, horizon_today_m, horizon_pi_m, state
            FROM vme_exposure_cells
            WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326))
            LIMIT 1
            """,
            lon, lat,
        )
    if r is None:
        return {"found": False, "citation": cae.CITATION}
    out = dict(r)
    out["found"] = True
    out["citation"] = cae.CITATION
    return out


@router.get("/v1/coral-exposure/summary")
async def coral_exposure_summary(_: str = Depends(get_api_key)):
    from services import coral_acid_exposure as cae
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT suitability, state FROM vme_exposure_cells")
    pairs = [(r["suitability"], r["state"]) for r in rows]
    return {
        "weighted": cae.weighted_exposure(pairs),
        "thresholds": cae.threshold_table(pairs),
        "counts": {s: sum(1 for _, st in pairs if st == s) for s in cae.STATES},
        "reference_year": "~2002 (GLODAP v2.2016b mapped reference year)",
        "citation": cae.CITATION,
    }


# ── Endpoints — SOCAT surface CO2 ────────────────────────────────────────────

@router.get("/v1/co2/meta", dependencies=[Depends(get_api_key)])
async def co2_meta():
    """Metadata for the SOCAT surface-CO₂ layer: variables, ranges, palettes, decades."""
    global _co2_meta_cache
    if _co2_meta_cache is None:
        _co2_meta_cache = json.dumps(socat_co2.build_meta())
    return Response(content=_co2_meta_cache, media_type="application/json")


@router.get("/v1/co2/{var_key}/{decade}.png", dependencies=[Depends(get_api_key)])
async def co2_texture(var_key: str, decade: int):
    """Serve a baked SOCAT colour-map PNG for a variable + decade index."""
    if var_key not in socat_co2.CO2_VARS:
        raise HTTPException(status_code=404, detail="Unknown variable")
    p = socat_co2.baked_png_path(var_key, decade)
    if p is None:
        raise HTTPException(status_code=404, detail="Not baked yet")
    return Response(content=p.read_bytes(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/co2/hexes", dependencies=[Depends(get_api_key)])
async def co2_hexes(variable: str = "fco2", decade: int = 5):
    """Field value per hex cell (clickable hexagon view of the SOCAT surface-CO₂ layer)."""
    if variable not in socat_co2.CO2_VARS:
        raise HTTPException(status_code=400, detail="unknown variable")
    if not 0 <= decade < len(socat_co2.DECADES):
        raise HTTPException(status_code=400, detail="decade out of range")
    try:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(_HEX_CELLS_SQL)
    except Exception:
        rows = []
    def _build():
        feats = []
        for r in rows:
            lat, lon = float(r["lat"]), float(r["lon"])
            val = socat_co2.sample(variable, lat, lon, decade)
            if val is None:
                continue
            feats.append(oxygen_deox.hex_feature(lat, lon, val, json.loads(r["gj"])))
        return feats
    features = await asyncio.to_thread(_build)
    return Response(content=json.dumps({"type": "FeatureCollection", "variable": variable,
                                        "decade": decade, "features": features}),
                    media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/co2/point", dependencies=[Depends(get_api_key)])
async def co2_point(lat: float, lon: float, decade: int = 5):
    """All SOCAT CO₂ variables at the nearest cell — powers the field click panel."""
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise HTTPException(status_code=400, detail="lat/lon out of range")
    if not 0 <= decade < len(socat_co2.DECADES):
        raise HTTPException(status_code=400, detail="decade out of range")
    def _build():
        out = []
        for k, cfg in socat_co2.CO2_VARS.items():
            out.append({"key": k, "label": cfg["label"], "units": cfg["units"],
                        "value": socat_co2.sample(k, float(lat), float(lon), decade)})
        return out
    variables = await asyncio.to_thread(_build)
    return Response(content=json.dumps({"lat": lat, "lon": lon, "decade": decade,
                                        "decade_label": socat_co2.DECADES[decade]["label"],
                                        "variables": variables,
                                        "citation": socat_co2.CITATION}),
                    media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


# ---------------------------------------------------------------------------
# Unified Marine Carbon — one readout combining the four grid-aligned field
# sources (GLODAP / SOCAT / ISAS oxygen / WOA). See marine_carbon.py.
# v1: SOCAT decade fixed to latest (5 = 2020s); WOA month annual.
# ---------------------------------------------------------------------------
_MARINE_CARBON_DECADE = 5  # SOCAT 2020s — fixed in v1

# GEBCO has no service-module CITATION constant (it is a raster holding, not a synced
# source); the acknowledgement wording matches the export-registry provenance.
_GEBCO_CITATION = ("Seafloor depth: GEBCO 2024 Grid (GEBCO Compilation Group, 2024, "
                   "doi:10.5285/1c44ce99-0a0d-5f4f-e063-7086abc0ea0f). "
                   "Public domain; acknowledgement requested.")


def mc_sample(key: str, lat: float, lon: float, depth: float,
              _oxy_grid=None) -> float | None:
    """Sample one unified variable at a point. _oxy_grid lets the hex loop load
    the ISAS grid once and reuse it across cells."""
    if key.startswith("co2_"):
        sub = {"co2_fco2": "fco2", "co2_sst": "sst", "co2_sal": "salinity"}[key]
        return socat_co2.sample(sub, lat, lon, _MARINE_CARBON_DECADE)
    if key in ("dic", "talk", "ph", "cant"):
        return glodap_carbon.sample(key, lat, lon, depth)
    if key in ("o2_recent", "deox_delta"):
        g = _oxy_grid if _oxy_grid is not None else oxygen_deox.load_recent_grid()
        recent = (oxygen_deox.nearest_grid_value(g.lats, g.lons, g.depths, g.data,
                                                 lat, lon, depth) if g is not None else None)
        if key == "o2_recent":
            return recent
        base = woa_climatology.sample("oxygen", lat, lon, depth, None)
        return (recent - base) if (recent is not None and base is not None) else None
    if key.startswith("woa_"):
        sub = {"woa_temp": "temperature", "woa_sal": "salinity", "woa_o2": "oxygen",
               "woa_nitrate": "nitrate", "woa_phosphate": "phosphate",
               "woa_silicate": "silicate"}[key]
        return woa_climatology.sample(sub, lat, lon, depth, None)
    if key in ("omega_arag", "omega_calc", "arag_horizon", "arag_horizon_shift"):
        av = {"omega_arag": "aragonite", "omega_calc": "calcite",
              "arag_horizon": "horizon", "arag_horizon_shift": "horizon-shift"}[key]
        v = acidification.sample(av, lat, lon, depth)
        # acidification.sample("horizon") returns math.inf for an always-supersaturated
        # column; math.inf serialises as the invalid JSON token `Infinity` and would break
        # the whole unified-point response. Coerce any non-finite value to None (JSON null).
        return None if (isinstance(v, float) and not math.isfinite(v)) else v
    if key == "seafloor_depth":
        elev = bathymetry_grid_export.sample("depth", lat, lon, None)
        # elevation is negative below sea level; land (>=0) has no seafloor depth
        return -float(elev) if (elev is not None and elev < 0) else None
    if key == "substrate":
        return seabed_lithology.sample(lat, lon)   # int code; class name built in the endpoint
    return None


@router.get("/v1/carbon/unified-hexes", dependencies=[Depends(get_api_key)])
async def carbon_unified_hexes(variable: str = "co2_fco2", depth: float = 0.0):
    """One carbon-related variable per hex cell — the colourable Marine Carbon grid."""
    if variable not in marine_carbon.COLOR_VARS:
        raise HTTPException(status_code=400, detail="variable must be one of "
                            + ",".join(marine_carbon.COLOR_VARS))
    cfg = marine_carbon.MARINE_CARBON_VARS[variable]
    try:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(_HEX_CELLS_SQL)
    except Exception:
        rows = []

    def _build():
        oxy = oxygen_deox.load_recent_grid() if variable in ("o2_recent", "deox_delta") else None
        feats = []
        for r in rows:
            lat, lon = float(r["lat"]), float(r["lon"])
            val = mc_sample(variable, lat, lon, float(depth), _oxy_grid=oxy)
            # Render the cell if the SELECTED variable has a value OR the cell has any
            # ocean climatology coverage (WOA temperature is global-ocean). Keeps the
            # grid dense and clickable even where the selected variable is sparse
            # (e.g. SOCAT fCO₂ ~21% coverage): value=None cells render muted on the
            # client and still surface the other sources on click. Land cells (WOA
            # temp None) are dropped.
            if val is None and woa_climatology.sample("temperature", lat, lon, float(depth), None) is None:
                continue
            feats.append({"type": "Feature", "geometry": json.loads(r["gj"]),
                          "properties": {"lat": lat, "lon": lon, "value": val}})
        return feats

    features = await asyncio.to_thread(_build)
    return Response(content=json.dumps({"type": "FeatureCollection", "variable": variable,
                                        "depth_m": depth, "vmin": cfg["vmin"], "vmax": cfg["vmax"],
                                        "features": features}),
                    media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/carbon/unified-point", dependencies=[Depends(get_api_key)])
async def carbon_unified_point(lat: float, lon: float, depth: float = 0.0):
    """All carbon-related variables at one location, grouped by source — the click panel."""
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise HTTPException(status_code=400, detail="lat/lon out of range")

    def _build():
        oxy = oxygen_deox.load_recent_grid()
        sampled = {k: mc_sample(k, float(lat), float(lon), float(depth), _oxy_grid=oxy)
                   for k in marine_carbon.MARINE_CARBON_VARS}
        labels = {}
        code = sampled.get("substrate")
        if code is not None:
            labels["substrate"] = seabed_lithology.LITHOLOGY_CLASSES.get(int(code))
        return marine_carbon.group_point(sampled, labels=labels)

    groups = await asyncio.to_thread(_build)
    return Response(content=json.dumps({"lat": lat, "lon": lon, "depth_m": depth,
                                        "decade": _MARINE_CARBON_DECADE, "groups": groups,
                                        # Co-location: every source cited. The two new field
                                        # groups add the platform-derived aragonite horizon
                                        # (acidification), GEBCO seafloor depth, and Dutkiewicz
                                        # substrate — the last is CC-BY-NC, so its attribution
                                        # is a licence obligation, not a nicety.
                                        "citations": [glodap_carbon.CITATION, socat_co2.CITATION,
                                                      acidification.CITATION,
                                                      seabed_lithology.CITATION,
                                                      _GEBCO_CITATION]}),
                    media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/carbon/nearest-obs", dependencies=[Depends(get_api_key)])
async def carbon_nearest_obs(lat: float, lon: float):
    """Nearest in-situ measurement from each ocean-chemistry source to the clicked point.

    One KNN query per source (all 8 tables are GIST-indexed). Co-location, not fusion:
    each row is that source's single nearest feature, with its true distance in km. A
    source with no rows is omitted by shape_rows (never shown as 0 km).
    """
    raw = []
    async with db.pool.acquire() as conn:
        for s in nearest_obs.OBS_SOURCES:
            gcol = f'{s["geom_col"]}::geometry' if s["geog"] else s["geom_col"]
            pt = "ST_SetSRID(ST_MakePoint($1, $2), 4326)"
            order_pt = f"{pt}::geography" if s["geog"] else pt
            summ = ", ".join(f'"{c}"' for c in s["summary_cols"])
            sql = f'''
                SELECT "{s["id_col"]}"::text AS id, {summ},
                       ST_Y({gcol}) AS lat, ST_X({gcol}) AS lon,
                       ST_Distance({s["geom_col"]}::geography,
                                   {pt}::geography)/1000.0 AS distance_km
                FROM {s["table"]}
                ORDER BY {s["geom_col"]} <-> {order_pt}
                LIMIT 1
            '''
            try:
                row = await conn.fetchrow(sql, lon, lat)
            except Exception:
                log.warning("nearest-obs: source %s query failed", s["key"], exc_info=True)
                row = None
            summary = " · ".join(
                str(row[c]) for c in s["summary_cols"] if row and row[c] is not None
            ) if row else ""
            raw.append({
                "source": s["key"], "label": s["label"],
                "id": row["id"] if row else None,
                "distance_km": float(row["distance_km"]) if row and row["distance_km"] is not None else None,
                "summary": summary,
                "lat": float(row["lat"]) if row and row["lat"] is not None else None,
                "lon": float(row["lon"]) if row and row["lon"] is not None else None,
                "deck_layer_id": s["deck_layer_id"],
            })
    return {"observations": nearest_obs.shape_rows(raw)}
