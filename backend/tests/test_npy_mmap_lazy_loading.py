# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Audit of every backend `np.load(...)` call site for `mmap_mode="r"` eligibility,
prompted by a 6 GB memory / 3.1-3.3 GB swap peak measured on production within ~50
minutes of every restart, during the `coral-acid-exposure` bake window.

The audit's actual finding (2026-09-18) differs from the lead that prompted it: neither
`acidification.py` nor `coral_acid_exposure.py` calls `np.load` at all (they read NetCDF
via xarray, a separate question). The real `np.load` call sites, and the verdict at each:

    backend/services/bathymetry_grid_export.py:_load_grid   SWITCHED to mmap_mode="r"
        depth.npy (~104 MB) is read-only from here on (sample() only ever does scalar
        indexing); its only writer, bake_bathymetry_grid(), runs once from a
        skip-if-present startup task with no admin Force-Sync route wired to it.

    backend/services/chi_impact.py:_load_grid                LEFT AS-IS, reported
        grid.npy is written in place (np.save, no tmp+rename) by the same bake that the
        admin "chi" Force-Sync action can trigger while another request holds the
        previous grid live — a mmap'd reader could see a torn read mid-rewrite.

    backend/services/currents_grid_export.py:_decode_depth    LEFT AS-IS, reported
        latest.npz is a zip archive, not a flat .npy; mmap_mode does not apply the same
        way and is unsupported for compressed archives.

Source inspection is the honest tool for "does this call pass mmap_mode" — behaviour
cannot see the difference between a lazy and an eager load of an all-valid array. The one
behavioural test below guards the thing behaviour CAN see: that going lazy did not also
go wrong.
"""
from __future__ import annotations

import inspect
import re

import numpy as np
import pytest

from services import bathymetry_grid_export as bge
from services import chi_impact
from services import currents_grid_export


def _code_only(func) -> str:
    """Source of `func` with comments stripped, so a call-site check can't be
    fooled (in either direction) by the word "mmap_mode" appearing in a comment
    explaining why it is or isn't used."""
    return "\n".join(re.sub(r"#.*", "", line) for line in inspect.getsource(func).splitlines())


# ─────────────────────────────────────────────────────────────────────────────
# Source inspection — the only honest tool for "does this call pass mmap_mode".
# ─────────────────────────────────────────────────────────────────────────────

def test_bathymetry_grid_export_load_grid_uses_mmap_mode():
    """The one call site this audit switched. depth.npy (~104 MB) is read-only from
    _load_grid onward — losing mmap_mode here silently reverts to loading the whole
    grid into RSS on every cold cache, which is exactly the regression this guards."""
    src = _code_only(bge._load_grid)
    assert 'mmap_mode="r"' in src, (
        "bathymetry_grid_export._load_grid no longer passes mmap_mode=\"r\" to "
        "np.load — this call site was verified read-only and safe; removing the "
        "flag reintroduces the eager-load memory cost with no comment explaining why"
    )


def test_chi_impact_load_grid_does_not_use_mmap_mode():
    """⛔ Do NOT flip this on without first making the writer atomic. grid.npy is
    rewritten in place (plain np.save, no tmp+rename) by the same bake_all() the
    admin "chi" Force-Sync action can trigger live — see the comment at the call
    site. Guards against someone "fixing" this file to match its sibling above
    without also fixing the write path underneath it."""
    src = _code_only(chi_impact._load_grid)
    assert "mmap_mode" not in src, (
        "chi_impact._load_grid now passes mmap_mode, but its writer (np.save "
        "directly to grid.npy) was never made atomic — a live Force-Sync rebake "
        "could hand a memory-mapped reader a torn read. Make the write atomic "
        "(tempfile + os.replace, as acidification.py's _save_png does) first."
    )


def test_currents_grid_export_decode_depth_does_not_use_mmap_mode():
    """latest.npz is a zip archive, not a flat .npy — mmap_mode is not the right tool
    here (unsupported for compressed archives, not a plain mmap-able layout for
    uncompressed ones either). Guards against someone adding it by analogy with the
    other two sites without checking the on-disk format actually supports it."""
    src = _code_only(currents_grid_export._decode_depth)
    assert "mmap_mode" not in src


# ─────────────────────────────────────────────────────────────────────────────
# Behavioural — a small fixture grid must yield IDENTICAL values through the
# changed (mmap) path, so "loads lazily" cannot quietly become "loads wrong".
# ─────────────────────────────────────────────────────────────────────────────

def test_mmap_loaded_bathymetry_grid_returns_a_real_memmap(tmp_path, monkeypatch):
    """Confirms the switch actually took effect at runtime, not just in source text:
    the array backing the loaded grid must be a numpy.memmap, and it must expose the
    correct dtype/shape — a mismatched dtype/shape would silently misread every cell."""
    lats = np.linspace(90, -90, 6)
    lons = np.linspace(-180, 180, 10)
    rng = np.random.default_rng(0)
    elev = rng.uniform(-6000.0, 1000.0, size=(6, 10)).astype("float32")

    monkeypatch.setattr(bge, "GRID_DIR", tmp_path)
    bge._write_holding(lats, lons, elev)
    bge.reset_cache()

    g = bge._load_grid("depth_m")
    assert isinstance(g._elev, np.memmap), (
        "_load_grid's array is not a numpy.memmap — mmap_mode is not actually "
        "taking effect at runtime despite the source-level flag"
    )
    assert g._elev.dtype == np.float32
    assert g._elev.shape == elev.shape


def test_mmap_loaded_bathymetry_grid_values_match_a_plain_load(tmp_path, monkeypatch):
    """The correctness guard: every cell read back through the mmap path must equal
    the value written, and sample() must agree with a direct plain np.load of the
    same file — proving the lazy path did not reorder axes, truncate, or misalign."""
    lats = np.linspace(90, -90, 8)
    lons = np.linspace(-180, 180, 12)
    rng = np.random.default_rng(42)
    elev = rng.uniform(-8000.0, 2000.0, size=(8, 12)).astype("float32")

    monkeypatch.setattr(bge, "GRID_DIR", tmp_path)
    bge._write_holding(lats, lons, elev)
    bge.reset_cache()

    g_mmap = bge._load_grid("depth_m")
    g_plain = np.load(tmp_path / bge._DEPTH_NPY)  # no mmap_mode — the ground truth

    np.testing.assert_array_equal(np.asarray(g_mmap._elev), g_plain)

    for lat, lon in [(90.0, -180.0), (-90.0, 180.0), (12.3, 45.6), (-33.0, -70.0)]:
        i = int(np.argmin(np.abs(lats - lat)))
        j = int(np.argmin(np.abs(lons - lon)))
        expected = None if np.isnan(elev[i, j]) else float(elev[i, j])
        assert bge.sample("depth_m", lat, lon, None) == expected


@pytest.mark.parametrize("with_nan", [False, True])
def test_mmap_loaded_bathymetry_grid_preserves_nan_as_none(tmp_path, monkeypatch, with_nan):
    """NaN handling is the one place a subtly-wrong lazy read would be invisible in
    the happy path: sample() must still return None for NaN cells and a real float
    for everything else, exactly as it did before mmap_mode was added."""
    lats = np.linspace(45, 44, 2)
    lons = np.linspace(10, 11, 2)
    elev = np.array([[-100.0, -200.0], [-300.0, -400.0]], dtype="float32")
    if with_nan:
        elev[0, 0] = np.nan

    monkeypatch.setattr(bge, "GRID_DIR", tmp_path)
    bge._write_holding(lats, lons, elev)
    bge.reset_cache()

    got = bge.sample("depth_m", 45.0, 10.0, None)
    if with_nan:
        assert got is None
    else:
        assert got == -100.0
