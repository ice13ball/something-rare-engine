# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os
import numpy as np
from backend.services import cascade_grid as g

CLIP = os.path.join(os.path.dirname(__file__), "fixtures", "cascade", "cascade_grid_clip.txt")

def test_parse_ascii_header_and_shape():
    hdr, arr = g._parse_ascii(open(CLIP, encoding="latin-1").read())
    assert hdr["ncols"] == 10 and hdr["nrows"] == 4
    assert hdr["cellsize"] == 5000.0
    assert arr.shape == (4, 10)

def test_proj_string_is_lat_ts_75():
    assert "lat_ts=75" in g.PROJ4 and "lon_0=0" in g.PROJ4

def test_sample_out_of_grid_is_none():
    # a point far outside the Arctic polar grid returns None
    assert g.sample(-40.0, 10.0, "oc") is None


class _StubTransformer:
    """Deterministic stand-in for pyproj.Transformer — maps chosen
    (lon, lat) inputs to chosen polar-stereographic (x, y) outputs so the
    row/col arithmetic in sample() can be verified without depending on
    pyproj's real projection math."""

    _MAP = {
        (10.0, 80.0): (5.0, 25.0),        # -> row 0, col 0 -> known value
        (20.0, 81.0): (15.0, 15.0),       # -> row 1, col 1 -> NODATA cell
        (30.0, 82.0): (1000.0, 1000.0),   # -> outside grid bounds
    }

    def transform(self, lon, lat):
        return self._MAP[(lon, lat)]


def test_sample_row_col_math_with_stub_transformer():
    # Tiny synthetic 3x3 grid with a known xllcorner/yllcorner/cellsize so
    # the row/col derivation (y_top = yllcorner + nrows*cellsize; row =
    # int((y_top-y)/cellsize); col = int((x-xllcorner)/cellsize)) is exercised
    # deterministically, independent of pyproj's actual projection output.
    hdr = {
        "ncols": 3, "nrows": 3,
        "xllcorner": 0.0, "yllcorner": 0.0,
        "cellsize": 10.0, "nodata_value": -9999.0,
    }
    arr = np.array([
        [1.0, 2.0, 3.0],
        [4.0, -9999.0, 6.0],
        [7.0, 8.0, 9.0],
    ])

    g.reset_cache()
    g._GRIDS["oc"] = (hdr, arr)
    g._TF = _StubTransformer()
    try:
        # (lon=10, lat=80) -> stub (x=5, y=25) -> row 0, col 0 -> value 1.0
        assert g.sample(80.0, 10.0, "oc") == 1.0
        # (lon=20, lat=81) -> stub (x=15, y=15) -> row 1, col 1 -> NODATA -> None
        assert g.sample(81.0, 20.0, "oc") is None
        # (lon=30, lat=82) -> stub (x=1000, y=1000) -> out of grid bounds -> None
        assert g.sample(82.0, 30.0, "oc") is None
    finally:
        g.reset_cache()
