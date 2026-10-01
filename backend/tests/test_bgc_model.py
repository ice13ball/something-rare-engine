# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""ocean-nutrients-model: Copernicus Marine BGC surface fields.

The fixture is a REAL 10 x 10 degree excerpt (Peru coast, 2026-08, no3 / po4 /
chl / nppv), see tests/fixtures/bgc_model/SOURCE.txt. The Copernicus client is
replaced by a test double that serves that excerpt. The double scales the real
values by a per-month factor (1 + months-since-2021-10 / 100) ONLY so that
different months can be told apart; those scaled values are not claimed real.
Everything under test (axis handling, bake, atomicity, sampler, endpoints) runs
for real.
"""
from __future__ import annotations

import asyncio
import pathlib
from datetime import datetime, timezone

import numpy as np
import pytest
import xarray as xr
from PIL import Image

from services import bgc_model as bgc

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "bgc_model" / "bgc_surface_window_2026-08.npz"
_Z = np.load(FIXTURE)
FIX = {k: np.asarray(_Z[k]) for k in ("no3", "po4", "chl", "nppv")}
FIX_LAT = np.asarray(_Z["lat"])
FIX_LON = np.asarray(_Z["lon"])

# A past month on purpose: the time axis ends here, never at the current month.
AXIS_END = "2025-02"
FIRST = "2021-10"


def _months(first: str, last: str) -> list[str]:
    out, y, m = [], int(first[:4]), int(first[5:])
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _factor(month: str) -> float:
    return 1.0 + ((int(month[:4]) - 2021) * 12 + int(month[5:]) - 10) / 100.0


class _VarProxy:
    def __init__(self, da, fail_months):
        self._da, self._fail = da, fail_months

    def sel(self, time):
        if bgc.month_key(time) in self._fail:
            raise RuntimeError("503 Service Unavailable (test double)")
        return self._da.sel(time=time)


class _DS:
    """The slice of an xarray Dataset the bake touches, plus injected failures."""

    def __init__(self, ds, fail_vars=None, fail_months=()):
        self._ds, self._fail_vars, self._fail_months = ds, set(fail_vars or ()), set(fail_months)
        self.closed = False

    def __contains__(self, name):
        return name in self._ds

    def __getitem__(self, name):
        if name in self._fail_vars:
            return _VarProxy(self._ds[name], self._fail_months)
        return self._ds[name]

    def close(self):
        self.closed = True


def _window_dataset(variables, months, lon_shift=0.0):
    times = np.array([f"{m}-01" for m in months], dtype="datetime64[ns]")
    data = {}
    for v in variables:
        stack = np.stack([FIX[v] * _factor(m) for m in months])[:, None].astype("float32")
        data[v] = (("time", "depth", "latitude", "longitude"), stack)
    return xr.Dataset(data, coords=dict(time=times, depth=[0.494], latitude=FIX_LAT,
                                        longitude=FIX_LON + lon_shift))


def _global_dataset(variables, month):
    """Full 681 x 1440 product grid (lat -80..90, lon -180..179.75), NaN except for
    the real window, placed at its true coordinates. One month, no copies in time."""
    lat = np.arange(-80.0, 90.0001, 0.25)
    lon = np.arange(-180.0, 180.0, 0.25)
    assert lat.size == 681 and lon.size == 1440
    data = {}
    for v in variables:
        full = np.full((681, 1440), np.nan, dtype="float32")
        full[240:281, 380:421] = FIX[v]
        data[v] = (("time", "depth", "latitude", "longitude"), full[None, None])
    return xr.Dataset(data, coords=dict(time=np.array([f"{month}-01"], dtype="datetime64[ns]"),
                                        depth=[0.494], latitude=lat, longitude=lon))


class _FakeCM:
    def __init__(self, axes, *, fail=None, fail_months=(), lon_shift=None, global_month=None):
        self.axes, self.fail, self.fail_months = axes, fail or {}, fail_months
        self.lon_shift, self.global_month = lon_shift or {}, global_month
        self.opened = []

    def open_dataset(self, dataset_id, variables, minimum_depth, maximum_depth, username, password):
        assert (minimum_depth, maximum_depth) == (0.0, 1.0), "surface level only"
        key = next(k for k, (ds_id, _) in bgc.DATASETS.items() if ds_id == dataset_id)
        assert variables == bgc.DATASETS[key][1]
        if self.global_month:
            ds = _global_dataset(variables, self.global_month)
        else:
            ds = _window_dataset(variables, self.axes[key], self.lon_shift.get(key, 0.0))
        proxy = _DS(ds, fail_vars=self.fail.get(key), fail_months=self.fail_months)
        self.opened.append(proxy)
        return proxy


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(bgc, "CACHE_DIR", tmp_path / "bgc")
    monkeypatch.setattr(bgc, "_GRID_CACHE", {})
    monkeypatch.setenv("CMEMS_USERNAME", "u")
    monkeypatch.setenv("CMEMS_PASSWORD", "p")
    return tmp_path / "bgc"


def _use(monkeypatch, end=AXIS_END, **kw):
    axis = _months(FIRST, end)
    cm = _FakeCM({k: axis for k in bgc.DATASETS}, **kw)
    monkeypatch.setattr(bgc, "_copernicusmarine", cm)
    return cm


def _snapshot(root: pathlib.Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _cell(valid=True):
    """A (row, col) in the window that holds a value / is NaN in the real excerpt."""
    ok = np.isfinite(FIX["no3"])
    r, c = np.argwhere(ok if valid else ~ok)[len(np.argwhere(ok if valid else ~ok)) // 2]
    return int(r), int(c)


# ── derived variable ────────────────────────────────────────────────────────

def test_nstar_is_no3_minus_16_po4_at_known_cells(cache, monkeypatch):
    _use(monkeypatch)
    bgc.sync_months()
    f = _factor(AXIS_END)
    nstar = bgc.load_grid("nstar", AXIS_END)
    for r, c in [(0, 0), (10, 30), (25, 12), (38, 3)]:
        no3, po4 = float(FIX["no3"][r, c]) * f, float(FIX["po4"][r, c]) * f
        assert np.isfinite(no3)
        expected = no3 - 16.0 * po4  # independent of derive_nstar
        assert nstar[r, c] == pytest.approx(expected, abs=2e-4)
        assert nstar[r, c] != pytest.approx(no3 - po4, abs=1e-2)  # the factor 16 matters
    r, c = _cell(valid=False)
    assert np.isnan(nstar[r, c])  # NaN in the inputs stays NaN


# ── NaN, coverage ───────────────────────────────────────────────────────────

def test_nan_is_no_data_not_zero(cache, monkeypatch):
    _use(monkeypatch)
    bgc.sync_months()
    r, c = _cell(valid=False)
    for var in bgc.VARS:
        out = bgc.point_value(var, float(FIX_LAT[r]), float(FIX_LON[c]))
        assert out["status"] == "no_data"
        assert out[bgc.VARS[var]["field"]] is None
    r, c = _cell(valid=True)
    ok = bgc.point_value("no3", float(FIX_LAT[r]), float(FIX_LON[c]))
    assert ok["status"] == "ok" and ok["no3_mmol_m3"] > 0.0


def test_south_of_80S_is_not_covered_but_a_nan_cell_is_no_data(cache, monkeypatch):
    month = "2026-08"
    monkeypatch.setattr(bgc, "_copernicusmarine", _FakeCM({}, global_month=month))
    bgc.sync_months()
    assert bgc.complete_months() == [month]
    g = bgc.read_month_meta(month)["grid"]
    assert (g["n_lat"], g["n_lon"], g["lat0"], g["lon0"], g["lon_global"]) == (681, 1440, -80.0, -180.0, True)
    below = bgc.point_value("chl", -80.5, 10.0)
    assert below["status"] == "not_covered" and below["chl_mg_m3"] is None
    edge = bgc.point_value("chl", -80.0, 10.0)  # inside the grid, NaN there
    assert edge["status"] == "no_data"
    r, c = 20, 20  # window cell for (-15, -80)
    hit = bgc.point_value("no3", -15.0, -80.0)
    assert hit["status"] == "ok" and hit["no3_mmol_m3"] == pytest.approx(float(FIX["no3"][r, c]))
    wrap = bgc.point_value("no3", 0.0, 179.95)  # wraps to the column at -180
    assert wrap["status"] == "no_data" and wrap["cell"]["lon"] == -180.0
    assert bgc.point_value("no3", 90.0, 0.0)["status"] == "no_data"


def test_window_grid_reports_outside_coordinates_as_not_covered(cache, monkeypatch):
    _use(monkeypatch)
    bgc.sync_months()
    assert bgc.point_value("no3", -45.0, -80.0)["status"] == "not_covered"
    assert bgc.point_value("no3", -15.0, 100.0)["status"] == "not_covered"


# ── bake output ─────────────────────────────────────────────────────────────

def test_bake_writes_png_and_float_grid_for_every_variable(cache, monkeypatch):
    _use(monkeypatch)
    res = bgc.sync_months()
    assert res["failed"] == {}
    d = cache / AXIS_END
    assert sorted(p.name for p in d.iterdir()) == sorted(
        ["meta.json"] + [f"{v}.{e}" for v in bgc.VARS for e in ("png", "npz")])
    assert not any(p.name.startswith(".tmp-") for p in cache.iterdir())
    for var in bgc.VARS:
        grid = bgc.load_grid(var, AXIS_END)
        assert grid.dtype == np.float32 and grid.shape == (41, 41)
        im = Image.open(d / f"{var}.png")
        assert im.mode == "RGBA" and im.size == (41, 41)
        alpha = np.asarray(im)[..., 3]
        # PNG rows run north -> south, the grid south -> north; NaN is transparent
        assert np.array_equal(alpha == 0, np.isnan(grid[::-1, :]))
    r, c = _cell(valid=True)
    assert 0 < bgc.read_month_meta(AXIS_END)["stats"]["no3"]["n_valid"] <= 41 * 41


def test_point_returns_the_exact_grid_value_and_unit(cache, monkeypatch):
    _use(monkeypatch)
    bgc.sync_months()
    r, c = _cell(valid=True)
    f = _factor(AXIS_END)
    units = {"no3": ("no3_mmol_m3", "mmol m-3"), "chl": ("chl_mg_m3", "mg m-3"),
             "nppv": ("nppv_mg_m3_day", "mg m-3 day-1"), "nstar": ("nstar_mmol_m3", "mmol m-3")}
    for var, (field, unit) in units.items():
        out = bgc.point_value(var, float(FIX_LAT[r]), float(FIX_LON[c]), AXIS_END)
        assert out["status"] == "ok" and out["unit"] == unit and out["value_field"] == field
        assert out[field] == float(bgc.load_grid(var, AXIS_END)[r, c])  # not the 8-bit PNG
    assert units["no3"][0] in bgc.point_value("no3", float(FIX_LAT[r]), float(FIX_LON[c]))
    exp = FIX["chl"][r, c] * f
    assert bgc.point_value("chl", float(FIX_LAT[r]), float(FIX_LON[c]))["chl_mg_m3"] == pytest.approx(float(exp), rel=1e-6)


def test_unknown_variable_and_month(cache, monkeypatch):
    _use(monkeypatch)
    with pytest.raises(LookupError):
        bgc.point_value("no3", -15.0, -80.0)  # nothing baked yet
    bgc.sync_months()
    with pytest.raises(KeyError):
        bgc.point_value("po4", -15.0, -80.0)  # read, but deliberately not served
    with pytest.raises(LookupError):
        bgc.point_value("no3", -15.0, -80.0, "2019-01")


# ── the time axis decides what is newest ────────────────────────────────────

def test_newest_month_comes_from_the_time_axis_not_the_clock(cache, monkeypatch):
    _use(monkeypatch)
    res = bgc.sync_months()
    now_month = datetime.now(timezone.utc).strftime("%Y-%m")
    assert now_month != AXIS_END
    assert res["newest"] == AXIS_END
    assert res["wanted"] == bgc.months_back(AXIS_END, 12)
    assert bgc.complete_months()[-1] == AXIS_END
    assert not (cache / now_month).exists()


def test_newest_is_the_latest_month_present_in_all_three_datasets(cache, monkeypatch):
    axis = _months(FIRST, AXIS_END)
    cm = _FakeCM({"nut": axis, "pft": axis, "bio": axis[:-1]})  # bio is a month behind
    monkeypatch.setattr(bgc, "_copernicusmarine", cm)
    res = bgc.sync_months()
    assert res["newest"] == axis[-2]
    assert axis[-1] not in bgc.complete_months()


# ── partial upstream failure ────────────────────────────────────────────────

@pytest.mark.parametrize("fail_key,fail_var", [("nut", "po4"), ("pft", "chl"), ("bio", "nppv")])
def test_failed_variable_writes_nothing_and_keeps_the_previous_month(cache, monkeypatch, fail_key, fail_var):
    _use(monkeypatch, end="2025-01")
    first = bgc.sync_months()
    assert len(first["on_disk"]) == 12
    before = _snapshot(cache)
    _use(monkeypatch, end=AXIS_END, fail={fail_key: [fail_var]}, fail_months={AXIS_END})
    res = bgc.sync_months()
    assert list(res["failed"]) == [AXIS_END] and res["baked"] == []
    assert not (cache / AXIS_END).exists()
    assert not [p for p in cache.iterdir() if p.name.startswith(".")], "temporary files left behind"
    assert _snapshot(cache) == before  # byte-identical: nothing partial, nothing pruned
    assert bgc.complete_months()[-1] == "2025-01"


def test_misaligned_grids_are_refused(cache, monkeypatch):
    _use(monkeypatch, lon_shift={"pft": 0.25})
    res = bgc.sync_months()
    assert res["baked"] == [] and set(res["failed"]) == set(res["wanted"])
    assert list(cache.iterdir()) == []


# ── retention ───────────────────────────────────────────────────────────────

def test_prune_keeps_twelve_months(cache, monkeypatch):
    _use(monkeypatch, end="2025-01")
    assert bgc.sync_months()["on_disk"] == bgc.months_back("2025-01", 12)[::-1]
    _use(monkeypatch, end=AXIS_END)
    res = bgc.sync_months()
    assert res["baked"] == [AXIS_END]
    months = bgc.complete_months()
    assert len(months) == 12 and months[0] == "2024-03" and months[-1] == AXIS_END
    assert not (cache / "2024-02").exists()
    (cache / "2023-01").mkdir()  # an incomplete directory is swept as well
    (cache / ".tmp-2025-03-1-abc").mkdir()
    bgc.prune_old()
    assert sorted(p.name for p in cache.iterdir()) == months


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
    from domains.fields import bgc_model as dom
    lg = _Logs()
    monkeypatch.setattr(dom, "_log_sync", lg.log_sync)
    monkeypatch.setattr(dom, "_log_sync_skipped", lg.log_sync_skipped)
    return dom, lg


def test_sync_logs_on_the_nothing_new_path(cache, monkeypatch, logs):
    dom, lg = logs
    _use(monkeypatch)
    assert asyncio.run(dom.sync_bgc_model()) == 12
    assert lg.ok == [("ocean-nutrients-model", 12, 12)]
    before = _snapshot(cache)
    assert asyncio.run(dom.sync_bgc_model()) == 0
    assert lg.ok[-1] == ("ocean-nutrients-model", 0, 12), "a run that found nothing must still be logged"
    assert len(lg.ok) == 2 and lg.skipped == []
    assert _snapshot(cache) == before


def test_sync_logs_a_skip_when_every_month_fails(cache, monkeypatch, logs):
    dom, lg = logs
    _use(monkeypatch, fail={"bio": ["nppv"]}, fail_months=set(_months(FIRST, AXIS_END)))
    assert asyncio.run(dom.sync_bgc_model()) == 0
    assert lg.ok == [] and len(lg.skipped) == 1 and lg.skipped[0][0] == "ocean-nutrients-model"
    assert bgc.complete_months() == []


def test_sync_logs_a_skip_when_the_upstream_cannot_be_opened(cache, monkeypatch, logs):
    dom, lg = logs
    monkeypatch.delenv("CMEMS_PASSWORD")
    monkeypatch.setattr(bgc, "_copernicusmarine", object())
    assert asyncio.run(dom.sync_bgc_model()) == 0
    assert len(lg.skipped) == 1 and "CMEMS" in lg.skipped[0][1]


def test_daily_task_waits_then_bakes_then_sleeps_a_day(monkeypatch):
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
    monkeypatch.setattr(scheduling.fields.bgc_model, "sync_bgc_model", fake_sync)
    with pytest.raises(Stop):
        asyncio.run(scheduling._ocean_nutrients_bake_task())
    assert sleeps == [scheduling._BAKE_STARTUP_DELAY["bgc_model"], 24 * 3600]
    assert 240 <= sleeps[0] <= 600 and calls == [False]
    assert len(set(scheduling._BAKE_STARTUP_DELAY.values())) == len(scheduling._BAKE_STARTUP_DELAY)
    spec = next(s for s in scheduling.TASK_REGISTRY if s.name == "ocean-nutrients-model-daily-bake")
    assert spec.role == scheduling.ROLE_WORKER


def test_force_sync_and_registries_know_the_layer():
    import layer_ops
    import main
    import sync_sources
    assert "ocean-nutrients-model" in sync_sources.SYNC_SOURCES
    assert main._SOURCE_TO_ACTION["ocean-nutrients-model"] == "ocean-nutrients-model"
    assert layer_ops.LAYER_OPS["ocean-nutrients-model"]["sync_source"] == "ocean-nutrients-model"


# ── encoding ────────────────────────────────────────────────────────────────

def test_scales_clip_instead_of_going_nan_and_nstar_zero_is_neutral():
    cfg = bgc.VARS["nppv"]
    t = bgc.normalise(np.array([-0.5, 0.0, 0.01, 50.0, 2000.0]), cfg)
    assert t.tolist() == [0.0, 0.0, 0.0, 1.0, 1.0]  # polar-night zeros and tiny negatives stay coloured
    rgba = bgc.encode_to_rgba(np.array([[0.0, np.nan, -15.0, 15.0]], dtype="float32"), "nstar")
    assert tuple(rgba[0, 0, :3]) == (240, 240, 240) and rgba[0, 0, 3] == 255  # 0 is the neutral colour
    assert rgba[0, 1, 3] == 0  # NaN is transparent
    assert tuple(rgba[0, 2, :3]) == (30, 60, 150) and tuple(rgba[0, 3, :3]) == (130, 20, 30)
    assert bgc.normalise(np.array([0.0]), bgc.VARS["no3"])[0] == 0.0
    assert bgc.normalise(np.array([35.0]), bgc.VARS["no3"])[0] == 1.0


# ── endpoints ───────────────────────────────────────────────────────────────

@pytest.fixture
def client(cache, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth import get_api_key
    from domains.fields import bgc_model as dom
    app = FastAPI()
    app.include_router(dom.router)
    app.dependency_overrides[get_api_key] = lambda: None
    return TestClient(app)


def test_endpoints(client, cache, monkeypatch):
    assert client.get("/v1/bgc-model/meta").json()["months"] == []
    assert client.get("/v1/bgc-model/no3/2025-02.png").status_code == 404
    _use(monkeypatch)
    bgc.sync_months()
    meta = client.get("/v1/bgc-model/meta").json()
    assert meta["latest"] == AXIS_END and len(meta["months"]) == 12 and meta["months"] == sorted(meta["months"])
    assert [v["key"] for v in meta["variables"]] == ["no3", "chl", "nppv", "nstar"]
    assert meta["product"]["doi"] == "10.48670/moi-00015"
    assert "Model output" in meta["caveat"] and "10.48670/moi-00015" in meta["attribution"]
    for v in meta["variables"]:
        assert v["unit"] and v["field"].endswith(("_m3", "_day")) and v["stats"]["n_valid"] > 0
        pos = [t["pos"] for t in v["ticks"]]
        assert pos == sorted(pos) and all(0.0 <= p <= 1.0 for p in pos)
        assert v["ramp"][0]["pos"] == 0.0 and v["ramp"][-1]["pos"] == 1.0
    png = client.get(f"/v1/bgc-model/chl/{AXIS_END}.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get("/v1/bgc-model/po4/2025-02.png").status_code == 404
    assert client.get("/v1/bgc-model/chl/2025-13.png").status_code == 404
    r, c = _cell(valid=True)
    q = dict(lat=float(FIX_LAT[r]), lon=float(FIX_LON[c]), var="nppv")
    ok = client.get("/v1/bgc-model/point", params=q).json()
    assert ok["status"] == "ok" and ok["unit"] == "mg m-3 day-1" and ok["nppv_mg_m3_day"] is not None
    assert "not measurements" in ok["caveat"]
    r2, c2 = _cell(valid=False)
    nd = client.get("/v1/bgc-model/point", params=dict(q, lat=float(FIX_LAT[r2]), lon=float(FIX_LON[c2]))).json()
    assert nd["status"] == "no_data" and nd["nppv_mg_m3_day"] is None
    nc = client.get("/v1/bgc-model/point", params=dict(q, lat=-85.0, lon=0.0)).json()
    assert nc["status"] == "not_covered"
    assert client.get("/v1/bgc-model/point", params=dict(q, var="po4")).status_code == 400
    assert client.get("/v1/bgc-model/point", params=dict(q, lat=95)).status_code == 400
    assert client.get("/v1/bgc-model/point", params=dict(q, month="2025/02")).status_code == 400
    assert client.get("/v1/bgc-model/point", params=dict(q, month="2019-01")).status_code == 404
