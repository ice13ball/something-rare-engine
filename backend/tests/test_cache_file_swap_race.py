# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The bake→read file race introduced by the web/worker process split.

`ABYSSAL_ROLE=worker` bakes into `/var/cache/abyssal-*`; `ABYSSAL_ROLE=web` reads the
same files. Every cached or memory-mapped reader in the web process is now exposed to
two failure shapes that a single-process backend never had:

1. **Torn read.** A plain `np.save(path, arr)` truncates the live file. A reader holding
   `np.load(path, mmap_mode="r")` over it gets garbage or SIGBUS — an uncatchable page
   fault, so no exception and no log line. Measured once, then written down rather than
   re-run (see `test_rebake_publishes_a_new_inode_instead_of_rewriting_the_live_one`,
   which asserts the same property through `st_ino` and cannot fault).

2. **Stale read.** Making the writer atomic fixes tearing but pins the reader to the OLD
   inode forever — the web process keeps serving last week's grid, silently. Guarded by
   `test_*_notices_a_replaced_file`.

⚠️ Behavioural, not shape-based, on purpose — a test that greps for `os.replace` proves
the code's spelling, not its effect. But behavioural here means observing the file's
identity and the reader's output across a real swap, never triggering the fault itself:
a SIGBUS aborts the interpreter, so it takes the run with it instead of going red. The
two shape assertions at the bottom are supplements and say why.

Sabotage counts measured 2026-09-18, one at a time, `pytest <this file> -q --color=no`
counted with `grep -cE '^(FAILED|ERROR) backend/tests/'`. **Control: 0.**

  1. `_write_holding` back to `np.save(GRID_DIR / _DEPTH_NPY, elev)`   → 2 red
  2. drop the stamp check in `bathymetry_grid_export._load_grid`       → 3 red
  3. `cache_swap` tempfile into the system temp dir, not the target's  → 1 red
  4. drop the stamp check in `chi_impact._load_grid`                   → 1 red
  5. drop the stamp check in `currents_grid_export._load_grid`         → 2 red
  6. `chi_impact._load_grid` grid write back to bare `np.save`         → 1 red
  7. `spatial_v2._raster_put` back to a shared `"<name>.tmp"`          → 1 red
"""
from __future__ import annotations

import inspect
import json
import os
import pathlib
import re

import numpy as np
import pytest

from services import bathymetry_grid_export as bge
from services import cache_swap
from services import chi_impact
from services import currents_grid_export as cge


# ─────────────────────────────────────────────────────────────────────────────
# cache_swap itself
# ─────────────────────────────────────────────────────────────────────────────

def test_atomic_write_keeps_the_temp_file_in_the_target_directory(tmp_path):
    """⛔ A rename across filesystems is NOT atomic — it degrades to copy+unlink,
    which reopens the torn window this whole module exists to close. Observed by
    watching where the temp file actually lands, not by reading the source."""
    target = tmp_path / "nested" / "holding.bin"
    seen: list[pathlib.Path] = []

    def _write(tmp: pathlib.Path) -> None:
        seen.append(tmp)
        tmp.write_bytes(b"payload")

    cache_swap.atomic_write(target, _write)

    assert seen, "atomic_write never invoked the writer"
    assert seen[0].parent == target.parent, (
        f"temp file was created in {seen[0].parent}, not beside the target in "
        f"{target.parent} — os.replace across filesystems is not atomic"
    )
    assert target.read_bytes() == b"payload"


def test_atomic_write_gives_each_writer_a_private_temp_name(tmp_path):
    """Two processes writing the same target must not share one temp path: their
    writes would interleave into a single file that is then renamed into place,
    intact-looking and wrong. A fixed "<name>.tmp" has exactly that bug."""
    target = tmp_path / "shared.bin"
    names: list[str] = []
    for i in range(5):
        cache_swap.atomic_write(target, lambda tmp, i=i: (names.append(tmp.name), tmp.write_bytes(bytes([i])))[-1])
    assert len(set(names)) == len(names), f"temp names collided: {names}"


def test_atomic_write_leaves_no_temp_behind_when_the_writer_raises(tmp_path):
    """A failed bake must not litter the cache dir with half-written temps that a
    later glob (available_dates, prune) could mistake for real holdings."""
    target = tmp_path / "x.bin"
    target.write_bytes(b"old")
    with pytest.raises(RuntimeError):
        cache_swap.atomic_write(target, lambda tmp: (_ for _ in ()).throw(RuntimeError("bake died")))
    assert target.read_bytes() == b"old", "a failed write clobbered the previous holding"
    assert list(tmp_path.iterdir()) == [target], f"temp file left behind: {list(tmp_path.iterdir())}"


def test_file_stamp_changes_when_the_file_is_replaced(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(b"aaa")
    before = cache_swap.file_stamp([p])
    cache_swap.atomic_write_bytes(p, b"bbb")
    assert cache_swap.file_stamp([p]) != before


def test_file_stamp_reports_a_missing_file_as_none_rather_than_raising(tmp_path):
    assert cache_swap.file_stamp([tmp_path / "nope"]) == (None,)


# ─────────────────────────────────────────────────────────────────────────────
# bathymetry_grid_export — the mmap reader. This is the one that can SIGBUS.
# ─────────────────────────────────────────────────────────────────────────────

def _bake_bathy(tmp_path, elev):
    lats = np.linspace(90, -90, elev.shape[0])
    lons = np.linspace(-180, 180, elev.shape[1])
    bge._write_holding(lats, lons, elev)
    return lats, lons


def test_rebake_publishes_a_new_inode_instead_of_rewriting_the_live_one(tmp_path, monkeypatch):
    """The property that makes `mmap_mode="r"` safe here, asserted WITHOUT faulting.

    A reader holding a mapping of depth.npy is safe if and only if a re-bake never
    touches the bytes of the inode it mapped. An atomic writer guarantees that: it
    fills a fresh inode and renames it over the name, leaving the old one alive
    until the last reference drops. An in-place `np.save` does the opposite — same
    inode, truncated and refilled underneath the mapping.

    ⛔ Deliberately checked by `st_ino`, NOT by reading through the stale mapping.
    Reading it is what the safe path makes harmless and the unsafe path makes fatal,
    and "fatal" here means SIGBUS — an uncatchable page fault that aborts the whole
    interpreter, so it could never be an assertion. Measured once on macOS
    2026-09-18, reverting `_write_holding` to a plain `np.save` and then comparing
    through the mapping taken before it; the kernel's own triage:

        Exception Type:     EXC_BAD_ACCESS (SIGBUS)
        Exception Subtype:  FS pagein error: 22 Invalid argument
        Kernel Triage:      CL - cluster_pagein past EOF

    That is the measurement behind the atomic writer. It is not re-run: the crash
    took the parent pytest process with it (exit 138) and reported ZERO failures,
    and every occurrence writes a macOS crash report.
    """
    monkeypatch.setattr(bge, "GRID_DIR", tmp_path)
    bge.reset_cache()
    npy = tmp_path / bge._DEPTH_NPY

    _bake_bathy(tmp_path, np.arange(64 * 64, dtype="float32").reshape(64, 64))
    held = bge._load_grid("depth_m")._elev
    assert isinstance(held, np.memmap), "not a memmap — this test is not exercising the race"
    ino_before = os.stat(npy).st_ino

    _bake_bathy(tmp_path, np.full((8, 8), -1234.0, dtype="float32"))   # the worker re-bakes

    assert os.stat(npy).st_ino != ino_before, (
        "the re-bake reused the inode the live mapping covers — it rewrote the file "
        "in place instead of renaming a new one over it. A reader holding "
        'np.load(..., mmap_mode="r") over that inode now faults (SIGBUS, '
        "cluster_pagein past EOF) or reads torn data."
    )


def test_bathymetry_notices_a_replaced_file(tmp_path, monkeypatch):
    """The other half: after the swap, a NEW sample() must return the NEW value.
    Without change detection the module cache pins the old grid for the life of
    the process and the platform serves stale depths with nothing in the log."""
    monkeypatch.setattr(bge, "GRID_DIR", tmp_path)
    bge.reset_cache()

    lats, lons = _bake_bathy(tmp_path, np.full((16, 16), -1000.0, dtype="float32"))
    assert bge.sample("depth_m", float(lats[0]), float(lons[0]), None) == -1000.0

    _bake_bathy(tmp_path, np.full((16, 16), -4000.0, dtype="float32"))
    assert bge.sample("depth_m", float(lats[0]), float(lons[0]), None) == -4000.0, (
        "sample() still returns the pre-rebake depth — the reader never noticed the "
        "file was replaced, which is exactly how the web process would serve stale "
        "data forever after a worker bake"
    )


def test_bathymetry_notices_a_grid_that_changed_shape(tmp_path, monkeypatch):
    """A reload that kept the old axes beside the new array would index the wrong
    cell rather than fail — the silent-corruption shape. Axes and array must move
    together."""
    monkeypatch.setattr(bge, "GRID_DIR", tmp_path)
    bge.reset_cache()

    _bake_bathy(tmp_path, np.zeros((4, 4), dtype="float32"))
    bge._load_grid("depth_m")

    big = (np.arange(20 * 30, dtype="float32") * -1.0).reshape(20, 30)
    lats, lons = _bake_bathy(tmp_path, big)

    g = bge._load_grid("depth_m")
    assert g._elev.shape == (20, 30)
    assert len(g.lats) == 20 and len(g.lons) == 30
    assert bge.sample("depth_m", float(lats[7]), float(lons[11]), None) == float(big[7, 11])


def test_bathymetry_notices_the_holding_disappearing(tmp_path, monkeypatch):
    """A purge between requests must produce None, not the last grid the process
    happened to load."""
    monkeypatch.setattr(bge, "GRID_DIR", tmp_path)
    bge.reset_cache()
    _bake_bathy(tmp_path, np.full((4, 4), -50.0, dtype="float32"))
    assert bge.sample("depth_m", 0.0, 0.0, None) == -50.0
    (tmp_path / bge._DEPTH_NPY).unlink()
    assert bge.sample("depth_m", 0.0, 0.0, None) is None


# ─────────────────────────────────────────────────────────────────────────────
# chi_impact — cached full read, atomic writer
# ─────────────────────────────────────────────────────────────────────────────

def _bake_chi(tmp_path, data):
    lats = np.linspace(90, -90, data.shape[0])
    lons = np.linspace(-180, 180, data.shape[1])
    cache_swap.atomic_np_save(tmp_path / "grid.npy", data)
    cache_swap.atomic_write_text(
        tmp_path / "grid_meta.json",
        json.dumps({"lats": lats.tolist(), "lons": lons.tolist(), "res_deg": 0.1}),
    )
    return lats, lons


def test_chi_impact_notices_a_replaced_grid(tmp_path, monkeypatch):
    """`sync_chi_impact` pops `_GRID_CACHE` in the process that ran the bake. After
    the split that is the worker, and nothing tells the web process. The stamp is
    the only thing that does."""
    monkeypatch.setattr(chi_impact, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(chi_impact, "_npy_path", lambda: tmp_path / "grid.npy")
    monkeypatch.setattr(chi_impact, "_meta_path", lambda: tmp_path / "grid_meta.json")
    chi_impact._GRID_CACHE.clear()

    lats, lons = _bake_chi(tmp_path, np.full((10, 20), 0.25, dtype="float32"))
    assert chi_impact.sample(float(lats[0]), float(lons[0])) == pytest.approx(0.25)

    _bake_chi(tmp_path, np.full((10, 20), 0.91, dtype="float32"))
    assert chi_impact.sample(float(lats[0]), float(lons[0])) == pytest.approx(0.91), (
        "chi_impact.sample() still returns the pre-rebake index — the module cache "
        "never re-checked the file"
    )


def test_chi_impact_writes_its_grid_atomically(tmp_path, monkeypatch):
    """The writer under test is the `_load_grid` reproject branch. Rather than
    stand up rasterio, drive the same helpers it calls and assert the invariant
    that matters: at no point is the target a partially-written file, and the
    previous holding survives a writer that dies mid-bake."""
    npy = tmp_path / "grid.npy"
    cache_swap.atomic_np_save(npy, np.full((5, 5), 1.0, dtype="float32"))
    good = npy.read_bytes()
    with pytest.raises(RuntimeError):
        cache_swap.atomic_write(npy, lambda tmp: (_ for _ in ()).throw(RuntimeError("boom")))
    assert npy.read_bytes() == good
    np.testing.assert_array_equal(np.load(npy), np.full((5, 5), 1.0, dtype="float32"))


# ─────────────────────────────────────────────────────────────────────────────
# currents_grid_export — cached decode of files the worker replaces daily
# ─────────────────────────────────────────────────────────────────────────────

def _bake_currents(root, depth_dir, u, v):
    d = root / depth_dir
    d.mkdir(parents=True, exist_ok=True)
    h, w = u.shape
    cache_swap.atomic_write_text(d / "latest.json", json.dumps({
        "bounds": [-180.0, -90.0, 180.0, 90.0], "width": w, "height": h,
        "url": f"/v1/currents/{depth_dir}.png", "date": "2026-09-18",
    }))

    def _npz(tmp):
        with open(tmp, "wb") as fh:
            np.savez_compressed(fh, u=u.astype("float32"), v=v.astype("float32"))

    cache_swap.atomic_write(d / "latest.npz", _npz)


def test_currents_export_notices_a_replaced_daily_bake(tmp_path, monkeypatch):
    """The currents bake runs daily in the worker. `reset_cache()` after it never
    reaches the web process, so without the stamp Area Export would keep handing
    out the first day this process ever loaded."""
    monkeypatch.setattr(cge, "CACHE_DIR", tmp_path)
    cge.reset_cache()

    u1 = np.full((6, 10), 0.11, dtype="float32")
    _bake_currents(tmp_path, "surface", u1, np.full((6, 10), -0.22, dtype="float32"))
    assert cge.sample("u", 90.0, -180.0, 0) == pytest.approx(0.11, abs=1e-6)

    _bake_currents(tmp_path, "surface", np.full((6, 10), 0.77, dtype="float32"),
                   np.full((6, 10), -0.88, dtype="float32"))
    assert cge.sample("u", 90.0, -180.0, 0) == pytest.approx(0.77, abs=1e-6), (
        "currents_grid_export.sample() still returns yesterday's velocity"
    )
    assert cge.sample("v", 90.0, -180.0, 0) == pytest.approx(-0.88, abs=1e-6)


def test_currents_export_notices_the_float_grid_appearing(tmp_path, monkeypatch):
    """GRID_PRECISION is served as export provenance. If the npz lands after a
    texture-only load and the reader does not re-check, a download keeps being
    labelled "uint8-texture" while float data sits on disk — a provenance lie."""
    monkeypatch.setattr(cge, "CACHE_DIR", tmp_path)
    cge.reset_cache()

    u = np.full((4, 8), 0.5, dtype="float32")
    _bake_currents(tmp_path, "surface", u, u)
    (tmp_path / "surface" / "latest.npz").unlink()
    from PIL import Image
    rgba = np.zeros((4, 8, 4), dtype="uint8")
    rgba[..., 3] = 255
    Image.fromarray(rgba, "RGBA").save(tmp_path / "surface" / "latest.png")
    cge._load_grid("u")
    assert cge.GRID_PRECISION[0] == "uint8-texture"

    _bake_currents(tmp_path, "surface", u, u)          # worker publishes the float grid
    cge._load_grid("u")
    assert cge.GRID_PRECISION[0] == "float32", (
        "the float grid appeared on disk but the export still claims texture precision"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Shape supplements. ⚠️ These assert spelling, not behaviour, and are here only
# because the behaviour they describe cannot be observed from a test process:
# `np.save`'s truncate window is microseconds wide and racing it from pytest
# would be flaky, and the tile cache writers are wired into FastAPI request
# handlers whose disk side-effect is otherwise invisible to a unit test.
# ─────────────────────────────────────────────────────────────────────────────

def _code_only(func) -> str:
    return "\n".join(re.sub(r"#.*", "", ln) for ln in inspect.getsource(func).splitlines())


@pytest.mark.parametrize("func", [bge._write_holding, chi_impact._load_grid])
def test_grid_writers_never_call_bare_np_save(func):
    src = _code_only(func)
    assert not re.search(r"(?<!_)\bnp\.save\s*\(", src), (
        f"{func.__qualname__} calls np.save directly again. That truncates the live "
        f"file; a web-process reader holding mmap_mode=\"r\" over it gets garbage or "
        f"SIGBUS. Use services.cache_swap.atomic_np_save."
    )


def test_tile_disk_cache_writers_go_through_cache_swap():
    from routers import spatial_v2
    for fn in (spatial_v2._cache_put, spatial_v2._raster_put):
        src = _code_only(fn)
        assert "cache_swap.atomic_write_bytes" in src, (
            f"{fn.__qualname__} no longer writes through cache_swap. A fixed "
            f'"<name>.tmp" is shared between the web and worker processes: their '
            f"writes interleave into it and the rename publishes the mixture."
        )
