# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""ocean-colour-satellite: Copernicus-GlobColour chlorophyll and primary production.

The fixture is a REAL 3 x 3 degree excerpt at the products' native 1/24 degree
resolution (Peru coast, 2026-08, CHL and PP, about two thirds NaN), see
tests/fixtures/ocean_colour/SOURCE.txt. The Copernicus client is replaced by a test
double that serves that excerpt as the multi-year and the near-real-time product.
The double scales the real values by a per-month factor, and by 1.5 for the
near-real-time product, ONLY so that months and products can be told apart; those
scaled values are not claimed real. The regridding, the product choice, the atomic
bake, the sampler and the endpoints all run for real.
"""
from __future__ import annotations

import asyncio
import pathlib
import warnings
from datetime import datetime, timezone

import numpy as np
import pytest
import xarray as xr
from PIL import Image

from services import ocean_colour as oc

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "ocean_colour" / "oc_window_2026-08.npz"
_Z = np.load(FIXTURE)
FIX = {"CHL": np.asarray(_Z["chl"]), "PP": np.asarray(_Z["pp"])}
FIX_LAT = np.asarray(_Z["lat"])
FIX_LON = np.asarray(_Z["lon"])
NT = 12  # the 72 x 72 window is 12 x 12 target cells

# Past months on purpose: the axes end here, never at the current month.
MY_FIRST = "2024-01"
MY_END = "2025-02"
NRT_FIRST, NRT_END = "2024-12", "2025-04"   # overlaps MY for three months, then runs on

_DS_KEYS = {"plankton": "CHL", "pp": "PP"}


def _months(first: str, last: str) -> list[str]:
    out, y, m = [], int(first[:4]), int(first[5:])
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _factor(month: str, product: str) -> float:
    base = 1.0 + ((int(month[:4]) - 2024) * 12 + int(month[5:])) / 100.0
    return base * (1.5 if product == "nrt" else 1.0)


def _blocks(arr):
    """Independent reference: (nanmean, valid count) of every 6 x 6 block."""
    mean = np.full((NT, NT), np.nan)
    cnt = np.zeros((NT, NT), dtype=int)
    for i in range(NT):
        for j in range(NT):
            b = arr[6 * i:6 * i + 6, 6 * j:6 * j + 6].astype("float64")
            cnt[i, j] = int(np.isfinite(b).sum())
            if cnt[i, j]:
                mean[i, j] = float(np.nansum(b)) / cnt[i, j]
    return mean, cnt


class _VarProxy:
    def __init__(self, da, fail_months):
        self._da, self._fail = da, fail_months

    def sel(self, time):
        if oc.month_key(time) in self._fail:
            raise RuntimeError("503 Service Unavailable (test double)")
        return self._da.sel(time=time)


class _DS:
    def __init__(self, ds, fail_vars=(), fail_months=()):
        self._ds, self._fail_vars, self._fail_months = ds, set(fail_vars), set(fail_months)
        self.closed = False

    def __contains__(self, name):
        return name in self._ds

    def __getitem__(self, name):
        if name in self._fail_vars:
            return _VarProxy(self._ds[name], self._fail_months)
        return self._ds[name]

    def close(self):
        self.closed = True


def _dataset(var, months, product):
    times = np.array([f"{m}-01" for m in months], dtype="datetime64[ns]")
    stack = np.stack([FIX[var] * _factor(m, product) for m in months]).astype("float32")
    return xr.Dataset({var: (("time", "latitude", "longitude"), stack)},
                      coords=dict(time=times, latitude=FIX_LAT, longitude=FIX_LON))


class _FakeCM:
    def __init__(self, axes, *, fail=None, fail_months=()):
        self.axes, self.fail, self.fail_months = axes, fail or {}, fail_months
        self.opened = []

    def open_dataset(self, dataset_id, variables, username, password):
        for product, p in oc.PRODUCTS.items():
            for key, ds_id in p["datasets"].items():
                if ds_id == dataset_id:
                    assert variables == [_DS_KEYS[key]]
                    proxy = _DS(_dataset(_DS_KEYS[key], self.axes[product], product),
                                fail_vars=self.fail.get((product, key), ()),
                                fail_months=self.fail_months)
                    self.opened.append(proxy)
                    return proxy
        raise AssertionError(f"unexpected dataset {dataset_id}")


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "CACHE_DIR", tmp_path / "oc")
    monkeypatch.setattr(oc, "_GRID_CACHE", {})
    monkeypatch.setenv("CMEMS_USERNAME", "u")
    monkeypatch.setenv("CMEMS_PASSWORD", "p")
    return tmp_path / "oc"


def _use(monkeypatch, my_end=MY_END, nrt_first=NRT_FIRST, nrt_end=NRT_END, **kw):
    axes = {"my": _months(MY_FIRST, my_end), "nrt": _months(nrt_first, nrt_end)}
    cm = _FakeCM(axes, **kw)
    monkeypatch.setattr(oc, "_copernicusmarine", cm)
    return cm


def _snapshot(root: pathlib.Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _centre(i, j):
    """Latitude/longitude of the centre of target cell (i, j) of the window."""
    return -13.75 + 0.25 * i, -77.75 + 0.25 * j


def _find(cnt, pred):
    i, j = np.argwhere(pred(cnt))[0]
    return int(i), int(j)


# ── regridding ──────────────────────────────────────────────────────────────

def test_block_mean_equals_an_independent_nanmean_on_every_cell(cache, monkeypatch):
    _use(monkeypatch)
    oc.sync_months()
    month = oc.complete_months()[-1]
    prod = oc.read_month_meta(month)["product_key"]
    for var, src in (("chl", "CHL"), ("pp", "PP")):
        mean, cnt = _blocks(FIX[src] * _factor(month, prod))
        got, n = oc.load_grid(var, month)
        assert got.shape == (NT, NT) and got.dtype == np.float32 and n.dtype == np.uint8
        assert np.array_equal(n, cnt)
        assert np.array_equal(np.isnan(got), cnt == 0)
        ok = cnt > 0
        assert np.allclose(got[ok], mean[ok], rtol=1e-5)
    # the window must really exercise all three kinds of block
    assert (cnt == 36).any() and (cnt == 0).any() and ((cnt > 0) & (cnt < 36)).any()


def test_an_empty_block_is_no_data_and_a_partial_block_keeps_its_valid_fraction(cache, monkeypatch):
    _use(monkeypatch)
    oc.sync_months()
    month = oc.complete_months()[-1]
    _, cnt = oc.load_grid("chl", month)
    i, j = _find(cnt, lambda c: c == 0)
    lat, lon = _centre(i, j)
    out = oc.point_value("chl", lat, lon)
    assert out["status"] == "no_data" and out["chl_mg_m3"] is None
    assert out["valid_fraction"] == 0.0 and "no satellite observation this month" in out["reason"]
    i, j = _find(cnt, lambda c: (c > 0) & (c < 36))
    lat, lon = _centre(i, j)
    out = oc.point_value("chl", lat, lon)
    prod = oc.read_month_meta(month)["product_key"]
    mean, c = _blocks(FIX["CHL"] * _factor(month, prod))
    assert out["status"] == "ok"
    assert out["valid_fraction"] == pytest.approx(c[i, j] / 36.0, abs=1e-4)
    assert out["chl_mg_m3"] == pytest.approx(mean[i, j], rel=1e-5)   # NaN ignored, not counted as 0
    zero_filled = float(np.nansum(FIX["CHL"][6 * i:6 * i + 6, 6 * j:6 * j + 6]) * _factor(month, prod)) / 36.0
    assert out["chl_mg_m3"] > zero_filled * 1.02


def test_strips_give_the_same_answer_and_never_read_more_than_a_strip(cache, monkeypatch):
    da = _dataset("CHL", ["2025-01"], "my")["CHL"].sel(time="2025-01-01")
    geo = oc.block_geometry(da["latitude"].values, da["longitude"].values)
    whole = oc.coarsen_field(da, geo)
    monkeypatch.setattr(oc, "STRIP_BLOCK_ROWS", 5)
    seen = []

    class _Spy:
        dims = da.dims

        def isel(self, latitude):
            seen.append(latitude.stop - latitude.start)
            return da.isel(latitude=latitude)

    strips = oc.coarsen_field(_Spy(), geo)
    assert max(seen) == 5 * oc.BLOCK and len(seen) == 3          # 12 rows in strips of 5, 5, 2
    assert np.array_equal(whole[0], strips[0], equal_nan=True) and np.array_equal(whole[1], strips[1])


def test_global_grid_lines_up_with_the_model_layer_and_wraps_the_seam():
    from services import bgc_model
    lat = (np.arange(4320) - 2160 + 0.5) / 24.0
    lon = (np.arange(8640) - 4320 + 0.5) / 24.0
    g = oc.block_geometry(lat, lon)["grid"]
    assert (g["n_lat"], g["n_lon"], g["lat0"], g["lon0"], g["lon_global"]) == (719, 1440, -89.75, -180.0, True)
    assert g["bounds"] == [-180.125, -89.875, 179.875, 89.875]
    # the model layer's grid has centres on multiples of 0.25 as well: -180.. and -80..
    assert (bgc_model.VARS and g["lon0"] % 0.25 == 0 and g["lat0"] % 0.25 == 0)
    # twelve rows, full width: the cell centred on -180 is made of the last 3 and first 3 columns
    lat12 = lat[:12]
    geo = oc.block_geometry(lat12, lon)
    assert geo["n_lat"] == 1
    da = xr.DataArray(np.tile(np.arange(8640, dtype="float32"), (12, 1)),
                      dims=("latitude", "longitude"), coords=dict(latitude=lat12, longitude=lon))
    mean, cnt = oc.coarsen_field(da, geo)
    assert mean[0, 0] == pytest.approx((8637 + 8638 + 8639 + 0 + 1 + 2) / 6.0)
    assert mean[0, 1] == pytest.approx(5.5) and mean[0, 1439] == pytest.approx(8633.5)  # columns 8631..8636
    assert (cnt == 36).all()


def test_fill_value_is_nan_not_a_number():
    a = np.full((6, 6), 2.0, dtype="float32")
    a[0, 0] = -999.0
    a[1, 1] = np.nan
    mean, cnt = oc.block_mean(oc._clean(a))
    assert cnt[0, 0] == 34 and mean[0, 0] == pytest.approx(2.0)
    allfill = oc._clean(np.full((6, 6), -999.0, dtype="float32"))
    mean, cnt = oc.block_mean(allfill)
    assert np.isnan(mean[0, 0]) and cnt[0, 0] == 0


# ── which product supplies which month ──────────────────────────────────────

def test_multi_year_wins_an_overlapping_month_and_near_real_time_fills_the_rest(cache, monkeypatch):
    _use(monkeypatch)
    res = oc.sync_months()
    assert res["failed"] == {}
    prods = res["products"]
    assert prods["2025-02"] == "my" and prods["2025-01"] == "my" and prods["2024-12"] == "my"
    assert prods["2025-03"] == "nrt" and prods["2025-04"] == "nrt"
    for m, key in prods.items():
        assert oc.read_month_meta(m)["product_key"] == key
    # the VALUES come from the product named, not just the label
    i, j = _find(oc.load_grid("chl", "2025-02")[1], lambda c: c == 36)
    mean_my, _ = _blocks(FIX["CHL"] * _factor("2025-02", "my"))
    mean_nrt, _ = _blocks(FIX["CHL"] * _factor("2025-02", "nrt"))
    assert oc.load_grid("chl", "2025-02")[0][i, j] == pytest.approx(mean_my[i, j], rel=1e-5)
    assert oc.load_grid("chl", "2025-02")[0][i, j] != pytest.approx(mean_nrt[i, j], rel=1e-3)
    mean_nrt3, _ = _blocks(FIX["CHL"] * _factor("2025-04", "nrt"))
    assert oc.load_grid("chl", "2025-04")[0][i, j] == pytest.approx(mean_nrt3[i, j], rel=1e-5)


def test_newest_month_comes_from_the_axes_not_the_clock(cache, monkeypatch):
    _use(monkeypatch)
    res = oc.sync_months()
    now_month = datetime.now(timezone.utc).strftime("%Y-%m")
    assert now_month not in (NRT_END, MY_END)
    assert res["newest"] == NRT_END                      # newest across BOTH axes
    assert res["wanted"] == oc.months_back(NRT_END, 12)
    assert oc.complete_months()[-1] == NRT_END and not (cache / now_month).exists()
    assert oc.build_meta()["month_products"][NRT_END] == "nrt"


def test_when_the_multi_year_product_catches_up_the_month_is_rebaked_from_it(cache, monkeypatch):
    _use(monkeypatch, my_end="2025-01", nrt_end="2025-03")
    res = oc.sync_months()
    assert res["products"]["2025-02"] == "nrt" and res["products"]["2025-03"] == "nrt"
    before = _snapshot(cache)
    _use(monkeypatch, my_end="2025-03", nrt_end="2025-03")
    res = oc.sync_months()
    assert sorted(res["baked"]) == ["2025-02", "2025-03"]
    assert oc.read_month_meta("2025-02")["product_key"] == "my"
    after = _snapshot(cache)
    keep = [k for k in before if k.startswith(("2024-12/", "2025-01/"))]
    assert keep and all(after[k] == before[k] for k in keep if not k.endswith("meta.json"))


def test_a_month_only_one_variable_has_is_not_available_from_that_product(cache, monkeypatch):
    axes = {"my": _months(MY_FIRST, MY_END), "nrt": _months(NRT_FIRST, NRT_END)}
    from services.ocean_colour import plan_months
    per = {"my": {"plankton": {m: 1 for m in axes["my"]}, "pp": {m: 1 for m in axes["my"][:-1]}},
           "nrt": {"plankton": {m: 1 for m in axes["nrt"]}, "pp": {m: 1 for m in axes["nrt"][:-1]}}}
    newest, chosen = plan_months(per)
    assert newest == "2025-03" and chosen["2025-02"] == "nrt" and chosen["2025-01"] == "my"


# ── bake output ─────────────────────────────────────────────────────────────

def test_bake_writes_png_and_float_grid_with_counts_for_both_variables(cache, monkeypatch):
    _use(monkeypatch)
    oc.sync_months()
    d = cache / NRT_END
    assert sorted(p.name for p in d.iterdir()) == sorted(
        ["meta.json"] + [f"{v}.{e}" for v in oc.VARS for e in ("png", "npz")])
    assert not any(p.name.startswith(".tmp-") for p in cache.iterdir())
    for var in oc.VARS:
        grid, cnt = oc.load_grid(var, NRT_END)
        im = Image.open(d / f"{var}.png")
        assert im.mode == "RGBA" and im.size == (NT, NT)
        alpha = np.asarray(im)[..., 3]
        assert np.array_equal(alpha == 0, np.isnan(grid[::-1, :]))   # N -> S rows; NaN transparent
    meta = oc.read_month_meta(NRT_END)
    assert meta["grid"]["lon_global"] is False and meta["grid"]["lat0"] == -13.75
    assert meta["product"] == "OCEANCOLOUR_GLO_BGC_L4_NRT_009_102" and meta["doi"] == "10.48670/moi-00279"


# ── partial upstream failure ────────────────────────────────────────────────

@pytest.mark.parametrize("product,key", [("my", "plankton"), ("my", "pp"), ("nrt", "plankton"), ("nrt", "pp")])
def test_one_failed_variable_writes_no_month_and_keeps_the_previous_ones(cache, monkeypatch, product, key):
    _use(monkeypatch, my_end="2025-01", nrt_end="2025-01")
    assert len(oc.sync_months()["on_disk"]) == 12
    before = _snapshot(cache)
    var = _DS_KEYS[key]
    month = "2025-02"      # new from this product only; the other product stops at 2025-01
    _use(monkeypatch, my_end="2025-02" if product == "my" else "2025-01",
         nrt_end="2025-02" if product == "nrt" else "2025-01",
         fail={(product, key): [var]}, fail_months={month})
    res = oc.sync_months()
    assert list(res["failed"]) == [month] and res["baked"] == []
    assert not (cache / month).exists()
    assert not [p for p in cache.iterdir() if p.name.startswith(".")], "temporary files left behind"
    assert _snapshot(cache) == before        # byte-identical: nothing partial, nothing pruned


def test_misaligned_grids_are_refused(cache, monkeypatch):
    class _Shifted(_FakeCM):
        def open_dataset(self, dataset_id, variables, username, password):
            ds = super().open_dataset(dataset_id, variables, username, password)
            if "pp_" in dataset_id:
                ds._ds = ds._ds.assign_coords(longitude=ds._ds["longitude"] + 1.0 / 24.0)
            return ds

    monkeypatch.setattr(oc, "_copernicusmarine", _Shifted(
        {"my": _months(MY_FIRST, MY_END), "nrt": _months(NRT_FIRST, NRT_END)}))
    res = oc.sync_months()
    assert res["baked"] == [] and set(res["failed"]) == set(res["wanted"])
    assert list(cache.iterdir()) == []


# ── point statuses ──────────────────────────────────────────────────────────

def test_point_ok_no_data_and_not_covered_never_zero(cache, monkeypatch):
    _use(monkeypatch)
    with pytest.raises(LookupError):
        oc.point_value("chl", -12.0, -76.0)       # nothing baked yet
    oc.sync_months()
    _, cnt = oc.load_grid("pp", "2025-02")
    i, j = _find(cnt, lambda c: c == 36)
    lat, lon = _centre(i, j)
    ok = oc.point_value("pp", lat, lon, "2025-02")
    assert ok["status"] == "ok" and ok["pp_mg_m2_day"] > 0 and ok["unit"] == "mg m-2 day-1"
    assert ok["valid_fraction"] == 1.0 and ok["product_key"] == "my"
    assert ok["pp_mg_m2_day"] == float(oc.load_grid("pp", "2025-02")[0][i, j])
    assert oc.point_value("pp", lat, lon)["product_key"] == "nrt"            # latest month default
    i, j = _find(cnt, lambda c: c == 0)
    lat, lon = _centre(i, j)
    nd = oc.point_value("pp", lat, lon, "2025-02")
    assert nd["status"] == "no_data" and nd["pp_mg_m2_day"] is None
    assert oc.point_value("pp", -45.0, -77.0)["status"] == "not_covered"
    assert oc.point_value("pp", -12.0, 100.0)["status"] == "not_covered"
    assert oc.point_value("pp", -12.0, 100.0)["pp_mg_m2_day"] is None
    with pytest.raises(KeyError):
        oc.point_value("nppv", -12.0, -76.0)
    with pytest.raises(LookupError):
        oc.point_value("pp", -12.0, -76.0, "2019-01")


# ── retention ───────────────────────────────────────────────────────────────

def test_prune_keeps_twelve_months(cache, monkeypatch):
    _use(monkeypatch, my_end="2025-01", nrt_end="2025-01")
    assert oc.sync_months()["on_disk"] == oc.months_back("2025-01", 12)[::-1]
    _use(monkeypatch, my_end="2025-02", nrt_end="2025-02")
    res = oc.sync_months()
    assert res["baked"] == ["2025-02"]
    months = oc.complete_months()
    assert len(months) == 12 and months[0] == "2024-03" and months[-1] == "2025-02"
    assert not (cache / "2024-02").exists()
    (cache / "2023-01").mkdir()
    (cache / ".tmp-2025-03-1-abc").mkdir()
    oc.prune_old()
    assert sorted(p.name for p in cache.iterdir()) == months


def test_the_cache_root_is_separate_from_the_model_layers():
    from services import bgc_model
    assert oc.CACHE_DIR != bgc_model.CACHE_DIR
    assert oc.CACHE_DIR.name == "abyssal-ocean-colour"


# ── the scheduled path ──────────────────────────────────────────────────────

class _Logs:
    def __init__(self):
        self.ok, self.skipped = [], []

    async def log_sync(self, source, added, total):
        self.ok.append((source, added, total))

    async def log_sync_skipped(self, source, reason):
        self.skipped.append((source, reason))


@pytest.fixture
def logs(monkeypatch):
    from domains.fields import ocean_colour as dom
    lg = _Logs()
    monkeypatch.setattr(dom, "_log_sync", lg.log_sync)
    monkeypatch.setattr(dom, "_log_sync_skipped", lg.log_sync_skipped)
    return dom, lg


def test_sync_logs_on_the_nothing_new_path(cache, monkeypatch, logs):
    dom, lg = logs
    _use(monkeypatch)
    assert asyncio.run(dom.sync_ocean_colour()) == 12
    assert lg.ok == [("ocean-colour-satellite", 12, 12)]
    before = _snapshot(cache)
    assert asyncio.run(dom.sync_ocean_colour()) == 0
    assert lg.ok[-1] == ("ocean-colour-satellite", 0, 12), "a run that found nothing must still be logged"
    assert len(lg.ok) == 2 and lg.skipped == []
    assert _snapshot(cache) == before


def test_sync_logs_a_skip_when_every_month_fails(cache, monkeypatch, logs):
    dom, lg = logs
    allm = set(_months(MY_FIRST, NRT_END))
    _use(monkeypatch, fail={("my", "pp"): ["PP"], ("nrt", "pp"): ["PP"]}, fail_months=allm)
    assert asyncio.run(dom.sync_ocean_colour()) == 0
    assert lg.ok == [] and len(lg.skipped) == 1 and lg.skipped[0][0] == "ocean-colour-satellite"
    assert oc.complete_months() == []


def test_sync_logs_a_skip_when_the_upstream_cannot_be_opened(cache, monkeypatch, logs):
    dom, lg = logs
    monkeypatch.delenv("CMEMS_PASSWORD")
    monkeypatch.setattr(oc, "_copernicusmarine", object())
    assert asyncio.run(dom.sync_ocean_colour()) == 0
    assert len(lg.skipped) == 1 and "CMEMS" in lg.skipped[0][1]


def test_daily_task_waits_after_the_bgc_bake_then_bakes_then_sleeps_a_day(monkeypatch):
    import scheduling

    class Stop(Exception):
        pass

    sleeps, calls = [], []

    async def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) == 2:
            raise Stop

    async def fake_sync(force=False):
        calls.append(force)
        return 0

    monkeypatch.setattr(scheduling.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(scheduling.fields.ocean_colour, "sync_ocean_colour", fake_sync)
    with pytest.raises(Stop):
        asyncio.run(scheduling._ocean_colour_bake_task())
    d = scheduling._BAKE_STARTUP_DELAY
    assert sleeps == [d["ocean_colour"], 24 * 3600] and calls == [False]
    assert d["ocean_colour"] >= 480 and d["ocean_colour"] > d["bgc_model"]
    assert len(set(d.values())) == len(d)
    spec = next(s for s in scheduling.TASK_REGISTRY if s.name == "ocean-colour-satellite-daily-bake")
    assert spec.role == scheduling.ROLE_WORKER


def test_force_sync_and_registries_know_the_layer():
    import layer_ops
    import main
    import sync_sources
    assert "ocean-colour-satellite" in sync_sources.SYNC_SOURCES
    assert main._SOURCE_TO_ACTION["ocean-colour-satellite"] == "ocean-colour-satellite"
    assert layer_ops.LAYER_OPS["ocean-colour-satellite"]["sync_source"] == "ocean-colour-satellite"


# ── encoding ────────────────────────────────────────────────────────────────

def test_scales_clip_and_nan_is_transparent():
    t = oc._bgc.normalise(np.array([0.0, 0.03, 10.0, 65.0]), oc.VARS["chl"])
    assert t.tolist() == [0.0, 0.0, 1.0, 1.0]
    t = oc._bgc.normalise(np.array([5.0, 50.0, 3000.0, 9000.0]), oc.VARS["pp"])
    assert t.tolist() == [0.0, 0.0, 1.0, 1.0]
    rgba = oc._bgc.encode_with(np.array([[1.0, np.nan]], dtype="float32"), oc.VARS["chl"])
    assert rgba[0, 0, 3] == 255 and rgba[0, 1, 3] == 0


# ── endpoints ───────────────────────────────────────────────────────────────

@pytest.fixture
def client(cache, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth import get_api_key
    from domains.fields import ocean_colour as dom
    app = FastAPI()
    app.include_router(dom.router)
    app.dependency_overrides[get_api_key] = lambda: None
    return TestClient(app)


def test_endpoints(client, cache, monkeypatch):
    assert client.get("/v1/ocean-colour/meta").json()["months"] == []
    assert client.get("/v1/ocean-colour/chl/2025-02.png").status_code == 404
    _use(monkeypatch)
    oc.sync_months()
    meta = client.get("/v1/ocean-colour/meta").json()
    assert meta["latest"] == NRT_END and len(meta["months"]) == 12 and meta["months"] == sorted(meta["months"])
    assert meta["month_products"]["2025-02"] == "my" and meta["month_products"]["2025-03"] == "nrt"
    assert [v["key"] for v in meta["variables"]] == ["chl", "pp"]
    assert meta["products"]["my"]["doi"] == "10.48670/moi-00281" and meta["products"]["nrt"]["doi"] == "10.48670/moi-00279"
    assert "moi-00281" in meta["attribution"] and "moi-00279" in meta["attribution"]
    for v in meta["variables"]:
        assert v["unit"] and v["field"].endswith(("_m3", "_day")) and v["stats"]["n_valid"] > 0
        pos = [t["pos"] for t in v["ticks"]]
        assert pos == sorted(pos) and all(0.0 <= p <= 1.0 for p in pos)
        assert v["ramp"][0]["pos"] == 0.0 and v["ramp"][-1]["pos"] == 1.0
    png = client.get(f"/v1/ocean-colour/pp/{NRT_END}.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get("/v1/ocean-colour/nppv/2025-02.png").status_code == 404
    assert client.get("/v1/ocean-colour/chl/2025-13.png").status_code == 404
    _, cnt = oc.load_grid("chl", "2025-02")
    i, j = _find(cnt, lambda c: c == 36)
    lat, lon = _centre(i, j)
    q = dict(lat=lat, lon=lon, var="chl", month="2025-02")
    ok = client.get("/v1/ocean-colour/point", params=q).json()
    assert ok["status"] == "ok" and ok["unit"] == "mg m-3" and ok["chl_mg_m3"] is not None
    assert ok["valid_fraction"] == 1.0 and ok["product_key"] == "my" and ok["product_label"] == "multi-year (reprocessed)"
    i, j = _find(cnt, lambda c: c == 0)
    lat, lon = _centre(i, j)
    nd = client.get("/v1/ocean-colour/point", params=dict(q, lat=lat, lon=lon)).json()
    assert nd["status"] == "no_data" and nd["chl_mg_m3"] is None and "cloud" in nd["reason"]
    assert client.get("/v1/ocean-colour/point", params=dict(q, lat=-85.0)).json()["status"] == "not_covered"
    assert client.get("/v1/ocean-colour/point", params=dict(q, var="nppv")).status_code == 400
    assert client.get("/v1/ocean-colour/point", params=dict(q, lat=95)).status_code == 400
    assert client.get("/v1/ocean-colour/point", params=dict(q, month="2025/02")).status_code == 400
    assert client.get("/v1/ocean-colour/point", params=dict(q, month="2019-01")).status_code == 404
