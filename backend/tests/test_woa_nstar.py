# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Derived WOA variable N* = nitrate - 16 x phosphate, run against a small REAL cut
of the WOA23 annual 1-degree files (public domain; 8-14N, 58-66E, depths 0/500/1000 m).
The expected values are recomputed here with xarray + numpy, independently of the
module under test."""
import asyncio
import contextlib
import shutil
import pathlib

import numpy as np
import pytest
import xarray as xr
from PIL import Image

from services import woa_climatology as woa

FIX = pathlib.Path(__file__).parent / "fixtures" / "woa_nstar"


@pytest.fixture()
def cache(tmp_path, monkeypatch):
    """A WOA cache dir laid out like the VPS one, holding only the fixture cut."""
    for var, code in (("nitrate", "n"), ("phosphate", "p")):
        d = tmp_path / var
        d.mkdir()
        shutil.copy(FIX / f"woa23_{var}_cut.nc", d / f"woa23_all_{code}00_01.nc")
    monkeypatch.setattr(woa, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(woa, "BAKE_DIR", tmp_path / "baked")
    monkeypatch.setattr(woa, "_GRID_CACHE", {})
    # Never touch the network: the fixture is all there is.
    monkeypatch.setattr(woa, "ensure_grid", lambda v, tt: woa._local_path(v, tt) if woa._local_path(v, tt).is_file() else None)
    monkeypatch.setattr(woa, "DISPLAY_DEPTHS", [0, 500, 1000])
    return tmp_path


def _raw(var, an):
    ds = xr.open_dataset(FIX / f"woa23_{var}_cut.nc", decode_times=False)
    arr = ds[an].squeeze().values.astype("float64")
    out = arr, ds["lat"].values, ds["lon"].values, ds["depth"].values
    ds.close()
    return out


def test_nstar_equals_nitrate_minus_16_phosphate(cache):
    n, lats, lons, deps = _raw("nitrate", "n_an")
    p, *_ = _raw("phosphate", "p_an")
    expected = n - 16.0 * p
    assert np.isfinite(expected).all() and expected.min() < expected.max()
    for di in range(len(deps)):
        for la in (0, 3, 5):
            for lo in (0, 4, 7):
                got = woa.sample("nstar", float(lats[la]), float(lons[lo]), float(deps[di]), None)
                assert got == pytest.approx(expected[di, la, lo], abs=2e-4)
                # and it is NOT plain N - P
                assert abs(got - (n[di, la, lo] - p[di, la, lo])) > 1.0


def test_fixture_grids_are_aligned_and_plain_vars_unchanged(cache):
    n, lats, lons, deps = _raw("nitrate", "n_an")
    assert woa.sample("nitrate", float(lats[2]), float(lons[2]), float(deps[1]), None) == pytest.approx(n[1, 2, 2], abs=1e-4)


def test_nan_in_either_input_gives_none_not_zero(cache):
    ga, gb = woa._load_grid("nitrate", 0), woa._load_grid("phosphate", 0)
    ga.data[0, 1, 1] = np.nan              # nitrate missing
    gb.data[0, 2, 2] = np.nan              # phosphate missing
    gb.data[0, 3, 3] = 9.96921e36          # WOA fill value
    woa._GRID_CACHE.pop(("nstar", 0), None)
    g = woa._load_grid("nstar", 0)
    assert np.isnan(g.data[0, 1, 1]) and np.isnan(g.data[0, 2, 2]) and np.isnan(g.data[0, 3, 3])
    assert woa.sample("nstar", float(g.lats[1]), float(g.lons[1]), 0.0, None) is None
    assert woa.sample("nstar", float(g.lats[2]), float(g.lons[2]), 0.0, None) is None
    assert woa.sample("nstar", float(g.lats[3]), float(g.lons[3]), 0.0, None) is None
    # untouched neighbour still computes a real number
    assert woa.sample("nstar", float(g.lats[0]), float(g.lons[0]), 0.0, None) is not None
    # NaN cell is transparent in the baked PNG, not the neutral colour
    assert woa.bake_variable_depth("nstar", 0)
    png = np.asarray(Image.open(woa.BAKE_DIR / "nstar" / "0.png"))
    h = png.shape[0]
    assert png[h - 1 - 1, 1, 3] == 0  # lat index 1 -> flipped row (south-up grid)


@pytest.mark.parametrize("coord", ["lats", "lons", "depths"])
def test_misaligned_grids_are_refused_loudly(cache, coord):
    gb = woa._load_grid("phosphate", 0)
    shifted = getattr(gb, coord).copy()
    shifted[0] += 0.5
    setattr(gb, coord, shifted)
    woa._GRID_CACHE.pop(("nstar", 0), None)
    with pytest.raises(ValueError, match="misaligned"):
        woa._load_grid("nstar", 0)


def test_different_shapes_are_refused(cache):
    gb = woa._load_grid("phosphate", 0)
    gb.lats = gb.lats[:-1]
    gb.data = gb.data[:, :-1, :]
    woa._GRID_CACHE.pop(("nstar", 0), None)
    with pytest.raises(ValueError, match="misaligned"):
        woa._load_grid("nstar", 0)


def test_missing_input_file_gives_none(cache):
    (cache / "phosphate" / "woa23_all_p00_01.nc").unlink()
    assert woa.sample("nstar", 11.0, 60.5, 0.0, None) is None
    assert woa.bake_variable_depth("nstar", 0) is None


def test_diverging_ramp_is_neutral_exactly_at_zero():
    cfg = woa.WOA_VARS["nstar"]
    assert cfg["vmin"] == -cfg["vmax"]
    rgba = woa.encode_field_to_rgba(np.array([[-1e3, 0.0, 1e3]], "float32"), cfg["vmin"], cfg["vmax"], cfg["cmap"])
    neg, zero, pos = (rgba[0, i, :3].astype(int) for i in range(3))
    assert zero.min() >= 235 and zero.max() - zero.min() <= 5   # neutral
    assert neg[2] > neg[0] + 50                                  # blue
    assert pos[0] > pos[2] + 50                                  # red


def test_bake_writes_png_for_nstar_at_each_depth_and_meta_lists_it(cache):
    assert "nstar" not in [v["key"] for v in woa.build_meta()["variables"]]
    for d in (0, 500, 1000):
        assert woa.bake_variable_depth("nstar", d)
        assert (woa.BAKE_DIR / "nstar" / f"{d}.png").is_file()
    meta = {v["key"]: v for v in woa.build_meta()["variables"]}
    assert meta["nstar"]["depths"] == [0, 500, 1000]
    assert meta["nstar"]["vmin"] == -15.0 and meta["nstar"]["vmax"] == 15.0
    assert meta["nstar"]["units"] == "µmol/kg"
    assert any(abs(s["pos"] - 0.5) < 1e-9 for s in meta["nstar"]["ramp"])


def test_bake_all_only_missing_bakes_just_what_is_absent(cache):
    # pretend everything but nstar is baked already, with a sentinel PNG
    for v in woa.WOA_VARS:
        if v == "nstar":
            continue
        (woa.BAKE_DIR / v).mkdir(parents=True)
        for d in woa.DISPLAY_DEPTHS:
            (woa.BAKE_DIR / v / f"{d}.png").write_bytes(b"sentinel")
    assert sorted(woa.missing_pngs()) == [("nstar", 0), ("nstar", 500), ("nstar", 1000)]
    assert woa.bake_all(only_missing=True) == 3
    assert woa.missing_pngs() == []
    assert (woa.BAKE_DIR / "oxygen" / "0.png").read_bytes() == b"sentinel"  # untouched


class _Conn:
    def __init__(self, last):
        self.last = last

    async def fetchval(self, *_a):
        return self.last


class _Pool:
    def __init__(self, last):
        self.last = last

    @contextlib.asynccontextmanager
    async def acquire(self):
        yield _Conn(self.last)


def _startup(monkeypatch, last):
    from datetime import datetime, timezone
    from domains.fields import climatology as clim
    monkeypatch.setattr(clim.db, "pool", _Pool(last), raising=False)
    logged = []

    async def _log(*a):
        logged.append(a)
    monkeypatch.setattr(clim, "_log_sync", _log)
    clim._woa_meta_cache = "stale"
    return clim, logged, datetime.now(timezone.utc)


def test_startup_bake_with_fresh_guard_bakes_only_missing_pngs(cache, monkeypatch):
    for v in woa.WOA_VARS:
        if v == "nstar":
            continue
        (woa.BAKE_DIR / v).mkdir(parents=True)
        for d in woa.DISPLAY_DEPTHS:
            (woa.BAKE_DIR / v / f"{d}.png").write_bytes(b"sentinel")
    from datetime import datetime, timezone
    clim, logged, now = _startup(monkeypatch, datetime.now(timezone.utc))  # baked just now: guard is fresh
    n = asyncio.run(clim.sync_woa())
    assert n == 3
    assert (woa.BAKE_DIR / "nstar" / "500.png").is_file()
    assert (woa.BAKE_DIR / "silicate" / "500.png").read_bytes() == b"sentinel"
    assert clim._woa_meta_cache is None          # /meta cache dropped so nstar shows up
    assert logged == []                          # the 30-day guard timestamp is not renewed


def test_startup_bake_with_fresh_guard_and_nothing_missing_skips(cache, monkeypatch):
    for v in woa.WOA_VARS:
        (woa.BAKE_DIR / v).mkdir(parents=True)
        for d in woa.DISPLAY_DEPTHS:
            (woa.BAKE_DIR / v / f"{d}.png").write_bytes(b"sentinel")
    from datetime import datetime, timezone
    clim, logged, _ = _startup(monkeypatch, datetime.now(timezone.utc))
    assert asyncio.run(clim.sync_woa()) == 0
    assert (woa.BAKE_DIR / "nstar" / "0.png").read_bytes() == b"sentinel"  # nothing re-baked
