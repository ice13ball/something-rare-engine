# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Nutrients & productivity (model) — layer `ocean-nutrients-model`.

Surface nitrate, chlorophyll-a, volumetric net primary production and N* from
the Copernicus Marine global biogeochemical analysis-and-forecast system
(PISCES, 0.25 degree, monthly means). The service module holds the bake and the
sampler; this module is the three endpoints and the sync wrapper.

⛔ Model output, not measurements. ⛔ `nppv` is a volumetric rate at the surface
level (mg m-3 day-1), not a column integral.

No cache global lives here on purpose: the bake runs in the WORKER process and
the endpoints in the WEB process, so an in-memory meta cache would go stale in
exactly the way the scheduling module's docstring warns about. Meta is rebuilt
from a handful of directory entries per request instead.
"""

from __future__ import annotations

import asyncio
import json
import logging

from auth import get_api_key
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from services import bgc_model
from sync_log import log_sync as _log_sync, log_sync_skipped as _log_sync_skipped

log = logging.getLogger(__name__)
router = APIRouter()

BGC_MODEL_BAKE_INTERVAL_SECONDS = 24 * 3600  # daily


async def sync_bgc_model(force: bool = False) -> int:
    """Bake whatever months are missing. Returns the number of months baked.

    Every exit path writes a sync_log row: success and "nothing new" through
    log_sync (so the monitor can tell "ran, found nothing" from "never ran"),
    a run in which every wanted month failed through log_sync_skipped (which does
    NOT refresh last_synced_at, so a broken upstream keeps ageing)."""
    try:
        result = await asyncio.to_thread(bgc_model.sync_months, force)
    except Exception as exc:
        log.warning("bgc-model sync failed — keeping previous months: %s", exc)
        await _log_sync_skipped(bgc_model.SYNC_SOURCE, f"{type(exc).__name__}: {exc}"[:300])
        return 0
    baked, failed = result["baked"], result["failed"]
    if failed and not baked:
        await _log_sync_skipped(
            bgc_model.SYNC_SOURCE,
            ("upstream read failed for " + ", ".join(sorted(failed)))[:300])
        return 0
    if failed:
        log.warning("bgc-model: %d month(s) not written: %s", len(failed), sorted(failed))
    await _log_sync(bgc_model.SYNC_SOURCE, len(baked), len(result["on_disk"]))
    if not baked:
        log.info("bgc-model: nothing new (newest upstream month %s, %d on disk)",
                 result["newest"], len(result["on_disk"]))
    return len(baked)


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/v1/bgc-model/meta", dependencies=[Depends(get_api_key)])
async def bgc_model_meta():
    """Variables, units, colour ramps, available months, attribution and caveat."""
    payload = await asyncio.to_thread(bgc_model.build_meta)
    return Response(content=json.dumps(payload), media_type="application/json",
                    headers={"Cache-Control": "public, max-age=300"})


@router.get("/v1/bgc-model/point", dependencies=[Depends(get_api_key)])
async def bgc_model_point(lat: float, lon: float, var: str, month: str | None = None):
    """Exact value of the nearest 0.25 degree cell, read from the float grid (not
    the PNG). status is `ok`, `no_data` (NaN: land or ice) or `not_covered`
    (outside the model grid, e.g. south of 80 S). The value is null unless ok."""
    if var not in bgc_model.VARS:
        raise HTTPException(status_code=400, detail="unknown variable")
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise HTTPException(status_code=400, detail="lat/lon out of range")
    if month is not None and not bgc_model.valid_month(month):
        raise HTTPException(status_code=400, detail="month must be yyyy-mm")
    try:
        out = await asyncio.to_thread(bgc_model.point_value, var, float(lat), float(lon), month)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    out["attribution"] = bgc_model.ATTRIBUTION
    out["caveat"] = bgc_model.CAVEAT
    return Response(content=json.dumps(out), media_type="application/json",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/v1/bgc-model/{var}/{month}.png", dependencies=[Depends(get_api_key)])
async def bgc_model_texture(var: str, month: str):
    """Baked colour-mapped RGBA texture for a variable and a yyyy-mm month."""
    if var not in bgc_model.VARS or not bgc_model.valid_month(month):
        raise HTTPException(status_code=404, detail="Unknown variable or month")
    path = bgc_model.png_path(var, month)
    if path is None:
        raise HTTPException(status_code=404, detail="Not baked")
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
