# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Area Export must not read its numbers out of a rendering texture.

The currents bake encodes u and v into one byte each across a ±3 m/s span, so
one step is 6/255 = 2.35 cm/s. That is the right trade for drawing particles.
`currents_grid_export` then decoded those bytes back and served them as the
exported velocity. Measured on the live bake 2026-09-10:

    surface   median speed 11.6 cm/s —  5.8% of wet cells below one step
    1000 m    median speed  3.7 cm/s — 38.4% of wet cells below one step

The 1,000 m field is the one this platform describes as carrying mining
sediment plumes, so a third of the layer that matters most was exported with
less than one step of resolution. The ±3 m/s clamp was never the problem — no
wet cell reached it at either depth — the step size was.

⛔ These tests EXECUTE the sampler against a written cache directory. A source
check would not notice a loader that opens the npz and then uses the texture.
"""
import ast
import json
import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

STEP = 6.0 / 255.0   # the texture's resolution, in m/s


def _write_cache(root: pathlib.Path, depth_dir: str, u, v, *, with_npz: bool):
    d = root / depth_dir
    d.mkdir(parents=True, exist_ok=True)
    h, w = u.shape
    meta = {"bounds": [-180.0, -80.0, 180.0, 90.0], "width": w, "height": h,
            "date": "2026-09-10", "depth_m": 0 if depth_dir == "surface" else 1000,
            "imageUnscale": [-3.0, 3.0]}
    (d / "latest.json").write_text(json.dumps(meta))

    from PIL import Image
    rgba = np.zeros((h, w, 4), dtype="uint8")
    rgba[..., 0] = np.clip((u + 3.0) / 6.0 * 255.0, 0, 255).astype("uint8")
    rgba[..., 1] = np.clip((v + 3.0) / 6.0 * 255.0, 0, 255).astype("uint8")
    rgba[..., 3] = 255
    Image.fromarray(rgba, "RGBA").save(d / "latest.png")

    if with_npz:
        with open(d / "latest.npz", "wb") as fh:
            np.savez_compressed(fh, u=u.astype("float32"), v=v.astype("float32"))


@pytest.fixture
def cache(tmp_path, monkeypatch):
    import services.currents_grid_export as ex
    monkeypatch.setattr(ex, "CACHE_DIR", tmp_path)
    ex.reset_cache()
    yield tmp_path, ex
    ex.reset_cache()


#: A deep-water velocity typical of the 1000 m field, chosen to land near a
#: quantisation BOUNDARY. ⚠️ The first values picked here (0.0131 / -0.0074)
#: happened to sit near a step centre, so the texture reproduced them to within
#: a quarter step and the fixture assertion below rejected them — which is what
#: that assertion is for. A test value the encoding handles well proves nothing.
DEEP_U, DEEP_V = 0.0235, -0.0353


def test_the_fixture_proves_the_texture_really_does_lose_this_value(cache):
    # ⛔ Without this, the comparison below could pass on a value the texture
    # happens to represent exactly, and prove nothing about precision.
    root, ex = cache
    u = np.full((4, 6), DEEP_U, dtype="float32")
    v = np.full((4, 6), DEEP_V, dtype="float32")
    _write_cache(root, "surface", u, v, with_npz=False)
    for var, want in (("u", DEEP_U), ("v", DEEP_V)):
        got = ex.sample(var, 0.0, 0.0, 0)
        assert got is not None
        assert abs(got - want) > STEP / 4, (
            f"the texture returned {got} for {var}, within a quarter step of "
            f"{want} — pick a test value the 8-bit encoding actually mangles"
        )


def test_the_export_uses_the_float_grid_when_it_is_there(cache):
    root, ex = cache
    u = np.full((4, 6), DEEP_U, dtype="float32")
    v = np.full((4, 6), DEEP_V, dtype="float32")
    _write_cache(root, "surface", u, v, with_npz=True)

    assert ex.sample("u", 0.0, 0.0, 0) == pytest.approx(DEEP_U, abs=1e-6), (
        "the exported value went through the 8-bit texture even though the "
        "float grid was written beside it"
    )
    assert ex.sample("v", 0.0, 0.0, 0) == pytest.approx(DEEP_V, abs=1e-6)
    assert ex.GRID_PRECISION[0] == "float32"


def test_it_still_works_and_says_so_when_only_the_texture_exists(cache):
    # The first deploy runs before the next bake, so the npz will be absent for
    # a few hours. That must degrade, not break — and must be admitted.
    root, ex = cache
    u = np.full((4, 6), DEEP_U, dtype="float32")
    v = np.full((4, 6), DEEP_V, dtype="float32")
    _write_cache(root, "surface", u, v, with_npz=False)

    got = ex.sample("u", 0.0, 0.0, 0)
    assert got is not None, "the sampler stopped working without the float grid"
    assert ex.GRID_PRECISION[0] == "uint8-texture", (
        "the sampler fell back to the texture without recording that it did"
    )


def test_a_float_grid_that_disagrees_with_the_metadata_is_refused(cache):
    # A stale npz of the wrong shape would shift every sampled cell silently.
    root, ex = cache
    u = np.full((4, 6), DEEP_U, dtype="float32")
    v = np.full((4, 6), DEEP_V, dtype="float32")
    _write_cache(root, "surface", u, v, with_npz=False)
    with open(root / "surface" / "latest.npz", "wb") as fh:
        np.savez_compressed(fh, u=np.zeros((9, 9), "float32"), v=np.zeros((9, 9), "float32"))
    ex.reset_cache()

    assert ex.sample("u", 0.0, 0.0, 0) is not None
    assert ex.GRID_PRECISION[0] == "uint8-texture", (
        "a mis-shaped float grid was trusted; every sampled cell would shift"
    )


def test_the_provenance_admits_what_the_fallback_costs():
    import services.export_registry as reg
    entry = next(v for k, v in vars(reg).items()
                 if isinstance(v, dict) and "ocean-currents" in v)["ocean-currents"]
    note = entry.prov.note
    assert "0.0235" in note and "float" in note.lower(), (
        "the export note does not say what a reader gets when the float grid "
        f"is missing: {note!r}"
    )


# ── The bake half ───────────────────────────────────────────────────────────
# ⛔ Everything above proves the READER prefers the float grid. If the WRITER
# never produces one, all of it passes while every export still comes out of
# the texture — the call-site lesson MOSAIC and offshore both taught this week.

def test_the_bake_writes_the_float_grid_beside_the_texture(tmp_path, monkeypatch):
    import services.currents_bake as bake

    u = np.array([[0.0235, -0.0353], [np.nan, 1.25]], dtype="float32")
    v = np.array([[-0.5, 0.5], [np.nan, -1.25]], dtype="float32")
    rgba = bake.encode_uv_to_rgba(u, v)
    meta = {"width": 2, "height": 2, "date": "2026-09-10",
            "bounds": [-180.0, -80.0, 180.0, 90.0]}

    bake._write_dated(tmp_path, "2026-09-10", rgba, meta, u=u, v=v)

    npz = tmp_path / "2026-09-10.npz"
    assert npz.is_file(), (
        "the bake wrote only the 8-bit texture; every export falls back to it"
    )
    with np.load(npz) as z:
        assert z["u"] == pytest.approx(u, nan_ok=True, abs=1e-6)
        assert z["v"] == pytest.approx(v, nan_ok=True, abs=1e-6)
    assert not list(tmp_path.glob("*.tmp*")), "a temp file survived the rename"


def test_the_latest_pointer_carries_the_float_grid_with_it(tmp_path, monkeypatch):
    import services.currents_bake as bake

    u = np.array([[0.0235, -0.0353]], dtype="float32")
    v = np.array([[-0.5, 0.5]], dtype="float32")
    rgba = bake.encode_uv_to_rgba(u, v)
    meta = {"width": 2, "height": 1, "date": "2026-09-10",
            "bounds": [-180.0, -80.0, 180.0, 90.0]}
    bake._write_dated(tmp_path, "2026-09-10", rgba, meta, u=u, v=v)
    bake._refresh_latest_pointer(tmp_path)

    assert (tmp_path / "latest.npz").is_file(), (
        "latest.png moved to the newest day and latest.npz did not — the "
        "export would serve texture values for whichever day is current"
    )
    with np.load(tmp_path / "latest.npz") as z:
        assert z["u"] == pytest.approx(u, abs=1e-6)


def test_pruning_takes_the_float_grid_with_the_texture(tmp_path, monkeypatch):
    # 0.3 MB per day per depth is cheap; 0.3 MB per day forever is a disk leak.
    import services.currents_bake as bake
    monkeypatch.setattr(bake, "CACHE_DIR", tmp_path)

    d = tmp_path / "surface"
    d.mkdir()
    for name in ("2020-01-01.png", "2020-01-01.json", "2020-01-01.npz"):
        (d / name).write_bytes(b"x")

    removed = bake.prune_old("surface", keep_days=1)
    assert removed == 1
    assert not (d / "2020-01-01.npz").exists(), (
        "prune_old removed the texture and left the float grid behind"
    )


def test_every_call_to_the_writer_actually_hands_it_the_floats():
    # ⚠️ This test exists because the one above it did NOT catch the sabotage
    # that mattered. Removing `u=u, v=v` from bake_depth's call left all eight
    # other guards green: _write_dated still works when given floats, so
    # testing _write_dated proves nothing about whether anyone gives it any.
    # Four green MOSAIC tests died the same way, and the offshore retry landed
    # on 4 of 7 call sites before an AST walk noticed.
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "services" / "currents_bake.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_write_dated"]
    assert calls, "fixture problem: no call to _write_dated found in currents_bake.py"
    naked = [c.lineno for c in calls
             if not {k.arg for k in c.keywords} >= {"u", "v"}]
    assert not naked, (
        f"_write_dated is called without u= and v= at line(s) {naked} — the "
        "float grid is never written, so every export silently falls back to "
        "the 8-bit texture while the reader tests stay green"
    )
