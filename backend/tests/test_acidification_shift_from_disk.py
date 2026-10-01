# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""horizon-shift must be served from BAKE_DIR/horizon_shift.npy, never recomputed on a
request path. Root-caused 2026-09-29: horizon_shift_grid() does a full PyCO2SYS
reconstruction over the whole GLODAP grid (>2 GB RSS measured) and was being called inside
the web process on every uncached horizon-shift click, throttling the API for ~7 minutes."""

import os

import numpy as np
import pytest
from services import acidification as acid
from services import glodap_carbon


def _raise(*a, **kw):
    raise AssertionError("computed in a request")


@pytest.fixture(autouse=True)
def _reset_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(acid, "BAKE_DIR", tmp_path)
    monkeypatch.setattr(acid, "SHIFT_NPY", tmp_path / "horizon_shift.npy")
    acid._GRID_CACHE.clear()
    acid._HORIZON_CACHE.clear()
    acid._OMEGA_CACHE.clear()
    acid._HSHIFT_CACHE.clear()
    acid._SHIFT_DISK_CACHE["arr"] = None
    acid._SHIFT_DISK_CACHE["mtime"] = None
    acid._SHIFT_DISK_CACHE["checked_at"] = None
    acid._SHIFT_MISSING_WARNED = False
    # Every test in this file must prove the heavy path is never touched.
    monkeypatch.setattr(acid, "omega_grid", _raise)
    monkeypatch.setattr(acid, "horizon_recon_grid", _raise)
    monkeypatch.setattr(acid, "horizon_shift_grid", _raise)
    yield


def _fake_base_grid():
    return glodap_carbon._Grid(
        np.array([0.0, 1.0]), np.array([0.0, 1.0]),
        np.array([0.0, 100.0]), np.zeros((2, 2, 2), dtype="float32"))


def _seed_aragonite(monkeypatch, base):
    acid._GRID_CACHE["aragonite"] = base


# ── a. npy present -> nearest-cell value; NaN -> None ─────────────────────────

def test_sample_reads_value_from_disk(monkeypatch):
    base = _fake_base_grid()
    _seed_aragonite(monkeypatch, base)
    sg = np.array([[10.0, 20.0], [np.nan, 40.0]], dtype="float32")
    acid._save_npy_atomic(sg, acid.SHIFT_NPY)

    v = acid.sample("horizon-shift", lat=0.0, lon=0.0, depth=None)
    assert v == pytest.approx(10.0)

    v2 = acid.sample("horizon-shift", lat=1.0, lon=1.0, depth=None)
    assert v2 == pytest.approx(40.0)


def test_sample_nan_cell_is_none(monkeypatch):
    base = _fake_base_grid()
    _seed_aragonite(monkeypatch, base)
    sg = np.array([[10.0, 20.0], [np.nan, 40.0]], dtype="float32")
    acid._save_npy_atomic(sg, acid.SHIFT_NPY)

    v = acid.sample("horizon-shift", lat=1.0, lon=0.0, depth=None)
    assert v is None


def test_sample_horizon_shift_underscore_alias(monkeypatch):
    base = _fake_base_grid()
    _seed_aragonite(monkeypatch, base)
    sg = np.array([[5.0, 6.0], [7.0, 8.0]], dtype="float32")
    acid._save_npy_atomic(sg, acid.SHIFT_NPY)

    v = acid.sample("horizon_shift", lat=0.0, lon=0.0, depth=None)
    assert v == pytest.approx(5.0)


# ── c. npy missing -> None ─────────────────────────────────────────────────

def test_missing_npy_returns_none(monkeypatch):
    base = _fake_base_grid()
    _seed_aragonite(monkeypatch, base)
    assert acid.load_shift_grid() is None
    v = acid.sample("horizon-shift", lat=0.0, lon=0.0, depth=None)
    assert v is None


def test_missing_npy_warns_once(monkeypatch, caplog):
    base = _fake_base_grid()
    _seed_aragonite(monkeypatch, base)
    with caplog.at_level("WARNING", logger="acidification"):
        acid.load_shift_grid()
        # force a re-stat by advancing the monotonic clock past the interval
        t = {"v": 1000.0}
        monkeypatch.setattr(acid.time, "monotonic", lambda: t["v"])
        acid._SHIFT_DISK_CACHE["checked_at"] = 0.0
        t["v"] = 1000.0
        acid.load_shift_grid()
    warnings = [r for r in caplog.records if "not baked yet" in r.message]
    assert len(warnings) == 1


# ── d. npy with wrong shape -> None ────────────────────────────────────────

def test_wrong_shape_returns_none(monkeypatch):
    base = _fake_base_grid()
    _seed_aragonite(monkeypatch, base)
    sg = np.zeros((3, 3), dtype="float32")  # base grid is (2, 2)
    acid._save_npy_atomic(sg, acid.SHIFT_NPY)

    assert acid.load_shift_grid() is None
    v = acid.sample("horizon-shift", lat=0.0, lon=0.0, depth=None)
    assert v is None


# ── e. bake saver: round-trips, atomic (no leftover temp file) ────────────

def test_save_npy_atomic_round_trips_and_leaves_no_temp(tmp_path):
    arr = np.array([[1.5, 2.5], [3.5, np.nan]], dtype="float32")
    out = tmp_path / "sub" / "horizon_shift.npy"
    acid._save_npy_atomic(arr, out)

    assert out.exists()
    loaded = np.load(out)
    np.testing.assert_array_equal(loaded[:2, :1], arr[:2, :1])
    assert np.isnan(loaded[1, 1])

    leftovers = [p for p in out.parent.iterdir() if p.name != out.name]
    assert leftovers == []


def test_bake_all_writes_shift_npy(monkeypatch, tmp_path):
    # Full bake is entangled with aragonite/calcite/horizon encoding too; stub every heavy
    # grid loader so bake_all() runs fast, and un-stub horizon_shift_grid (the autouse
    # fixture forbids it everywhere else, but the bake IS the one legitimate caller).
    base = glodap_carbon._Grid(
        np.array([0.0, 1.0]), np.array([0.0, 1.0]),
        np.array([0.0, 100.0]),
        np.array([[[3.0, 3.0], [0.5, 0.5]], [[2.0, 2.0], [0.2, 0.2]]], dtype="float32"))
    monkeypatch.setattr(acid, "ensure_holdings", lambda force=False: True)
    monkeypatch.setattr(acid, "_load_grid", lambda v: base)
    sg = np.array([[10.0, 20.0], [30.0, 40.0]], dtype="float32")
    monkeypatch.setattr(acid, "horizon_shift_grid", lambda: sg)

    n = acid.bake_all()

    assert n > 0
    assert acid.SHIFT_NPY.exists()
    loaded = np.load(acid.SHIFT_NPY)
    np.testing.assert_array_equal(loaded, sg)


# ── f. mtime-gated reload picks up a new bake without a restart ───────────

def test_mtime_reload_picks_up_new_bake(monkeypatch):
    base = _fake_base_grid()
    _seed_aragonite(monkeypatch, base)

    clock = {"t": 0.0}
    monkeypatch.setattr(acid.time, "monotonic", lambda: clock["t"])

    sg_a = np.array([[1.0, 1.0], [1.0, 1.0]], dtype="float32")
    acid._save_npy_atomic(sg_a, acid.SHIFT_NPY)
    v_a = acid.sample("horizon-shift", lat=0.0, lon=0.0, depth=None)
    assert v_a == pytest.approx(1.0)

    sg_b = np.array([[2.0, 2.0], [2.0, 2.0]], dtype="float32")
    acid._save_npy_atomic(sg_b, acid.SHIFT_NPY)
    # bump mtime explicitly in case the two saves land in the same filesystem tick
    st = acid.SHIFT_NPY.stat()
    os.utime(acid.SHIFT_NPY, (st.st_atime, st.st_mtime + 5))

    # still within the 60s re-stat window -> stale cached value
    clock["t"] = 30.0
    v_stale = acid.sample("horizon-shift", lat=0.0, lon=0.0, depth=None)
    assert v_stale == pytest.approx(1.0)

    # past the 60s window -> re-stat, mtime changed -> reload
    clock["t"] = 61.0
    v_b = acid.sample("horizon-shift", lat=0.0, lon=0.0, depth=None)
    assert v_b == pytest.approx(2.0)
