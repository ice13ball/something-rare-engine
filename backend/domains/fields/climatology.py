# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""WOA + Oxygen — the two "climatology" ambient colour-field layers: NOAA
World Ocean Atlas 2023 (temperature/salinity/nutrients/oxygen, static
download-once) and ISAS20 BGC-Argo recent-O2 + deoxygenation-vs-WOA-baseline
(`oxygen-deox`). Both share the Field-vs-Hexagon pattern and
both sample `services.woa_climatology` — `oxygen-deox`'s own "change" view is
literally ISAS recent O2 minus WOA baseline, so the two layers are coupled
data-wise as well as by module.

Moved verbatim out of backend/main.py (Task 5 of the backend vertical-split
refactor, Phase 3). Only permitted edits applied: `@app.get` -> `@router.get`,
`_pool.acquire()` -> `db.pool.acquire()`, leading underscore dropped from
every moved top-level function name (`_sync_woa` -> `sync_woa`,
`_sync_oxygen_deox` -> `sync_oxygen_deox`; every endpoint already had no
underscore), every internal call site to a renamed function rewired to the
bare form, and imports/docstring. The two cache globals keep their leading
underscore, matching precedent.

## `woa_sample` moved here too — the `sensors.woa_enrich` cross-domain problem

`/v1/woa/sample` (`woa_sample`) originally called `sensors.woa_enrich(...)`.
Moving it into this module unchanged would have created a `fields -> sensors`
domain-to-domain import, which the architecture forbids (no sub-module may
import another domain). Rather than stranding this one WOA endpoint in
`main.py` next to `_backfill_woa_anomalies` (the only other caller of the
same function), the coordinator had the underlying function moved to its true
home: `woa_enrich` is now `services.woa_climatology.enrich_profile` — it was
always a ten-line pure wrapper over that module's own `sample()`, with
nothing Argo-specific beyond its return keys' naming. `sensors.py` and
`main.py`'s `_backfill_woa_anomalies` were both rewired to call
`woa_climatology.enrich_profile(...)` directly; this module does the same.
No `fields -> sensors` edge exists, and `climatology.py` carries its full 9
`/v1/woa*` + `/v1/oxygen*` endpoints — none left behind in `main.py`.

`woa_sample`'s docstring was updated to name `services.woa_climatology.
enrich_profile` instead of the deleted `_woa_enrich` — the one docstring edit
in this whole task, made at the reviewing coordinator's explicit instruction
after the whole-branch review. Task 2's "revert rather than fix prose during a
pure move" precedent (editing OpenAPI `description` text fails the
byte-for-byte gate) is right for a docstring describing unchanged code, but
`_woa_enrich` doesn't exist anywhere in this codebase any more — a docstring
that still names it doesn't describe a stale-but-valid alternative, it
describes nothing. This one line was worth a gate re-check (still passed:
FastAPI's OpenAPI `description` is the function's docstring, so the gate
snapshot was re-taken after this edit, not compared against the pre-edit one).

## `_HEX_CELLS_SQL` — imported from `_common.py`, not duplicated

`woa_hexes` and `oxygen_hexes` are two of eight consumers of the same 2-line
SQL constant, the other six spread across `carbon.py` and `habitat.py`. All
eight consumers left `main.py`, so the constant moved into
`domains/fields/_common.py` — one definition, imported here as `from ._common
import _HEX_CELLS_SQL`. An intra-package import, not a domain-to-domain edge.

## What did NOT move, and why

- **`_woa_startup_bake`, `_oxygen_startup_bake`, `_woa_backfill_task`,
  `_backfill_woa_anomalies`** — startup orchestration / one-shot Argo
  backfill, stay in `main.py` per the brief. The two startup-bake wrappers
  were rewired to call `fields.climatology.sync_woa()` /
  `fields.climatology.sync_oxygen_deox()`. `_backfill_woa_anomalies` needed
  no `fields` reference at all — its call was rewired to
  `woa_climatology.enrich_profile(...)` directly (see above).
- **`_BAKE_STARTUP_DELAY`** stays in `main.py` — shared by every field-layer
  bake, not owned by this module alone.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import db
from auth import get_api_key
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from services import oxygen_deox, woa_climatology
from sync_log import log_sync as _log_sync

from ._common import _HEX_CELLS_SQL

log = logging.getLogger(__name__)
router = APIRouter()

# ── Caches ──────────────────────────────────────────────────────────────────
_woa_meta_cache: str | None = None  # serialized /v1/woa/meta payload
_oxygen_meta_cache: str | None = None  # serialized /v1/oxygen/meta payload


def clear_caches() -> None:
    """Drop this domain's cached responses. Called by /admin/cache/clear."""
    global _woa_meta_cache, _oxygen_meta_cache
    _woa_meta_cache = None
    _oxygen_meta_cache = None


async def sync_woa(force: bool = False) -> int:
    """Download WOA grids (once) + bake all colour PNGs. Static dataset: a 30-day
    sync_log guard skips re-bakes unless force=True (admin Force Sync passes force)."""
    global _woa_meta_cache
    if not force:
        async with db.pool.acquire() as conn:
            last = await conn.fetchval("SELECT last_synced_at FROM sync_log WHERE source = 'woa-climatology'")
        if last is not None and (datetime.now(timezone.utc) - last) < timedelta(days=30):
            log.info("woa: recent bake found — skipping")
            return 0
    try:
        n = await asyncio.to_thread(woa_climatology.bake_all)
    except Exception as exc:
        log.warning("woa bake failed — keeping previous: %s", exc)
        await _log_sync("woa-climatology", 0, 0)
        return 0
    _woa_meta_cache = None
    await _log_sync("woa-climatology", n, n)
    log.info("woa: baked %d colour PNGs", n)
    return n


async def sync_oxygen_deox(force: bool = False) -> int:
    """Download + bake the ISAS DOXY oxygen layer. sync_log guard makes restarts cheap."""
    global _oxygen_meta_cache
    if not force:
        async with db.pool.acquire() as conn:
            last = await conn.fetchval("SELECT last_synced_at FROM sync_log WHERE source = 'oxygen-deox'")
        if last is not None:
            await _log_sync("oxygen-deox", 0, 0)
            return 0
    n = await asyncio.to_thread(oxygen_deox.bake_all)
    _oxygen_meta_cache = None
    await _log_sync("oxygen-deox", n, n)
    return n


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/v1/woa/meta", dependencies=[Depends(get_api_key)])
async def woa_meta():
    """Metadata for the WOA climatology layer: variables, ranges, palettes, depths."""
    global _woa_meta_cache
    if _woa_meta_cache is None:
        _woa_meta_cache = json.dumps(woa_climatology.build_meta())
    return Response(content=_woa_meta_cache, media_type="application/json")


@router.get("/v1/woa/{var_key}/{depth_m}.png", dependencies=[Depends(get_api_key)])
async def woa_texture(var_key: str, depth_m: int):
    """Serve a baked WOA colour-map PNG for a variable + depth level."""
    if var_key not in woa_climatology.WOA_VARS or depth_m not in woa_climatology.DISPLAY_DEPTHS:
        raise HTTPException(status_code=404, detail="Unknown variable or depth")
    path = woa_climatology.baked_png_path(var_key, depth_m)
    if path is None:
        raise HTTPException(status_code=404, detail="Not baked yet")
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/oxygen/meta", dependencies=[Depends(get_api_key)])
async def oxygen_meta():
    global _oxygen_meta_cache
    if _oxygen_meta_cache is None:
        _oxygen_meta_cache = json.dumps(oxygen_deox.build_meta())
    return Response(content=_oxygen_meta_cache, media_type="application/json")


@router.get("/v1/woa/hexes", dependencies=[Depends(get_api_key)])
async def woa_hexes(variable: str = "oxygen", depth: float = 0.0):
    """Field value per hex cell (clickable hexagon view of the WOA layer)."""
    if variable not in woa_climatology.WOA_VARS:
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
            v = woa_climatology.sample(variable, lat, lon, float(depth), None)
            if v is None:
                continue
            feats.append(oxygen_deox.hex_feature(lat, lon, v, json.loads(r["gj"])))
        return feats
    features = await asyncio.to_thread(_build)
    return Response(content=json.dumps({"type": "FeatureCollection", "variable": variable,
                                        "depth_m": depth, "features": features}),
                    media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/oxygen/point", dependencies=[Depends(get_api_key)])
async def oxygen_point(lat: float, lon: float, depth: float = 0.0):
    """ISAS recent O₂ (2014–2018) + WOA 1971–2000 baseline + Δ at the nearest cell.

    ⛔ NOT "~1980s". woa_climatology.FIELDS["oxygen"] uses period `decav71A0` and
    carries baseline="1971–2000" two files away; 1985 is the midpoint of that
    window, not the window. The Δ this returns is a 30-year mean subtracted from a
    5-year mean, and a reader who thinks the baseline is one decade will
    misjudge what the change means.
    """
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise HTTPException(status_code=400, detail="lat/lon out of range")
    def _build():
        grid = oxygen_deox.load_recent_grid()
        recent = (oxygen_deox.nearest_grid_value(grid.lats, grid.lons, grid.depths, grid.data,
                                                 float(lat), float(lon), float(depth))
                  if grid is not None else None)
        baseline = woa_climatology.sample("oxygen", float(lat), float(lon), float(depth), None)
        delta = (recent - baseline) if (recent is not None and baseline is not None) else None
        return {"lat": lat, "lon": lon, "depth_m": depth, "units": "µmol/kg",
                "recent_o2": recent, "baseline_o2": baseline, "delta_o2": delta}
    payload = await asyncio.to_thread(_build)
    return Response(content=json.dumps(payload), media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/oxygen/hexes", dependencies=[Depends(get_api_key)])
async def oxygen_hexes(view: str = "recent", depth: float = 0.0):
    """Recent O₂ or Δ per hex cell (clickable hexagon view of the oxygen layer)."""
    if view not in ("recent", "change"):
        raise HTTPException(status_code=400, detail="view must be recent|change")
    try:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(_HEX_CELLS_SQL)
    except Exception:
        rows = []
    def _build():
        grid = oxygen_deox.load_recent_grid()
        feats = []
        for r in rows:
            lat, lon = float(r["lat"]), float(r["lon"])
            recent = (oxygen_deox.nearest_grid_value(grid.lats, grid.lons, grid.depths, grid.data,
                                                     lat, lon, float(depth)) if grid is not None else None)
            if view == "recent":
                val = recent
            else:
                base = woa_climatology.sample("oxygen", lat, lon, float(depth), None)
                val = (recent - base) if (recent is not None and base is not None) else None
            if val is None:
                continue
            feats.append(oxygen_deox.hex_feature(lat, lon, val, json.loads(r["gj"])))
        return feats
    features = await asyncio.to_thread(_build)
    return Response(content=json.dumps({"type": "FeatureCollection", "view": view,
                                        "depth_m": depth, "features": features}),
                    media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/oxygen/{view}/{depth_m}.png", dependencies=[Depends(get_api_key)])
async def oxygen_png(view: str, depth_m: int):
    if view not in ("recent", "change"):
        raise HTTPException(status_code=404, detail="view must be recent|change")
    p = oxygen_deox.baked_png_path(view, depth_m)
    if p is None:
        raise HTTPException(status_code=404, detail="not baked")
    return Response(content=p.read_bytes(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/woa/point", dependencies=[Depends(get_api_key)])
async def woa_point(lat: float, lon: float, depth: float = 0.0, month: int = 0):
    """All WOA variables at the nearest 1° cell — powers the field click panel."""
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise HTTPException(status_code=400, detail="lat/lon out of range")
    def _build():
        out = []
        for key, cfg in woa_climatology.WOA_VARS.items():
            v = woa_climatology.sample(key, float(lat), float(lon), float(depth),
                                       month if 1 <= month <= 12 else None)
            out.append({"key": key, "label": cfg["label"], "units": cfg["units"],
                        "baseline": cfg["baseline"], "value": v})
        return out
    variables = await asyncio.to_thread(_build)
    return Response(content=json.dumps({"lat": lat, "lon": lon, "depth_m": depth,
                                        "month": month, "variables": variables}),
                    media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/woa/sample", dependencies=[Depends(get_api_key)])
async def woa_sample(lat: float, lon: float, month: int, deep_m: float = 0.0):
    """Point-sample WOA climatology for one month — powers the Argo panel's
    seasonal-cycle explorer. Reuses services.woa_climatology.enrich_profile;
    static data, so cacheable."""
    if not 1 <= month <= 12:
        raise HTTPException(status_code=400, detail="month must be 1-12")
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise HTTPException(status_code=400, detail="lat/lon out of range")
    vals = await asyncio.to_thread(woa_climatology.enrich_profile, float(lat), float(lon), int(month), 0.0, float(deep_m))
    return Response(content=json.dumps(vals), media_type="application/json",
                    headers={"Cache-Control": "public, max-age=86400"})
