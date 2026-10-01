# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Satellite ocean colour: chlorophyll-a and primary production, monthly, 0.25 degree.

Layer id ``ocean-colour-satellite``. Source: Copernicus Marine Service,
Copernicus-GlobColour L4 monthly, 4 km (1/24 degree) global ocean-colour
observations, two products:

* ``my``  OCEANCOLOUR_GLO_BGC_L4_MY_009_104   multi-year, reprocessed
* ``nrt`` OCEANCOLOUR_GLO_BGC_L4_NRT_009_102  near-real-time

Variables served (the unit is part of the API field name, see ``VARS``):

* ``chl`` chlorophyll-a, mg m-3
* ``pp``  primary productivity, mg m-2 day-1 (the datasets' own unit string; the
          standard name says "expressed as carbon"). ⛔ A WATER-COLUMN INTEGRAL: it
          cannot be compared with the surface volumetric ``nppv`` of the model layer
          ``ocean-nutrients-model``.

Which product a month comes from is decided from the datasets' ACTUAL time axes,
never from an assumed lag between them: a month is taken from the multi-year product
when that has it (for both variables), otherwise from the near-real-time one, and the
newest month is the newest across both axes. The product is recorded per month. A month
baked from the near-real-time product is re-baked once the multi-year product has it.

Regridding: the 1/24 degree field is block-averaged 6 x 6 onto the SAME 0.25 degree cell
edges as ``ocean-nutrients-model`` (centres on multiples of 0.25, so the cells line up).
NaN is ignored in the mean; a target cell with no valid source cell is NaN; the number of
valid source cells (0..36) is stored beside the mean and returned as ``valid_fraction``.
The work is done in latitude strips, so no more than one strip of one variable is in
memory at a time (the full-resolution field is 149 MB).

Storage (``CACHE_DIR``, env ``OCEAN_COLOUR_CACHE_DIR``)::

    <yyyy-mm>/<var>.png    colour-mapped RGBA texture, rows run N -> S
    <yyyy-mm>/<var>.npz    float32 ``v`` and uint8 ``n`` (valid source cells), rows S -> N
    <yyyy-mm>/meta.json    grid geometry, statistics, provenance (written last)

Atomic month writes, month arithmetic, ramps and the PNG encoder come from
``services.bgc_model``. This directory is deliberately separate from the model layer's:
its prune would delete foreign subdirectories.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
from datetime import datetime, timezone

import numpy as np

from services import bgc_model as _bgc

try:
    from PIL import Image as _Image
    _PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _Image = None
    _PIL_AVAILABLE = False

try:
    import copernicusmarine as _copernicusmarine
except ImportError:  # pragma: no cover
    _copernicusmarine = None

log = logging.getLogger("ocean_colour")

SYNC_SOURCE = "ocean-colour-satellite"
LAYER_ID = "ocean-colour-satellite"

CACHE_DIR = pathlib.Path(os.getenv("OCEAN_COLOUR_CACHE_DIR", "/var/cache/abyssal-ocean-colour"))

MONTHS_KEPT = 12
BLOCK = 6                      # 1/24 degree -> 1/4 degree
SRC_STEP = 1.0 / 24.0
TARGET_STEP = 0.25
STRIP_BLOCK_ROWS = 100         # 100 target rows = 600 source rows = ~20 MB float32
_FILL_BELOW = -990.0           # the datasets' fill is -999
_FILL_ABS = 1e20

LICENCE_URL = "https://marine.copernicus.eu/user-corner/service-commitments-and-licence"

# Product key -> metadata. Order matters: the first one is the preferred product.
PRODUCTS: dict[str, dict] = {
    "my": dict(
        id="OCEANCOLOUR_GLO_BGC_L4_MY_009_104",
        title="Global Ocean Colour (Copernicus-GlobColour), Bio-Geo-Chemical, L4 "
              "(monthly and interpolated) from Satellite Observations (1997-ongoing)",
        label="multi-year (reprocessed)", doi="10.48670/moi-00281",
        datasets={"plankton": "cmems_obs-oc_glo_bgc-plankton_my_l4-multi-4km_P1M",
                  "pp": "cmems_obs-oc_glo_bgc-pp_my_l4-multi-4km_P1M"}),
    "nrt": dict(
        id="OCEANCOLOUR_GLO_BGC_L4_NRT_009_102",
        title="Global Ocean Colour (Copernicus-GlobColour), Bio-Geo-Chemical, L4 "
              "(monthly and interpolated) from Satellite Observations (Near Real Time)",
        label="near-real-time", doi="10.48670/moi-00279",
        datasets={"plankton": "cmems_obs-oc_glo_bgc-plankton_nrt_l4-multi-4km_P1M",
                  "pp": "cmems_obs-oc_glo_bgc-pp_nrt_l4-multi-4km_P1M"}),
}
for _k, _p in PRODUCTS.items():
    _p["doi_url"] = f"https://doi.org/{_p['doi']}"
    _p["url"] = f"https://data.marine.copernicus.eu/product/{_p['id']}/description"

ATTRIBUTION = ("Generated using E.U. Copernicus Marine Service Information; "
               + "; ".join(p["doi_url"] for p in PRODUCTS.values()))
NO_DATA_REASON = ("no satellite observation this month (cloud, sea ice, polar night or land)")
CAVEAT = ("Satellite observations (Copernicus-GlobColour, merged ocean-colour sensors), "
          "monthly means averaged from 4 km to 0.25 degree. Primary production is a "
          "water-column integral derived from satellite chlorophyll by a model.")

# dataset key -> (variable read from it)
SRC_VAR = {"plankton": "CHL", "pp": "PP"}

# Ranges are measured on the live 2026-08 field at 0.25 degree (719 x 1440, 43 % NaN):
#   chl  p1 0.035  p5 0.046  p50 0.134  p95 1.91  p99 10.9  max 65   -> log, 0.03..10
#   pp   p1 67     p5 81     p50 324    p95 1254  p99 3050  max 9948 -> log, 50..3000
# The model layer's chlorophyll scale (0.03..1.5) is NOT reused: 7.5 % of the satellite
# cells exceed 1.5 (coastal and high-latitude water), so it would paint them one colour.
# Same ramp family, so the two layers still read alike.
VARS: dict[str, dict] = {
    "chl": dict(
        label="Chlorophyll-a (satellite)", unit="mg m-3", field="chl_mg_m3", dataset="plankton",
        scale="log", vmin=0.03, vmax=10.0, cmap="chl_green",
        ticks=[0.03, 0.1, 1.0, 10.0],
        note="Monthly mean chlorophyll-a concentration in the surface layer seen by the satellite."),
    "pp": dict(
        label="Primary production (satellite, column)", unit="mg m-2 day-1",
        field="pp_mg_m2_day", dataset="pp",
        scale="log", vmin=50.0, vmax=3000.0, cmap="npp_magma",
        ticks=[50.0, 100.0, 500.0, 3000.0],
        note=("Primary productivity integrated over the water column, in mg m-2 per day "
              "(expressed as carbon). Not comparable with the model layer's surface "
              "volumetric rate.")),
}


class UpstreamError(RuntimeError):
    """The Copernicus Marine request failed or returned something unusable."""


# ──────────────────────────────────────────────────────────────────────────────
# Regridding
# ──────────────────────────────────────────────────────────────────────────────

def _axis_blocks(c: np.ndarray, name: str) -> tuple[int, int]:
    """(first aligned index, number of whole 6-cell blocks) on one source axis.

    Target cell edges sit at k * 0.25 + 0.125, i.e. at index 3 (mod 6) of the source
    edges, which are multiples of 1/24."""
    if c.size < BLOCK:
        raise UpstreamError(f"{name} axis has {c.size} point(s)")
    d = np.diff(c.astype("float64"))
    if not np.allclose(d, SRC_STEP, rtol=0.0, atol=1e-4):
        raise UpstreamError(f"{name} axis is not regular at 1/24 degree")
    edge = np.round((c.astype("float64") - SRC_STEP / 2) * 24.0).astype("int64")
    aligned = np.nonzero(edge % BLOCK == 3)[0]
    if aligned.size == 0:
        raise UpstreamError(f"{name} axis does not line up with the 0.25 degree grid")
    i0 = int(aligned[0])
    return i0, (c.size - i0) // BLOCK


def block_geometry(lat: np.ndarray, lon: np.ndarray) -> dict:
    """Where the 0.25 degree cells sit for a source grid, and how to cut them out."""
    lat_i0, n_lat = _axis_blocks(lat, "latitude")
    lon_global = bool(abs(lon.size * SRC_STEP - 360.0) < 1e-3)
    if lon_global:
        # The cell centred on a multiple of 0.25 near the antimeridian straddles the
        # array seam: its 6 source columns are the last 3 and the first 3.
        lon_i0 = _axis_blocks(lon, "longitude")[0]
        n_lon = lon.size // BLOCK
        lon0 = float(lon[lon_i0]) + 2.5 * SRC_STEP - 6 * SRC_STEP
    else:
        lon_i0, n_lon = _axis_blocks(lon, "longitude")
        lon0 = float(lon[lon_i0]) + 2.5 * SRC_STEP
    if n_lat < 1 or n_lon < 1:
        raise UpstreamError("no whole 0.25 degree cell inside the grid")
    lat0 = float(lat[lat_i0]) + 2.5 * SRC_STEP
    lat0, lon0 = round(lat0 / TARGET_STEP) * TARGET_STEP, round(lon0 / TARGET_STEP) * TARGET_STEP
    lat_max = lat0 + (n_lat - 1) * TARGET_STEP
    lon_max = lon0 + (n_lon - 1) * TARGET_STEP
    return {
        "lat_i0": lat_i0, "lon_i0": lon_i0, "n_lat": n_lat, "n_lon": n_lon,
        "grid": {
            "lat0": lat0, "lon0": lon0, "step": TARGET_STEP, "n_lat": n_lat, "n_lon": n_lon,
            "lat_max": lat_max, "lon_max": lon_max, "lon_global": lon_global,
            # pixel EDGES [west, south, east, north]; the cell centres are the coords
            "bounds": [lon0 - TARGET_STEP / 2, lat0 - TARGET_STEP / 2,
                       lon_max + TARGET_STEP / 2, lat_max + TARGET_STEP / 2],
        },
    }


def block_mean(a: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """6 x 6 block mean with NaN ignored. (H, W) multiples of 6 -> (mean float32, count
    uint8). A block with no valid cell is NaN with count 0, never 0.0."""
    h, w = a.shape
    if h % BLOCK or w % BLOCK:
        raise ValueError(f"shape {a.shape} is not a multiple of {BLOCK}")
    b = a.reshape(h // BLOCK, BLOCK, w // BLOCK, BLOCK)
    valid = np.isfinite(b)
    count = valid.sum(axis=(1, 3))
    total = np.where(valid, b, 0.0).sum(axis=(1, 3), dtype="float64")
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(count > 0, total / np.maximum(count, 1), np.nan)
    return mean.astype("float32"), count.astype("uint8")


def _clean(raw: np.ndarray) -> np.ndarray:
    a = np.asarray(raw, dtype="float32")
    return np.where(np.isfinite(a) & (a > _FILL_BELOW) & (np.abs(a) < _FILL_ABS), a, np.nan).astype("float32")


def coarsen_field(da, geo: dict) -> tuple[np.ndarray, np.ndarray]:
    """One (latitude, longitude) DataArray at 1/24 degree -> (mean, count) on the
    0.25 degree grid of `geo`, read and reduced in latitude strips."""
    if tuple(da.dims) != ("latitude", "longitude"):
        raise UpstreamError(f"expected (latitude, longitude), got {da.dims}")
    n_lat, n_lon = geo["n_lat"], geo["n_lon"]
    mean = np.full((n_lat, n_lon), np.nan, dtype="float32")
    count = np.zeros((n_lat, n_lon), dtype="uint8")
    lon_global = geo["grid"]["lon_global"]
    for r0 in range(0, n_lat, STRIP_BLOCK_ROWS):
        r1 = min(r0 + STRIP_BLOCK_ROWS, n_lat)
        s0 = geo["lat_i0"] + r0 * BLOCK
        strip = _clean(da.isel(latitude=slice(s0, geo["lat_i0"] + r1 * BLOCK)).values)  # network read
        if lon_global:
            strip = np.roll(strip, BLOCK - geo["lon_i0"], axis=1)
        else:
            strip = strip[:, geo["lon_i0"]: geo["lon_i0"] + n_lon * BLOCK]
        mean[r0:r1], count[r0:r1] = block_mean(strip)
        del strip
    return mean, count


# ──────────────────────────────────────────────────────────────────────────────
# Months and storage
# ──────────────────────────────────────────────────────────────────────────────

month_key = _bgc.month_key
valid_month = _bgc.valid_month
months_back = _bgc.months_back


def _month_dir(month: str) -> pathlib.Path:
    return CACHE_DIR / month


def is_complete(month: str) -> bool:
    d = _month_dir(month)
    if not (d / "meta.json").is_file():
        return False
    return all((d / f"{v}.png").is_file() and (d / f"{v}.npz").is_file() for v in VARS)


def complete_months() -> list[str]:
    """Months fully on disk, oldest first."""
    if not CACHE_DIR.is_dir():
        return []
    return sorted(p.name for p in CACHE_DIR.iterdir()
                  if p.is_dir() and valid_month(p.name) and is_complete(p.name))


def read_month_meta(month: str) -> dict | None:
    p = _month_dir(month) / "meta.json"
    return json.loads(p.read_text()) if p.is_file() else None


def png_path(var: str, month: str) -> pathlib.Path | None:
    if var not in VARS or not valid_month(month):
        return None
    p = _month_dir(month) / f"{var}.png"
    return p if p.is_file() else None


def prune_old(keep: int = MONTHS_KEPT) -> int:
    return _bgc.prune_months(CACHE_DIR, keep, is_complete)


def _write_month(month: str, fields: dict[str, tuple[np.ndarray, np.ndarray]],
                 geometry: dict, extra: dict) -> None:
    """Build the month in a temporary directory and rename it into place."""
    if not _PIL_AVAILABLE:
        raise RuntimeError("Pillow not installed — cannot bake")

    def build(tmp: pathlib.Path) -> None:
        var_stats = {}
        for var, (mean, count) in fields.items():
            g32 = np.ascontiguousarray(mean, dtype="float32")
            rgba = _bgc.encode_with(g32[::-1, :], VARS[var])  # N -> S rows for the texture
            _Image.fromarray(rgba, "RGBA").save(tmp / f"{var}.png", format="PNG", optimize=True)
            with open(tmp / f"{var}.npz", "wb") as fh:
                np.savez_compressed(fh, v=g32, n=np.ascontiguousarray(count, dtype="uint8"))
            var_stats[var] = _bgc.array_stats(g32)
        meta = {"month": month, "grid": geometry, "stats": var_stats,
                "baked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **extra}
        (tmp / "meta.json").write_text(json.dumps(meta))  # last: completeness marker

    _bgc.publish_month(CACHE_DIR, month, build)


# ──────────────────────────────────────────────────────────────────────────────
# Upstream access
# ──────────────────────────────────────────────────────────────────────────────

def _open(product: str, dataset_key: str):
    if _copernicusmarine is None:
        raise RuntimeError("copernicusmarine not installed — cannot bake")
    creds = _bgc._credentials()  # fail with the plain message before touching the client
    return _copernicusmarine.open_dataset(
        dataset_id=PRODUCTS[product]["datasets"][dataset_key],
        variables=[SRC_VAR[dataset_key]], **creds)


def time_axis(ds) -> dict[str, object]:
    return _bgc.time_axis(ds)


def plan_months(axes: dict) -> tuple[str, dict[str, str]]:
    """(newest month, month -> product key) from the datasets' own time axes.

    `axes[product][dataset_key]` is that dataset's month -> time-value mapping. A month
    is available from a product when BOTH variables have it there; the multi-year
    product wins when both products have the month."""
    avail: dict[str, set[str]] = {}
    for product, per in axes.items():
        sets = [set(a) for a in per.values()]
        avail[product] = set.intersection(*sets) if sets else set()
    union = set().union(*avail.values()) if avail else set()
    if not union:
        raise UpstreamError("neither product offers a month for both variables")
    chosen = {m: next(p for p in PRODUCTS if m in avail.get(p, ())) for m in union}
    return max(union), chosen


def fetch_month(opened: dict, axes: dict, month: str, product: str) -> tuple[dict, dict]:
    """Read and coarsen every variable for `month` BEFORE anything is written, one
    variable at a time. Any failure raises, so the caller never holds a partial set."""
    fields: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    geo = None
    for var, cfg in VARS.items():
        key = cfg["dataset"]
        ds = opened[product][key]
        src = SRC_VAR[key]
        if src not in ds:
            raise UpstreamError(f"variable {src!r} missing from the {product} dataset")
        da = ds[src].sel(time=axes[product][key][month])
        g = block_geometry(np.asarray(da["latitude"].values), np.asarray(da["longitude"].values))
        if geo is None:
            geo = g
        elif g["grid"] != geo["grid"]:
            raise UpstreamError(f"{var}: grid differs from the other variable")
        if not bool(np.all(np.diff(da["latitude"].values) > 0)):
            raise UpstreamError("latitude axis is not ascending")
        fields[var] = coarsen_field(da, geo)
    return fields, geo["grid"]


def bake_month(opened: dict, axes: dict, month: str, product: str) -> None:
    fields, grid = fetch_month(opened, axes, month, product)
    p = PRODUCTS[product]
    _write_month(month, fields, grid, {
        "product_key": product, "product": p["id"], "product_label": p["label"],
        "doi": p["doi"], "datasets": p["datasets"],
        "time_stamp": str(axes[product]["plankton"][month])[:10],
        "block": f"{BLOCK}x{BLOCK} mean of 1/24 degree cells, NaN ignored",
    })


def sync_months(force: bool = False) -> dict:
    """Bring the cache up to date. Blocking; run in a thread.

    Newest month and the product of each month are read from the datasets' own time
    axes, never from the clock or an assumed lag. Wanted = the newest month and the 11
    before it. A month already complete is left alone unless `force` or the product that
    should supply it has changed (near-real-time -> multi-year once reprocessed)."""
    if not _PIL_AVAILABLE or _copernicusmarine is None:
        raise RuntimeError("copernicusmarine / Pillow not installed — cannot bake")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    opened: dict = {p: {} for p in PRODUCTS}
    try:
        for product in PRODUCTS:
            for key in SRC_VAR:
                opened[product][key] = _open(product, key)
        axes = {p: {k: time_axis(ds) for k, ds in per.items()} for p, per in opened.items()}
        newest, chosen = plan_months(axes)
        wanted = [m for m in months_back(newest, MONTHS_KEPT) if m in chosen]
        have = set(complete_months())

        def current(m: str) -> bool:
            meta = read_month_meta(m) if m in have else None
            return meta is not None and meta.get("product_key") == chosen[m]

        todo = [m for m in wanted if force or not current(m)]
        baked: list[str] = []
        failed: dict[str, str] = {}
        for month in todo:  # newest first: the most useful month lands first
            try:
                bake_month(opened, axes, month, chosen[month])
                baked.append(month)
                log.info("ocean_colour: baked %s from %s", month, chosen[month])
            except Exception as exc:
                failed[month] = f"{type(exc).__name__}: {exc}"
                log.warning("ocean_colour: %s not written (previous months kept): %s", month, exc)
        prune_old()
        return {"newest": newest, "wanted": wanted, "baked": baked, "failed": failed,
                "products": {m: chosen[m] for m in wanted}, "on_disk": complete_months()}
    finally:
        for per in opened.values():
            for ds in per.values():
                try:
                    ds.close()
                except Exception:  # pragma: no cover
                    pass


# ──────────────────────────────────────────────────────────────────────────────
# Reading: point lookup and meta
# ──────────────────────────────────────────────────────────────────────────────

_GRID_CACHE: dict[tuple[str, str], tuple[int, np.ndarray, np.ndarray]] = {}


def load_grid(var: str, month: str) -> tuple[np.ndarray, np.ndarray] | None:
    """(float32 mean, uint8 valid-cell count) for (var, month), cached by file mtime so a
    re-bake by the worker process is picked up by the web process without a restart."""
    p = _month_dir(month) / f"{var}.npz"
    try:
        mtime = p.stat().st_mtime_ns
    except FileNotFoundError:
        return None
    hit = _GRID_CACHE.get((var, month))
    if hit is not None and hit[0] == mtime:
        return hit[1], hit[2]
    with np.load(p) as z:
        v = np.asarray(z["v"], dtype="float32")
        n = np.asarray(z["n"], dtype="uint8")
    if len(_GRID_CACHE) >= 8:
        _GRID_CACHE.clear()
    _GRID_CACHE[(var, month)] = (mtime, v, n)
    return v, n


def point_value(var: str, lat: float, lon: float, month: str | None = None) -> dict:
    """Value of the nearest 0.25 degree cell. Raises KeyError (unknown var), LookupError
    (month not on disk). status: ok | no_data (no valid satellite cell in the block) |
    not_covered (outside the grid). A missing value is None, never 0."""
    if var not in VARS:
        raise KeyError(var)
    months = complete_months()
    if month is None:
        if not months:
            raise LookupError("nothing baked yet")
        month = months[-1]
    elif month not in months:
        raise LookupError(f"month {month} not available")
    cfg = VARS[var]
    meta = read_month_meta(month)
    g = meta["grid"]
    out = {"var": var, "month": month, "lat": lat, "lon": lon, "unit": cfg["unit"],
           "value_field": cfg["field"], cfg["field"]: None, "status": "not_covered",
           "valid_fraction": None, "product_key": meta.get("product_key"),
           "product_label": meta.get("product_label")}
    half = g["step"] / 2
    if lat < g["lat0"] - half or lat >= g["lat_max"] + half:
        return out
    if g["lon_global"]:
        col = int(np.floor((lon - g["lon0"]) / g["step"] + 0.5)) % g["n_lon"]
    else:
        if lon < g["lon0"] - half or lon >= g["lon_max"] + half:
            return out
        col = int(np.floor((lon - g["lon0"]) / g["step"] + 0.5))
    row = int(np.floor((lat - g["lat0"]) / g["step"] + 0.5))
    row = min(max(row, 0), g["n_lat"] - 1)
    col = min(max(col, 0), g["n_lon"] - 1)
    loaded = load_grid(var, month)
    if loaded is None:
        raise LookupError(f"grid for {var} {month} not available")
    grid, count = loaded
    v = float(grid[row, col])
    out["cell"] = {"lat": g["lat0"] + row * g["step"],
                   "lon": ((g["lon0"] + col * g["step"] + 180.0) % 360.0) - 180.0
                   if g["lon_global"] else g["lon0"] + col * g["step"]}
    out["valid_fraction"] = round(int(count[row, col]) / float(BLOCK * BLOCK), 4)
    if not np.isfinite(v):
        out["status"] = "no_data"
        out["reason"] = NO_DATA_REASON
        return out
    out[cfg["field"]] = v
    out["status"] = "ok"
    return out


def build_meta() -> dict:
    """Payload of /v1/ocean-colour/meta, read from disk on every call."""
    months = complete_months()
    metas = {m: read_month_meta(m) for m in months}
    latest = metas[months[-1]] if months else None
    variables = []
    if latest is not None:
        for key, c in VARS.items():
            variables.append({
                "key": key, "label": c["label"], "unit": c["unit"], "field": c["field"],
                "scale": c["scale"], "vmin": c["vmin"], "vmax": c["vmax"],
                "cmap": c["cmap"], "ramp": _bgc.ramp_hex(c["cmap"]),
                "ticks": _bgc.tick_list_for(c), "note": c["note"],
                "stats": latest["stats"].get(key),
            })
    return {
        "layer": LAYER_ID, "months": months, "latest": months[-1] if months else None,
        "month_products": {m: metas[m].get("product_key") for m in months},
        "variables": variables, "grid": latest["grid"] if latest else None,
        "products": {k: {"id": p["id"], "title": p["title"], "label": p["label"],
                         "doi": p["doi"], "doi_url": p["doi_url"], "url": p["url"]}
                     for k, p in PRODUCTS.items()},
        "licence_url": LICENCE_URL, "attribution": ATTRIBUTION, "caveat": CAVEAT,
    }
