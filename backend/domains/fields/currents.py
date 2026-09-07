# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Ocean Currents field — animated CMEMS surface/1000 m u/v texture. The
smallest of the four `domains/fields/` sub-modules: 2 endpoints, 1 cache, the
bake logic, and the constant that paces the daily bake task.

Moved verbatim out of backend/main.py (Task 5 of the backend vertical-split
refactor, Phase 3). Only permitted edits applied: `@app.get` -> `@router.get`
(this module's code never touches `_pool`/`db.pool` — no DB access of its
own, only `sync_log`), leading underscore dropped from the two moved
top-level function names (`_sync_currents` -> `sync_currents`,
`_bake_all_currents` -> `bake_all_currents`; `currents_meta`/`currents_texture`
already had no underscore), every internal call site to a renamed function
rewired to the bare form, and imports/docstring. Module-level constants and
the cache global keep their leading underscore only where they already had
one: `_currents_meta_cache` did, `CURRENTS_BAKE_INTERVAL_SECONDS` did not and
still doesn't — it moved unchanged.

## `CURRENTS_BAKE_INTERVAL_SECONDS` moved here; `_currents_bake_task` did not

`_currents_bake_task` and `_currents_backfill_task` are startup orchestration
(daily bake loop / one-shot history backfill) and stay in `main.py`, per the
brief's explicit list — matching every other Phase-3 task's own startup-bake
wrapper. `CURRENTS_BAKE_INTERVAL_SECONDS` is a plain numeric constant that
paces `_currents_bake_task`'s sleep loop; moving it here and having
`_currents_bake_task` read `fields.currents.CURRENTS_BAKE_INTERVAL_SECONDS`
is main->domain, the allowed direction — not a `fields`-internal dependency,
so it was moved to sit with the bake logic it configures rather than left
orphaned in main.py. `_currents_bake_task` was rewired to call
`fields.currents.bake_all_currents()`; `_currents_backfill_task` (which calls
`services.currents_bake` directly, never through this module) needed no
change beyond continuing to import `services.currents_bake` itself.

## What did NOT move, and why

- **`_currents_bake_task`, `_currents_backfill_task`** — startup orchestration,
  stay in `main.py`. Rewired to call `fields.currents.sync_currents(...)` /
  `fields.currents.bake_all_currents()` where they previously called the
  underscored main.py-local names.
- **`import services.currents_bake as currents_bake`** stays in `main.py`'s
  own top-of-file imports too (not removed) — `_currents_backfill_task` calls
  `currents_bake.available_dates`/`currents_bake.bake_depth`/
  `currents_bake.prune_old`/`currents_bake.CURRENTS_HISTORY_DAYS` directly,
  independent of this module.
- **`_BAKE_STARTUP_DELAY`** (the staggered-startup dict for every field-layer
  bake, not just currents) stays in `main.py` — it belongs to the startup
  orchestration layer, not to any one field family.

## Domain knowledge (load-bearing)

- The animated field is a **custom 2D-canvas particle overlay, not a deck.gl
  layer**. `weatherlayers-gl`'s GPU particle simulation never advects under
  MapLibre interleaving — verified at the GPU-buffer level across two library
  versions and two deck.gl versions. Do not reintroduce it.
- `ImageBitmap.close()` zeroes width/height on the frontend decoder — capture
  them into locals *before* closing.
- PIL `save()` needs an explicit `format="PNG"` in the bake because the atomic
  temp filename ends in `.tmp`, which PIL can't infer a format from.
- Baked texture rows run N->S (row 0 = north) — same convention the CASCADE
  and Arctic raster bakes use.
"""

from __future__ import annotations

import asyncio
import json
import logging

import services.currents_bake as currents_bake
from auth import get_api_key
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sync_log import log_sync as _log_sync

log = logging.getLogger(__name__)
router = APIRouter()

CURRENTS_BAKE_INTERVAL_SECONDS = 24 * 3600  # daily

# ── Caches ──────────────────────────────────────────────────────────────────
_currents_meta_cache: str | None = None  # serialized /v1/currents/meta payload


def clear_caches() -> None:
    """Drop this domain's cached responses. Called by /admin/cache/clear."""
    global _currents_meta_cache
    _currents_meta_cache = None


async def sync_currents(depth_slug: str, target_date=None) -> int:
    """Bake one depth's current texture. CMEMS failure keeps the old texture.

    Runs the blocking copernicusmarine/PIL work in a thread so the event loop
    is never blocked. Returns 1 on success, 0 on handled failure.
    """
    global _currents_meta_cache
    try:
        await asyncio.to_thread(currents_bake.bake_depth, depth_slug, target_date)
    except Exception as exc:
        log.warning("currents bake %s (%s) failed — keeping previous: %s",
                    depth_slug, target_date or "latest", exc)
        await _log_sync(f"currents-{depth_slug}", 0, 0)
        return 0
    _currents_meta_cache = None  # invalidate meta so next request re-reads disk
    await _log_sync(f"currents-{depth_slug}", 1, 1)
    return 1


async def bake_all_currents():
    for slug in ("surface", "1000m"):
        await sync_currents(slug)
        await asyncio.to_thread(currents_bake.prune_old, slug)


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/v1/currents/meta", dependencies=[Depends(get_api_key)])
async def currents_meta():
    """Metadata for both baked current depths + available history dates."""
    global _currents_meta_cache
    if _currents_meta_cache is None:
        payload = {}
        for slug in ("surface", "1000m"):
            m = currents_bake.read_meta(slug)
            if m is not None:
                dates = currents_bake.available_dates(slug)
                payload[slug] = {**m, "available_dates": dates,
                                 "min_date": dates[0] if dates else m.get("date"),
                                 "max_date": dates[-1] if dates else m.get("date")}
        _currents_meta_cache = json.dumps(payload)
    return Response(content=_currents_meta_cache, media_type="application/json")


@router.get("/v1/currents/{depth_slug}.png", dependencies=[Depends(get_api_key)])
async def currents_texture(depth_slug: str, date: str | None = None):
    """Serve the baked RGBA current texture for a depth slug (optional ?date=)."""
    if depth_slug not in ("surface", "1000m"):
        raise HTTPException(status_code=404, detail="Unknown depth")
    if date is not None:
        if len(date) != 10 or date.count("-") != 2:
            raise HTTPException(status_code=400, detail="Bad date format")
        if date not in currents_bake.available_dates(depth_slug):
            raise HTTPException(status_code=404, detail="No texture for date")
    path = currents_bake.texture_path(depth_slug, date)
    if path is None:
        raise HTTPException(status_code=404, detail="Texture not baked yet")
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
