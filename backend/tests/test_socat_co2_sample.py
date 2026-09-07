# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import numpy as np
import pytest
import pathlib
import shutil

from services import socat_co2 as sc


def test_sample_land_returns_none(monkeypatch):
    class G:
        lats = np.array([0.0])
        lons = np.array([0.0])
        decades = [0]
        data = np.full((1, 1, 1), np.nan, "float32")

    monkeypatch.setattr(sc, "_load_grid", lambda v: G())
    assert sc.sample("fco2", 0.0, 0.0, 0) is None


def test_load_grid_real_fixture(tmp_path, monkeypatch):
    pytest.importorskip("xarray")
    pytest.importorskip("netCDF4")
    src = pathlib.Path(__file__).parent / "fixtures" / "socat_co2" / "SOCATv2026_decadal.slice.nc"
    shutil.copy(src, tmp_path / sc.NC_FILE)
    monkeypatch.setattr(sc, "RAW_DIR", tmp_path)
    sc._GRID_CACHE.clear()
    g = sc._load_grid("fco2")
    assert g is not None
    assert g.data.shape[0] == 6                        # 6 decades
    assert g.lons.min() >= -180 and g.lons.max() <= 180
    assert (g.lons[1:] > g.lons[:-1]).all()            # ascending
