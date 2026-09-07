# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""NOAA Marine Cadastre — paginated fetcher for the Submarine Cables FeatureServer.

Source: https://coast.noaa.gov/arcgis/rest/services/Hosted/SubmarineCables/FeatureServer/0
Owner: marinecadastre_noaa (joint NOAA/BOEM portal).
2,816 cable corridors, paginated 1000 rows per request.
Yields: list[dict] — one page of normalised feature dicts at a time.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx

log = logging.getLogger(__name__)

ENDPOINT = (
    "https://coast.noaa.gov/arcgis/rest/services/"
    "Hosted/SubmarineCables/FeatureServer/0/query"
)
PAGE_SIZE = 1000
TIMEOUT_S = 60.0


async def fetch_noaa_cables_pages() -> AsyncIterator[list[dict]]:
    """Yield pages of NOAA Marine Cadastre cable features.

    Each yielded item is a list of dicts:
        {
            "object_id":    int,
            "short_name":   str | None,
            "cable_system": str | None,
            "owner":        str | None,
            "status":       str | None,
            "region":       str | None,
            "shape_length": float | None,
            "rings":        list[list[list[float]]],   # ArcGIS polygon rings
        }

    Pagination: ArcGIS uses resultOffset + resultRecordCount.
    Stops when the response sets exceededTransferLimit=False or returns 0 features.
    """
    offset = 0
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        while True:
            params = {
                "where": "1=1",
                "outFields": (
                    "objectid,shortname,cablesystem,owner,status,region,SHAPE__Length"
                ),
                "outSR": "4326",
                "f": "json",
                "resultOffset": offset,
                "resultRecordCount": PAGE_SIZE,
            }
            r = await client.get(ENDPOINT, params=params)
            r.raise_for_status()
            data = r.json()
            features = data.get("features", []) or []
            if not features:
                return

            page: list[dict] = []
            for feat in features:
                attrs = feat.get("attributes", {}) or {}
                geom = feat.get("geometry", {}) or {}
                rings = geom.get("rings")
                if not rings:
                    continue
                page.append({
                    "object_id":    attrs.get("objectid"),
                    "short_name":   _coerce_str(attrs.get("shortname")),
                    "cable_system": _coerce_str(attrs.get("cablesystem")),
                    "owner":        _coerce_str(attrs.get("owner")),
                    "status":       _coerce_str(attrs.get("status")),
                    "region":       _coerce_str(attrs.get("region")),
                    "shape_length": _coerce_float(attrs.get("SHAPE__Length")),
                    "rings":        rings,
                })
            yield page

            if not data.get("exceededTransferLimit"):
                return
            offset += PAGE_SIZE


def _coerce_str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _coerce_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def rings_to_geojson_polygon(rings: list[list[list[float]]]) -> dict:
    """Convert ArcGIS polygon rings to a GeoJSON Polygon (single).

    ArcGIS publishes cable polygons as a single outer ring per feature in
    practice — but rings[] could contain multiple. We treat ring[0] as outer
    and the rest as holes. Most NOAA cable features are simple corridors
    with one ring; defensive handling kept anyway.
    """
    if not rings:
        raise ValueError("empty rings")
    return {
        "type": "Polygon",
        "coordinates": rings,
    }
