# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations
import io
import json
import math
from typing import Sequence

import mercantile
from PIL import Image, ImageDraw

_SIZE = 1024  # render at 2× then LANCZOS down to 512

_BORDER = (255, 255, 255, 200)  # white stroke — visible against every fill color and basemap
_COLORS: dict[str, tuple[int, ...]] = {
    "offshore_wind": (56, 189, 248, 130),
    "seabed_mining": (217, 70, 239, 130),
    "ccs_storage":   (16, 185, 129, 130),
}
_DEFAULT_FILL = (220, 38, 38, 130)  # oil_gas / fallback

def _build_query(types: list[str] | None, countries: list[str] | None) -> tuple[str, list]:
    """Compose the SQL + params for an offshore-activities tile.

    Bbox is always $1..$4, simplification tolerance is the last arg.
    Optional type/country filters are appended only when provided.

    Guard: only simplify when the polygon's bbox area is at least 16×tol²
    (i.e. >4×tol in each axis). Smaller polygons pass through unsimplified —
    PIL rasterises them at sub-pixel scale and they don't vanish.

    The bbox filter is expanded by the tolerance so that a polygon whose
    simplified geometry retreats slightly inside a tile edge is still fetched
    by the neighbouring tile — preventing the "cut in half" boundary bug.
    """
    # Compute tol_idx upfront so it can be referenced in the WHERE clause.
    n_extra = (1 if types else 0) + (1 if countries else 0)
    tol_idx = 4 + n_extra + 1

    where = [
        f"oa.geom && ST_Expand(ST_SetSRID(ST_MakeEnvelope($1,$2,$3,$4), 4326), ${tol_idx}::float8)",
        "(oa.name IS NOT NULL OR oa.operator IS NOT NULL)",
    ]
    params: list = []
    if types:
        params.append(types)
        where.append(f"oa.activity_type = ANY(${4 + len(params)}::text[])")
    if countries:
        params.append(countries)
        where.append(f"oa.sovereign = ANY(${4 + len(params)}::text[])")
    sql = f"""
SELECT ST_AsGeoJSON(
         CASE
           WHEN ST_Area(ST_Envelope(oa.geom)) > (${tol_idx}::float8 * ${tol_idx}::float8 * 16.0)
             THEN ST_SimplifyPreserveTopology(oa.geom, ${tol_idx}::float8)
           ELSE oa.geom
         END
       )::text AS g,
       oa.activity_type
  FROM offshore_activities oa
 WHERE {' AND '.join(where)}
 ORDER BY ST_Area(oa.geom) DESC
 LIMIT 5000
"""
    return sql, params


def _tolerance_for_zoom(z: int) -> float:
    """Geometry simplification tolerance in degrees, ≈ 2 px on a 512² tile.

    A tile at zoom z spans 360/2^z degrees, so 1 px = 360 / (2^z · 512) ≈ 0.7/2^z.
    Doubled gives ~2 px (sub-pixel for users). Returns 0 at z ≥ 12 — at city scale
    every vertex matters, and the polygons are simple enough that simplification
    saves nothing.
    """
    if z >= 12:
        return 0.0
    return 1.4 / (2 ** z)


def _merc_y(lat: float) -> float:
    r = math.radians(lat)
    return math.log(math.tan(math.pi / 4 + r / 2))


def _project(
    lon: float, lat: float,
    west: float, east: float,
    mn: float, ms: float,
) -> tuple[float, float]:
    px = (lon - west) / (east - west) * _SIZE
    py = (mn - _merc_y(lat)) / (mn - ms) * _SIZE
    return px, py


def _draw_polygon(
    img: Image.Image, draw: ImageDraw.ImageDraw, rings: list[list],
    west: float, east: float, mn: float, ms: float,
    fill: tuple,
    border=_BORDER,
) -> None:
    """Draw a polygon (optionally with holes) onto img/draw.

    rings[0] is the outer ring; rings[1..] are interior holes.
    Sub-pixel polygons (< 2 px extent) are rendered as a 4-px dot so they
    remain visible at low zoom.

    Holed polygons are rendered onto an isolated RGBA layer and
    alpha-composited onto img.  This prevents hole erasing (fill=(0,0,0,0))
    from punching through polygons already drawn on the shared canvas.

    Pass border=None for dense choropleth fills (e.g. arctic-catchments) to
    suppress the heavy white outline that would dominate at low zoom.
    """
    outer = [_project(c[0], c[1], west, east, mn, ms) for c in rings[0]]
    if len(outer) < 3:
        return

    xs = [p[0] for p in outer]
    ys = [p[1] for p in outer]
    if max(xs) - min(xs) < 2 and max(ys) - min(ys) < 2:
        # Sub-pixel polygon — draw as a visible 4-px dot at the centroid
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        r = 4
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=border)
        return

    if not rings[1:]:
        # No holes — draw directly onto the shared canvas (fast path).
        draw.polygon(outer, fill=fill, outline=border, width=(5 if border else 0))
        return

    # Holed polygon — render onto an isolated layer so that writing
    # (0,0,0,0) for holes only erases pixels on THIS layer, never
    # clobbering neighbours already drawn on img.
    layer = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    ldraw = ImageDraw.Draw(layer)
    ldraw.polygon(outer, fill=fill, outline=border, width=(5 if border else 0))
    for hole in rings[1:]:
        pts = [_project(c[0], c[1], west, east, mn, ms) for c in hole]
        if len(pts) >= 3:
            ldraw.polygon(pts, fill=(0, 0, 0, 0), outline=border, width=(3 if border else 0))
    img.alpha_composite(layer)


async def render_tile(
    z: int, x: int, y: int,
    types: list[str] | None,
    conn,
    countries: list[str] | None = None,
) -> bytes:
    bounds = mercantile.bounds(mercantile.Tile(x, y, z))
    west, south, east, north = bounds.west, bounds.south, bounds.east, bounds.north
    # Clamp to Web Mercator poles to avoid log(0)
    mn = _merc_y(min(north, 85.0511))
    ms = _merc_y(max(south, -85.0511))

    tol = _tolerance_for_zoom(z)
    sql, extra_params = _build_query(types, countries)
    rows = await conn.fetch(sql, west, south, east, north, *extra_params, tol)

    img = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for row in rows:
        if not row["g"]:
            continue
        geom = json.loads(row["g"])
        fill = _COLORS.get(row["activity_type"], _DEFAULT_FILL)
        gtype = geom.get("type")
        if gtype == "Polygon":
            _draw_polygon(img, draw, geom["coordinates"], west, east, mn, ms, fill)
        elif gtype == "MultiPolygon":
            for poly in geom["coordinates"]:
                _draw_polygon(img, draw, poly, west, east, mn, ms, fill)

    out = img.resize((512, 512), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Arctic-catchments choropleth raster renderer
# ---------------------------------------------------------------------------
# arctic_ramp is a pure computation module — safe to import at module level.
from services.arctic_ramp import arctic_catchment_color, ARCTIC_VARS  # noqa: E402
# _ARCTIC_MIN_AREA is imported lazily inside render_arctic_tile because
# spatial_v2 imports raster_tiles at its own top level (circular at load time).


def _empty_png() -> bytes:
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


EMPTY_PNG: bytes = _empty_png()


async def render_arctic_tile(z: int, x: int, y: int, variable: str, conn) -> bytes:
    """Rasterise arctic_catchments polygons inside tile (z, x, y).

    Each catchment is filled with the ramp colour for *variable*.  The area
    floor from ``_ARCTIC_MIN_AREA`` is applied so low-zoom tiles touch few
    polygons.  No outline is drawn (border=None) — dense fill wins over
    hairlines at regional scales.

    Returns ``EMPTY_PNG`` (transparent 512×512) when no catchments fall inside
    the tile.  Always returns valid PNG bytes.
    """
    # Lazy import: spatial_v2 imports raster_tiles at its top level, so a
    # module-level import would be circular.  By call-time both modules are
    # fully initialized, so this is safe.
    from routers.spatial_v2 import _ARCTIC_MIN_AREA  # noqa: PLC0415

    # Whitelist variable against known keys — prevents SQL injection.
    if variable not in ARCTIC_VARS:
        variable = "ocs_mean"

    bounds = mercantile.bounds(mercantile.Tile(x, y, z))
    west, south, east, north = bounds.west, bounds.south, bounds.east, bounds.north
    mn = _merc_y(min(north, 85.0511))
    ms = _merc_y(max(south, -85.0511))
    tol = _tolerance_for_zoom(z)              # degrees
    min_area = _ARCTIC_MIN_AREA.get(z, 0.0)  # km² floor shared with MVT tiles

    # variable column interpolated by name from the ARCTIC_VARS whitelist — safe.
    sql = f"""
SELECT ST_AsGeoJSON(
         CASE WHEN $5::float8 > 0
                   AND ST_Area(ST_Envelope(geom)) > ($5::float8 * $5::float8 * 16.0)
              THEN ST_SimplifyPreserveTopology(geom, $5::float8)
              ELSE geom END
       )::text AS g,
       {variable} AS val
  FROM arctic_catchments
 WHERE geom && ST_Expand(ST_SetSRID(ST_MakeEnvelope($1,$2,$3,$4), 4326), $5::float8)
   AND area_km2 >= $6::float8
 ORDER BY area_km2 DESC
 LIMIT 8000
"""
    rows = await conn.fetch(sql, west, south, east, north, tol, min_area)

    img = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    drew = False

    for row in rows:
        if not row["g"]:
            continue
        fill = arctic_catchment_color(row["val"], variable)
        geom = json.loads(row["g"])
        gtype = geom.get("type")
        if gtype == "Polygon":
            _draw_polygon(img, draw, geom["coordinates"], west, east, mn, ms, fill, border=None)
            drew = True
        elif gtype == "MultiPolygon":
            for poly in geom["coordinates"]:
                _draw_polygon(img, draw, poly, west, east, mn, ms, fill, border=None)
            drew = True

    if not drew:
        return EMPTY_PNG

    out = img.resize((512, 512), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()
