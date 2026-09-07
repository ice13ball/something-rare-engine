# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import numpy as np
import pytest
from services import bathymetry_grid_export as bge
from services import bathymetry_stats as bs

def test_downsample_and_sample(tmp_path, monkeypatch):
    # synthetic 4x8 global elevation grid, lat descending 90..-90, lon -180..180
    lats = np.linspace(90, -90, 4)
    lons = np.linspace(-180, 180, 8)
    # depth = -1000 in the ocean row, +500 land row
    elev = np.where(np.arange(4)[:, None] % 2 == 0, -1000.0, 500.0) * np.ones((4, 8))
    monkeypatch.setattr(bge, "GRID_DIR", tmp_path)
    n = bge._write_holding(lats, lons, elev.astype("float32"))
    assert n == 32
    bge.reset_cache()
    g = bge._load_grid("depth_m")
    assert g.lats[0] > g.lats[-1]                 # N→S
    # nearest an ocean cell (row 0) → -1000; land cell (row 1) → +500
    assert bge.sample("depth_m", 90.0, -180.0, None) == -1000.0
    assert bge.sample("depth_m", 30.0, 0.0, None) in (-1000.0, 500.0)

def test_missing_holding_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(bge, "GRID_DIR", tmp_path)  # empty
    bge.reset_cache()
    assert bge._load_grid("depth_m") is None


def test_bake_uses_strided_decimation_no_full_materialize(tmp_path, monkeypatch):
    """Locks the fix for the full-grid OOM: bake must use lazy strided isel(),
    never coarsen().mean() (which forces materializing the entire source grid).
    Uses a tiny synthetic in-memory Dataset instead of the real 4GB GEBCO file."""
    xr = pytest.importorskip("xarray")
    # native spacing (0.02) finer than STEP_DEG (0.05) so stride > 1 is exercised.
    lat = np.arange(-1.0, 1.001, 0.02)   # ascending on purpose — exercises the N->S flip
    lon = np.arange(-2.0, 2.001, 0.02)
    elev = (np.arange(lat.size)[:, None] * 10 + np.arange(lon.size)[None, :]).astype("float64")
    ds = xr.Dataset({bs._ELEV_VAR: ((bs._LAT, bs._LON), elev)},
                     coords={bs._LAT: lat, bs._LON: lon})

    monkeypatch.setattr(bge, "GRID_DIR", tmp_path)
    monkeypatch.setattr(bs, "ensure_holdings", lambda force=False: True)
    monkeypatch.setattr(bs, "_elev_path", lambda: tmp_path / "no_such_elev.nc")
    monkeypatch.setattr(xr, "open_dataset", lambda path: ds)

    n = bge.bake_bathymetry_grid(force=True)

    native = abs(float(lat[1] - lat[0]))
    stride = max(1, int(round(bge.STEP_DEG / native)))
    expected_lats = lat[::stride]
    expected_lons = lon[::stride]
    expected_elev = elev[::stride, ::stride]
    if expected_lats[0] < expected_lats[-1]:          # ensure N->S, same as source
        expected_lats = expected_lats[::-1]
        expected_elev = expected_elev[::-1, :]

    assert n == expected_elev.size
    bge.reset_cache()
    g = bge._load_grid("depth_m")
    assert g.lats[0] > g.lats[-1]                     # N->S
    np.testing.assert_allclose(g.lats, expected_lats)
    np.testing.assert_allclose(g.lons, expected_lons)
    np.testing.assert_allclose(g._elev, expected_elev)
