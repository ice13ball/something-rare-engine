# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import json

from services.export_query import Aoi


def normalize_lons(lons) -> list[float]:
    return [(x - 360.0) if x > 180.0 else float(x) for x in lons]


def _poly_bbox(poly_geojson: str) -> tuple[float, float, float, float]:
    coords = json.loads(poly_geojson)["coordinates"][0]
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return min(xs), min(ys), max(xs), max(ys)


def cells_in_aoi(lats, lons, aoi: Aoi) -> list[tuple[int, int, float, float]]:
    """Grid nodes inside the AOI. `lons` MUST be pre-normalized to -180..180.

    poly is approximated by its bounding box here (exact point-in-polygon is done
    in the caller when shapely is available; the bbox keeps this dependency-free
    and is a safe superset — caller may refine).
    """
    if aoi.kind == "bbox":
        minx, miny, maxx, maxy = aoi.bbox  # type: ignore[misc]
    elif aoi.kind == "poly":
        minx, miny, maxx, maxy = _poly_bbox(aoi.poly_geojson)  # type: ignore[arg-type]
    else:
        raise ValueError("cells AOI not supported for field sources")
    out: list[tuple[int, int, float, float]] = []
    for i, la in enumerate(lats):
        if la < miny or la > maxy:
            continue
        for j, lo in enumerate(lons):
            if lo < minx or lo > maxx:
                continue
            out.append((i, j, float(la), float(lo)))
    return out
