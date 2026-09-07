# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Sentinel-2 thumbnail confirmation for vessel_events.

After SAR×AIS correlation writes a vessel_event, this pass fetches a
small true-color Sentinel-2 PNG around each detection so an operator (or
the public DetailPanel) can visually confirm: is there actually a vessel,
a platform, a wake, or just SAR clutter?

S2 has ~5-day revisit and is cloud-affected, so the nearest usable pass
may be hours-to-days away from the SAR acquisition. We accept whatever
cloud-free-ish scene falls inside a ±3-day window around the event —
worst case the vessel has moved on, but the surrounding context
(platform? cable-ship mooring? empty ocean?) is still informative.

Thumbnails are written to ``data/s2_thumbs/<event_id>.png`` and served
via the ``/v2/map/vessel-events/{event_id}/thumb.png`` route registered
on the vessel_events router.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import httpx

import db
from sar_detector import _get_token, SH_PROCESS_URL, SH_REQUEST_CONCURRENCY
import asyncio

log = logging.getLogger("sar_confirm")

THUMB_DIR = Path(__file__).parent / "data" / "s2_thumbs"
THUMB_HALF_DEG = 0.03          # ~3 km half-side at equator
THUMB_PX       = 256
S2_WINDOW_DAYS = 3             # accept any clear-ish scene ±3 days
MAX_THUMBS_PER_RUN = 30        # PU budget cap; S2 Process is cheaper than S1

S2_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B03", "B02", "dataMask"] }],
    output: { bands: 3, sampleType: "UINT8" }
  };
}
function evaluatePixel(s) {
  if (s.dataMask < 1) return [0, 0, 0];
  // Linear stretch for true-color. L1C reflectances are ~[0, 0.3] over
  // ocean+coast; *3.5*255 maps that to the 0..255 range without saturating
  // bright urban/sand targets.
  const k = 3.5 * 255;
  return [Math.min(255, s.B04 * k),
          Math.min(255, s.B03 * k),
          Math.min(255, s.B02 * k)];
}
"""


def _bbox_around(lon: float, lat: float) -> list[float]:
    return [lon - THUMB_HALF_DEG, lat - THUMB_HALF_DEG,
            lon + THUMB_HALF_DEG, lat + THUMB_HALF_DEG]


def _thumb_path(event_id: str) -> Path:
    # event_id is sanitized on write-side (sar_correlator produces 'sar_<hex>').
    return THUMB_DIR / f"{event_id}.png"


async def _fetch_thumb(
    client: httpx.AsyncClient,
    event_id: str,
    lon: float,
    lat: float,
    ts,
) -> bool:
    """Fetch and persist one S2 RGB thumbnail. Returns True on success."""
    token = await _get_token(client)
    from_ts = (ts - timedelta(days=S2_WINDOW_DAYS)).isoformat().replace("+00:00", "Z")
    to_ts   = (ts + timedelta(days=S2_WINDOW_DAYS)).isoformat().replace("+00:00", "Z")
    body = {
        "input": {
            "bounds": {
                "bbox": _bbox_around(lon, lat),
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
            },
            "data": [{
                "type": "sentinel-2-l1c",
                "dataFilter": {
                    "timeRange":      {"from": from_ts, "to": to_ts},
                    "maxCloudCoverage": 60,
                    "mosaickingOrder": "leastCC",
                },
            }],
        },
        "output": {
            "width":  THUMB_PX,
            "height": THUMB_PX,
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
        },
        "evalscript": S2_EVALSCRIPT,
    }
    r = await client.post(
        SH_PROCESS_URL,
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=120.0,
    )
    if r.status_code != 200:
        log.info("S2 thumb miss for %s: HTTP %d", event_id, r.status_code)
        return False

    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    _thumb_path(event_id).write_bytes(r.content)
    return True


async def confirm_recent_events() -> dict[str, int]:
    """Fetch S2 thumbnails for vessel_events missing one. Returns counts."""
    summary = {"attempted": 0, "ok": 0}
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT event_id, ts, lon, lat
            FROM vessel_events
            WHERE s2_thumbnail_url IS NULL
              AND ts > NOW() - INTERVAL '14 days'
            ORDER BY ts DESC
            LIMIT {MAX_THUMBS_PER_RUN}
            """
        )
    if not rows:
        return summary

    sem = asyncio.Semaphore(SH_REQUEST_CONCURRENCY)
    async with httpx.AsyncClient() as client:
        async def _one(r):
            async with sem:
                ok = await _fetch_thumb(client, r["event_id"], r["lon"], r["lat"], r["ts"])
            if ok:
                # URL is relative — the route in vessel_events.py serves it.
                url = f"/v2/map/vessel-events/{r['event_id']}/thumb.png"
                async with db.pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE vessel_events SET s2_thumbnail_url = $1 WHERE event_id = $2",
                        url, r["event_id"],
                    )
            return ok

        results = await asyncio.gather(*[_one(r) for r in rows], return_exceptions=True)

    for res in results:
        summary["attempted"] += 1
        if res is True:
            summary["ok"] += 1
        elif isinstance(res, Exception):
            log.warning("S2 thumb failed: %s", res)

    log.info("S2 confirmation done: %s", summary)
    return summary
