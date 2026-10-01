# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Ocean colour (satellite) — layer `ocean-colour-satellite`.

Chlorophyll-a and primary production observed from space (Copernicus-GlobColour,
Copernicus Marine), monthly, block-averaged to 0.25 degree. The service module holds
the bake and the sampler; this module is the three endpoints and the sync wrapper.

⛔ `pp` is a water-column integral (mg m-2 day-1), not the surface volumetric rate of
`ocean-nutrients-model`. ⛔ A cell with no satellite observation is `no_data`, never 0.

As for the model layer, no cache global lives here: the bake runs in the WORKER process
and the endpoints in the WEB process, so meta is rebuilt from a handful of directory
entries per request instead of being held in memory.
"""

from __future__ import annotations

import asyncio
import json
import logging

from auth import get_api_key
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from services import ocean_colour
from sync_log import log_sync as _log_sync, log_sync_skipped as _log_sync_skipped

log = logging.getLogger(__name__)
router = APIRouter()

OCEAN_COLOUR_BAKE_INTERVAL_SECONDS = 24 * 3600  # daily


async def sync_ocean_colour(force: bool = False) -> int:
    """Bake whatever months are missing (or whose supplying product changed). Returns
    the number of months baked.

    Every exit path writes a sync_log row: success and "nothing new" through log_sync,
    a run in which every wanted month failed (or the upstream could not be opened)
    through log_sync_skipped, which does NOT refresh last_synced_at so a broken
    upstream keeps ageing."""
    try:
        result = await asyncio.to_thread(ocean_colour.sync_months, force)
    except Exception as exc:
        log.warning("ocean-colour sync failed — keeping previous months: %s", exc)
        await _log_sync_skipped(ocean_colour.SYNC_SOURCE, f"{type(exc).__name__}: {exc}"[:300])
        return 0
    baked, failed = result["baked"], result["failed"]
    if failed and not baked:
        await _log_sync_skipped(
            ocean_colour.SYNC_SOURCE,
            ("upstream read failed for " + ", ".join(sorted(failed)))[:300])
        return 0
    if failed:
        log.warning("ocean-colour: %d month(s) not written: %s", len(failed), sorted(failed))
    await _log_sync(ocean_colour.SYNC_SOURCE, len(baked), len(result["on_disk"]))
    if not baked:
        log.info("ocean-colour: nothing new (newest upstream month %s, %d on disk)",
                 result["newest"], len(result["on_disk"]))
    return len(baked)


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/v1/ocean-colour/meta", dependencies=[Depends(get_api_key)])
async def ocean_colour_meta():
    """Variables, units, colour ramps, available months with the product each came
    from, attribution and caveat."""
    payload = await asyncio.to_thread(ocean_colour.build_meta)
    return Response(content=json.dumps(payload), media_type="application/json",
                    headers={"Cache-Control": "public, max-age=300"})


@router.get("/v1/ocean-colour/point", dependencies=[Depends(get_api_key)])
async def ocean_colour_point(lat: float, lon: float, var: str, month: str | None = None):
    """Exact value of the nearest 0.25 degree cell, read from the float grid (not the
    PNG). status is `ok`, `no_data` (no satellite observation in the cell: cloud, sea
    ice, polar night or land) or `not_covered` (outside the grid). The value is null
    unless ok. `valid_fraction` is the share of the 36 source cells that held a value."""
    if var not in ocean_colour.VARS:
        raise HTTPException(status_code=400, detail="unknown variable")
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise HTTPException(status_code=400, detail="lat/lon out of range")
    if month is not None and not ocean_colour.valid_month(month):
        raise HTTPException(status_code=400, detail="month must be yyyy-mm")
    try:
        out = await asyncio.to_thread(ocean_colour.point_value, var, float(lat), float(lon), month)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    out["attribution"] = ocean_colour.ATTRIBUTION
    out["caveat"] = ocean_colour.CAVEAT
    return Response(content=json.dumps(out), media_type="application/json",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/v1/ocean-colour/{var}/{month}.png", dependencies=[Depends(get_api_key)])
async def ocean_colour_texture(var: str, month: str):
    """Baked colour-mapped RGBA texture for a variable and a yyyy-mm month."""
    if var not in ocean_colour.VARS or not ocean_colour.valid_month(month):
        raise HTTPException(status_code=404, detail="Unknown variable or month")
    path = ocean_colour.png_path(var, month)
    if path is None:
        raise HTTPException(status_code=404, detail="Not baked")
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
