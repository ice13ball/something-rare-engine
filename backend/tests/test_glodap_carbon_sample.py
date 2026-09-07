# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Tests for glodap_carbon: lon normalisation, sample(), and _load_grid() fixture."""
import numpy as np
import pytest

from services import glodap_carbon as gc


def test_normalize_lon_rolls_to_minus180():
    data = np.arange(4, dtype="float32").reshape(1, 1, 4)   # (depth, lat, lon)
    lon = np.array([20.5, 110.5, 200.5, 290.5])             # 20°E-origin, >180 present
    d2, l2 = gc.normalize_lon(data, lon)
    assert l2.min() >= -180 and l2.max() <= 180
    assert np.all(np.diff(l2) > 0)                          # monotonically increasing


def test_sample_land_returns_none(monkeypatch):
    # A grid that is all-NaN → any sample is None (land/fill).
    class G:
        lats   = np.array([0.0])
        lons   = np.array([0.0])
        depths = np.array([0.0])
        data   = np.full((1, 1, 1), np.nan, "float32")

    monkeypatch.setattr(gc, "_load_grid", lambda v: G())
    assert gc.sample("dic", 0.0, 0.0, 0.0) is None


def test_load_grid_real_fixture(tmp_path, monkeypatch):
    import pathlib
    import shutil

    pytest.importorskip("xarray")
    pytest.importorskip("netCDF4")

    src = (
        pathlib.Path(__file__).parent
        / "fixtures"
        / "glodap_carbon"
        / "GLODAPv2.2016b.TCO2.slice.nc"
    )
    # _load_grid globs for the exact nc_file name defined in CARBON_VARS["dic"].
    shutil.copy(src, tmp_path / "GLODAPv2.2016b.TCO2.nc")
    monkeypatch.setattr(gc, "RAW_DIR", tmp_path)
    gc._GRID_CACHE.clear()

    g = gc._load_grid("dic")
    assert g is not None
    assert g.data.shape[0] == 33                          # 33 depth levels
    assert g.lons.min() >= -180 and g.lons.max() <= 180  # normalized
    assert (g.lons[1:] > g.lons[:-1]).all()              # sorted ascending
    assert np.isfinite(g.data[0]).any()                  # surface ocean has data
    # This trimmed slice fixture predates Input_N — a real GLODAP file carries it,
    # but a grid loaded without it must degrade to None, not crash.
    assert g.counts is None


def _write_synthetic_glodap_nc(path, tco2, input_n, lat, lon, depth):
    """Build a minimal GLODAPv2-shaped NetCDF (TCO2/Input_N/Depth/lat/lon) so the
    Input_N-carrying path in _load_grid can be exercised without the real tarball."""
    import xarray as xr

    ds = xr.Dataset(
        {
            "TCO2": (("depth_surface", "lat", "lon"), tco2.astype("float32")),
            "Input_N": (("depth_surface", "lat", "lon"), input_n.astype("float32")),
            "Depth": (("depth_surface",), depth.astype("float64")),
        },
        coords={"lat": lat.astype("float64"), "lon": lon.astype("float64")},
    )
    ds.to_netcdf(path)


def test_grid_carries_the_per_cell_observation_count(tmp_path, monkeypatch):
    """GLODAP ships Input_N in every file we already open. Without it a cell
    backed by one measurement looks identical to a cell backed by hundreds."""
    pytest.importorskip("xarray")
    pytest.importorskip("netCDF4")

    lon = np.array([20.5, 110.5, 200.5, 290.5])
    lat = np.array([0.0])
    depth = np.array([0.0])
    tco2 = np.array([[[1000.0, 1001.0, 1002.0, 1003.0]]])
    input_n = np.array([[[5.0, 12.0, 3.0, 40.0]]])

    _write_synthetic_glodap_nc(
        tmp_path / "GLODAPv2.2016b.TCO2.nc", tco2, input_n, lat, lon, depth,
    )
    monkeypatch.setattr(gc, "RAW_DIR", tmp_path)
    gc._GRID_CACHE.clear()

    g = gc._load_grid("dic")
    assert g is not None
    assert getattr(g, "counts", None) is not None
    assert g.counts.shape == g.data.shape


def test_counts_are_rolled_with_the_same_lon_permutation_as_the_data(tmp_path, monkeypatch):
    """The GLODAP grid runs 20.5°E → 379.5°E, so normalize_lon rolls columns to
    sort it ascending. If counts is rolled using an already-sorted lon axis
    (instead of the original one), it lands on a different permutation than
    the values it is supposed to describe — silent per-cell corruption."""
    pytest.importorskip("xarray")
    pytest.importorskip("netCDF4")

    # Crosses the 180° wrap non-trivially: raw -> wrapped -> sort order [2, 1, 0, 3].
    lon = np.array([20.5, 379.5, 200.5, 100.5])
    lat = np.array([0.0])
    depth = np.array([0.0])
    # Distinct, non-overlapping value ranges so a permutation mismatch can't
    # hide behind coincidentally-equal numbers.
    tco2 = np.array([[[1000.0, 1001.0, 1002.0, 1003.0]]])
    input_n = np.array([[[500.0, 501.0, 502.0, 503.0]]])

    _write_synthetic_glodap_nc(
        tmp_path / "GLODAPv2.2016b.TCO2.nc", tco2, input_n, lat, lon, depth,
    )
    monkeypatch.setattr(gc, "RAW_DIR", tmp_path)
    gc._GRID_CACHE.clear()

    g = gc._load_grid("dic")
    assert g is not None
    assert g.counts is not None
    # Both arrays must have travelled through the identical column permutation:
    # subtracting each series' own offset should yield the same index sequence.
    assert np.array_equal(g.data[0, 0, :] - 1000.0, g.counts[0, 0, :] - 500.0)


def test_sample_count_is_none_when_grid_has_no_counts(monkeypatch):
    class G:
        lats   = np.array([0.0])
        lons   = np.array([0.0])
        depths = np.array([0.0])
        data   = np.array([[[42.0]]], dtype="float32")
        counts = None

    monkeypatch.setattr(gc, "_load_grid", lambda v: G())
    assert gc.sample_count("dic", 0.0, 0.0, 0.0) is None


def test_sample_count_is_none_on_land(monkeypatch):
    class G:
        lats   = np.array([0.0])
        lons   = np.array([0.0])
        depths = np.array([0.0])
        data   = np.array([[[np.nan]]], dtype="float32")
        counts = np.full((1, 1, 1), np.nan, "float32")

    monkeypatch.setattr(gc, "_load_grid", lambda v: G())
    assert gc.sample_count("dic", 0.0, 0.0, 0.0) is None


def test_sample_count_returns_the_observation_count(monkeypatch):
    class G:
        lats   = np.array([0.0])
        lons   = np.array([0.0])
        depths = np.array([0.0])
        data   = np.array([[[2100.0]]], dtype="float32")
        counts = np.array([[[37.0]]], dtype="float32")

    monkeypatch.setattr(gc, "_load_grid", lambda v: G())
    assert gc.sample_count("dic", 0.0, 0.0, 0.0) == 37.0


def test_sample_count_is_none_off_grid(monkeypatch):
    """When the grid can't be loaded at all (no baked file yet, or an older
    extract that never carried Input_N), sample_count must return None
    rather than raising or fabricating a count."""
    monkeypatch.setattr(gc, "_load_grid", lambda v: None)
    assert gc.sample_count("dic", 47.0, 8.5, 0.0) is None
