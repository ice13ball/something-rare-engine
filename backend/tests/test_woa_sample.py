# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import numpy as np
import pytest
from services import woa_climatology as woa


class _StubField:
    """Mimics the (lat, lon, depth) lookup surface the sampler needs."""
    def __init__(self):
        self.lats = np.array([-1.0, 0.0, 1.0])      # 1° cells
        self.lons = np.array([0.0, 1.0, 2.0])
        self.depths = np.array([0.0, 100.0, 1000.0])
        self.data = np.empty((3, 3, 3), dtype="float32")
        for di in range(3):
            for la in range(3):
                for lo in range(3):
                    self.data[di, la, lo] = di * 100 + la * 10 + lo
        self.data[0, 0, 0] = np.nan  # land


def test_nearest_cell_and_depth(monkeypatch):
    stub = _StubField()
    monkeypatch.setattr(woa, "_load_grid", lambda var, tt: stub)
    assert woa.sample("temperature", lat=0.1, lon=0.9, depth_m=90.0, month=1) == pytest.approx(111.0)


def test_land_returns_none(monkeypatch):
    stub = _StubField()
    monkeypatch.setattr(woa, "_load_grid", lambda var, tt: stub)
    assert woa.sample("temperature", lat=-1.0, lon=0.0, depth_m=0.0, month=1) is None


def test_deep_uses_annual_when_below_monthly_limit(monkeypatch):
    calls = []
    monkeypatch.setattr(woa, "_load_grid", lambda var, tt: (calls.append(tt) or _StubField()))
    woa.sample("temperature", lat=0.0, lon=0.0, depth_m=1600.0, month=5)
    assert 0 in calls  # annual (tt=0) requested for deep sample


def test_monthly_used_in_upper_ocean(monkeypatch):
    calls = []
    monkeypatch.setattr(woa, "_load_grid", lambda var, tt: (calls.append(tt) or _StubField()))
    woa.sample("temperature", lat=0.0, lon=0.0, depth_m=50.0, month=5)
    assert 5 in calls  # monthly field requested in the upper ocean
