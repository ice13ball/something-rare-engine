# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""acidification._load_grid()/_aux_grid() open GLODAP NetCDF files with `xr.open_dataset`.

Measured 2026-09-18 (see session report, not re-derived here): the on-disk GLODAP grid
is 33x180x360 float64, unpacked, uncompressed (~17 MB/variable) — confirmed against the
real fixture `backend/tests/fixtures/glodap_carbon/GLODAPv2.2016b.TCO2.slice.nc`'s
encoding (dtype float64, zlib=False, _FillValue=-999.0). A synthetic full-resolution file
of that exact encoding, read the way `_load_grid`/`_aux_grid` read it, peaked at ~265-272 MB
RSS across a 9-variable sequential read (dominated by python/xarray/netCDF4 import
overhead ~90 MB + the extracted numpy arrays themselves) — wrapping the read in a `with`
block changed that number by less than run-to-run noise. So this suite does NOT assert an
RSS reduction (there isn't one to assert); it pins the two things that changed on purpose:

  1. the `with` block actually closes the Dataset (no leaked file handle if a caller starts
     depending on that instead of GC), and
  2. the values read through it are BIT-IDENTICAL to what the previous open()/close() (or
     open()-and-never-close()) style produced — the whole point of a hygiene-only change is
     that it must not perturb a single published number.

Does NOT cover: the real GLODAP tarball's actual files (only available on the VPS) or the
6 GB/3.3 GB RSS incident itself (that was never reproduced locally; this suite reproduces
the read *pattern* on a same-shaped, same-encoded synthetic file instead).
"""
from __future__ import annotations

import pathlib

import numpy as np
import pytest

xr = pytest.importorskip("xarray")
pytest.importorskip("netCDF4")

from services import acidification as acid
from services import glodap_carbon


def _write_synthetic_omega_nc(path: pathlib.Path, varname: str, ny: int = 6, nx: int = 8,
                               depths=(0.0, 100.0, 500.0)) -> None:
    """Build a GLODAP-shaped file: same variable/dim names, same encoding (float64,
    unpacked, _FillValue sentinel) as the real fixture, at a fixture-sized resolution."""
    rng = np.random.default_rng(42)
    lat = np.linspace(-2.5, 2.5, ny)
    lon = np.linspace(20.5, 20.5 + nx - 1, nx)   # GLODAP's 20.5E-origin axis
    depth = np.asarray(depths, dtype="float64")
    data = rng.normal(loc=1.0, scale=0.3, size=(len(depth), ny, nx)).astype("float64")
    data[:, 0, 0] = -999.0   # a land/fill cell, same sentinel the real files use
    ds = xr.Dataset(
        {varname: (("depth_surface", "lat", "lon"), data),
         "Depth": (("depth_surface",), depth)},
        coords={"lat": lat.astype("float64"), "lon": lon.astype("float64")},
    )
    ds[varname].encoding = {"_FillValue": -999.0, "zlib": False, "dtype": "float64"}
    ds.to_netcdf(path)


def _load_grid_old_style(path, var, depth_name="Depth"):
    """The exact read _load_grid() performed BEFORE this session's `with`-block change
    (open, read, never explicitly close — relies on GC)."""
    ds = xr.open_dataset(path)
    arr = np.asarray(ds[var].values, dtype="float32")
    while arr.ndim > 3:
        arr = arr.squeeze(axis=0)
    lats = np.asarray(ds["lat"].values, dtype="float64")
    lons = np.asarray(ds["lon"].values, dtype="float64")
    depths = np.asarray(ds[depth_name].values, dtype="float64")
    return arr, lats, lons, depths


def _aux_grid_old_style(path, var):
    """The exact read _aux_grid() performed BEFORE this session's `with`-block change
    (open, read, explicit ds.close())."""
    ds = xr.open_dataset(path)
    arr = np.asarray(ds[var].values, dtype="float64")
    while arr.ndim > 3:
        arr = arr.squeeze(axis=0)
    lons = np.asarray(ds["lon"].values, dtype="float64")
    ds.close()
    return arr, lons


@pytest.fixture()
def omega_nc(tmp_path, monkeypatch):
    fn = "GLODAPv2.2016b.OmegaA.nc"
    _write_synthetic_omega_nc(tmp_path / fn, "OmegaA")
    monkeypatch.setattr(glodap_carbon, "RAW_DIR", tmp_path)
    acid._GRID_CACHE.clear()
    yield tmp_path / fn
    acid._GRID_CACHE.clear()


def test_load_grid_with_block_matches_old_open_close_pattern(omega_nc):
    """Numerical output must not change: the new `with`-block _load_grid() must produce
    the exact same arrays (same dtype, same values including the -999.0 -> untouched-until-
    normalize_lon sentinel) as the pre-change open()/never-close() pattern."""
    new_arr, new_lats, new_lons, new_depths = None, None, None, None

    g = acid._load_grid("aragonite")
    assert g is not None
    new_arr, new_lats, new_lons, new_depths = g.data, g.lats, g.lons, g.depths

    old_arr, old_lats, old_lons, old_depths = _load_grid_old_style(omega_nc, "OmegaA")
    old_arr, old_lons = glodap_carbon.normalize_lon(old_arr, old_lons)

    assert new_arr.dtype == old_arr.dtype == np.dtype("float32")
    np.testing.assert_array_equal(new_arr, old_arr)          # bit-identical, no tolerance needed
    np.testing.assert_array_equal(new_lats, old_lats)
    np.testing.assert_array_equal(new_lons, old_lons)
    np.testing.assert_array_equal(new_depths, old_depths)


def test_load_grid_with_block_actually_closes_the_file(omega_nc, monkeypatch):
    """Pin the change itself: `with xr.open_dataset(...)` must call `__exit__`/close on the
    Dataset. A regression back to a bare `ds = xr.open_dataset(...)` (no context manager)
    would make this fail, since a plain object has no `__exit__` to intercept."""
    calls = {"opened": 0, "closed": 0}
    real_open_dataset = xr.open_dataset
    real_close = xr.Dataset.close

    def spy_open_dataset(*args, **kwargs):
        calls["opened"] += 1
        return real_open_dataset(*args, **kwargs)

    def spy_close(self, *args, **kwargs):
        calls["closed"] += 1
        return real_close(self, *args, **kwargs)

    monkeypatch.setattr(xr, "open_dataset", spy_open_dataset)
    monkeypatch.setattr(xr.Dataset, "close", spy_close)
    g = acid._load_grid("aragonite")
    assert g is not None
    assert calls["opened"] == 1
    assert calls["closed"] == 1, "with-block must close the Dataset exactly once"


def test_aux_grid_with_block_matches_old_open_close_pattern(tmp_path, monkeypatch):
    """Same equality proof for _aux_grid() (used by omega_grid() for DIC/TAlk/temp/sal/PO4/Si)."""
    fn = "GLODAPv2.2016b.TAlk.nc"
    _write_synthetic_omega_nc(tmp_path / fn, "TAlk")
    monkeypatch.setattr(glodap_carbon, "RAW_DIR", tmp_path)

    new_arr = acid._aux_grid(fn, "TAlk")
    assert new_arr is not None

    old_arr, old_lons = _aux_grid_old_style(tmp_path / fn, "TAlk")
    old_arr, _ = glodap_carbon.normalize_lon(old_arr, old_lons)

    assert new_arr.dtype == old_arr.dtype == np.dtype("float64")
    np.testing.assert_array_equal(new_arr, old_arr)


def test_aux_grid_missing_file_still_returns_none(tmp_path, monkeypatch):
    """Unrelated to the `with`-block change, but cheap to pin: a missing source file must
    still degrade to None (no file to open at all, so the with-block is never entered)."""
    monkeypatch.setattr(glodap_carbon, "RAW_DIR", tmp_path)
    assert acid._aux_grid("GLODAPv2.2016b.DoesNotExist.nc", "X") is None
