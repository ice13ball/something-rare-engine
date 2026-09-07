# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""AU AODN — ACMA submarine cable protection zone fetcher.

Source: CSIRO GeoServer becrc workspace, layer
becrc_wp2_acma_submarine_cable_locations_2021.
Licence: CC-BY 4.0. 16 features (3 protection zones around Perth + Sydney).
Dataset is frozen ("Current as of 2021") — re-sync rarely produces deltas.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

import httpx

log = logging.getLogger(__name__)

ENDPOINT = "https://www.cmar.csiro.au/geoserver/becrc/wfs"
TYPENAME = "becrc:becrc_wp2_acma_submarine_cable_locations_2021"
TIMEOUT_S = 60.0


async def fetch_au_cables_features() -> AsyncGenerator[list[dict], None]:
    """Yield AU cable features (single batch, 16 features expected).

    Each dict has:
        object_id    int
        cable        str | None  (full cable name)
        abbrev       str | None  (e.g. "AJC")
        coordinates  list (GeoJSON MultiLineString coords)
    """
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": TYPENAME,
        "outputFormat": "application/json",
        "SRSName": "EPSG:4326",
    }
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        try:
            r = await client.get(ENDPOINT, params=params)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as exc:
            log.warning("au_cables: WFS fetch failed — %s", exc)
            return
        except ValueError as exc:
            log.warning("au_cables: response not JSON — %s", exc)
            return

    features_in = data.get("features", []) or []
    if not features_in:
        log.warning("au_cables: WFS returned 0 features")
        return

    page: list[dict] = []
    for feat in features_in:
        props = feat.get("properties", {}) or {}
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if not coords:
            continue
        if gtype == "LineString":
            coords = [coords]
        elif gtype != "MultiLineString":
            log.debug("au_cables: skipping oid=%s — unexpected geometry type %s", props.get("objectid", "?"), gtype)
            continue

        oid = props.get("objectid")
        if oid is None:
            continue
        try:
            oid_int = int(oid)
        except (ValueError, TypeError):
            continue

        page.append({
            "object_id":   oid_int,
            "cable":       _coerce_str(props.get("cable")),
            "abbrev":      _coerce_str(props.get("abbrev")),
            "coordinates": coords,
        })

    yield page


def _coerce_str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def coords_to_geojson_multilinestring(coords: list) -> dict:
    return {"type": "MultiLineString", "coordinates": coords}
