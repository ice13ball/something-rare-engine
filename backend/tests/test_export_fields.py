# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import pytest
from services.export_query import Aoi, parse_aoi
from services.export_fields import cells_in_aoi, normalize_lons


def test_normalize_lons():
    assert normalize_lons([20.5, 200.0, 359.5, 180.0]) == [20.5, -160.0, -0.5, 180.0]


def test_cells_in_bbox():
    lats = [0.0, 10.0, 20.0, 30.0]
    lons = [0.0, 10.0, 20.0]
    aoi = parse_aoi("5,5,25,25", None, None)  # lng 5..25, lat 5..25
    got = {(i, j) for (i, j, la, lo) in cells_in_aoi(lats, lons, aoi)}
    # lats 10,20 (idx 1,2); lons 10,20 (idx 1,2)
    assert got == {(1, 1), (1, 2), (2, 1), (2, 2)}


def test_cells_in_poly_uses_polygon_extent():
    lats = [0.0, 10.0, 20.0]
    lons = [0.0, 10.0, 20.0]
    aoi = parse_aoi(None, '{"type":"Polygon","coordinates":[[[5,5],[25,5],[25,25],[5,25],[5,5]]]}', None)
    got = {(i, j) for (i, j, la, lo) in cells_in_aoi(lats, lons, aoi)}
    assert (1, 1) in got and (2, 2) in got and (0, 0) not in got


def test_cells_aoi_raises_valueerror():
    """cells_in_aoi still raises ValueError for 'cells' kind — the guard remains in place."""
    aoi = parse_aoi(None, None, "cell1,cell2")
    with pytest.raises(ValueError, match="cells AOI not supported"):
        cells_in_aoi([0.0, 10.0], [0.0, 10.0], aoi)


# ─── _bbox_row_to_aoi (pure helper, no DB) ──────────────────────────────────

def test_bbox_row_to_aoi_builds_correct_aoi():
    from routers.export import _bbox_row_to_aoi
    row = (-10.0, -20.0, 10.0, 20.0)
    aoi = _bbox_row_to_aoi(row)
    assert aoi == Aoi(kind="bbox", bbox=(-10.0, -20.0, 10.0, 20.0))


def test_bbox_row_to_aoi_returns_none_on_null_row():
    from routers.export import _bbox_row_to_aoi
    assert _bbox_row_to_aoi(None) is None


def test_bbox_row_to_aoi_returns_none_on_null_extent():
    """DB returns a row but ST_Extent was NULL (no matching cells)."""
    from routers.export import _bbox_row_to_aoi
    # Simulate asyncpg row where first column is None
    assert _bbox_row_to_aoi((None, None, None, None)) is None


def test_router_import_clean():
    """Confirm routers.export imports without error and exposes routes."""
    from routers.export import router
    assert len(router.routes) > 0
