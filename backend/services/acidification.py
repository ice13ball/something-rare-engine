# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Ocean Acidification (modeled): GLODAP OmegaA/OmegaC fields + derived aragonite
saturation-horizon depth. Reads GLODAP's authoritative Ω (never recomputes via PyCO2SYS).

Heavy deps (xarray/PIL) imported lazily so this stays importable in test envs.
Ω fields: GLODAP v2.2016b (Lauvset et al. 2016; Key et al. 2015). Horizon depth: platform-derived.
"""
from __future__ import annotations
import glob as _glob
import math, os, pathlib
import numpy as np
from services import glodap_carbon  # reuse holdings + normalize_lon

CACHE_DIR = pathlib.Path(os.getenv("ACID_CACHE_DIR", "/var/cache/abyssal-acidification"))
BAKE_DIR  = CACHE_DIR / "baked"

CITATION = (
    "Ω fields: GLODAPv2.2016b Mapped Climatology — Lauvset et al. 2016 "
    "(ESSD 8:325, doi:10.5194/essd-8-325-2016); Key et al. 2015 (NDP-093). "
    "Aragonite saturation-horizon depth: platform-derived from GLODAP OmegaA."
)

DISPLAY_DEPTHS: list[int] = [0, 200, 500, 1000, 2000, 3000, 4000]

ACID_VARS: dict[str, dict] = {
    "aragonite": {"nc_file": "GLODAPv2.2016b.OmegaA.nc", "nc_var": "OmegaA",
                  "units": "Ω", "vmin": 0.5, "center": 1.0, "vmax": 4.0,
                  "cmap": "div_acid", "kind": "diverging",
                  "label": "Aragonite saturation (ΩA)"},
    "calcite":   {"nc_file": "GLODAPv2.2016b.OmegaC.nc", "nc_var": "OmegaC",
                  "units": "Ω", "vmin": 0.8, "center": 1.0, "vmax": 6.0,
                  "cmap": "div_acid", "kind": "diverging",
                  "label": "Calcite saturation (ΩC)"},
    "horizon":   {"nc_file": None, "nc_var": None,
                  "units": "m", "vmin": 0.0, "center": None, "vmax": 4000.0,
                  "cmap": "seq_horizon", "kind": "horizon",
                  "label": "Aragonite saturation-horizon depth"},
    "horizon-shift": {"nc_file": None, "nc_var": None,
                      "units": "m", "vmin": 0.0, "center": None, "vmax": 400.0,
                      "cmap": "seq_shift", "kind": "shift", "depths": [],
                      "label": "Aragonite horizon shift since preindustrial"},
}

_RAMPS: dict[str, list[tuple[float, tuple[int, int, int]]]] = {
    # RdBu diverging: red = corrosive (Ω<1), white = Ω≈1, blue = supersaturated (Ω>1)
    "div_acid":    [(0.0, (178, 24, 43)), (0.5, (247, 247, 247)), (1.0, (33, 102, 172))],
    # shallow horizon (0) = alarming dark red, deep = paler/calmer muted teal
    "seq_horizon": [(0.0, (128, 0, 38)),  (0.5, (200, 120, 60)),  (1.0, (90, 170, 165))],
    # shoaling magnitude: pale (no change) -> deep magenta (large shoaling)
    "seq_shift": [(0.0, (247, 240, 245)), (0.5, (197, 106, 168)), (1.0, (109, 15, 92))],
}
_HORIZON_SAFE = (200, 220, 240)  # always-supersaturated (math.inf) → pale-blue "safe"

def _lerp(c0, c1, t):
    return tuple(int(round(c0[i] + (c1[i] - c0[i]) * t)) for i in range(3))

def _ramp_rgb(cmap: str, t: float):
    stops = _RAMPS[cmap]; t = min(1.0, max(0.0, t))
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]; t1, c1 = stops[i + 1]
        if t <= t1:
            frac = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return _lerp(c0, c1, frac)
    return stops[-1][1]

def _diverging_norm(v: float, vmin: float, center: float, vmax: float) -> float:
    if v <= center:
        span = (center - vmin) or 1.0
        return 0.5 * min(1.0, max(0.0, (v - vmin) / span))
    span = (vmax - center) or 1.0
    return 0.5 + 0.5 * min(1.0, max(0.0, (v - center) / span))

def encode_diverging_to_rgba(arr, vmin, center, vmax, cmap):
    h, w = arr.shape
    rgba = np.zeros((h, w, 4), dtype="uint8")
    for y in range(h):
        for x in range(w):
            v = arr[y, x]
            if np.isnan(v):
                continue
            r, g, b = _ramp_rgb(cmap, _diverging_norm(float(v), vmin, center, vmax))
            rgba[y, x] = (r, g, b, 255)
    return rgba

def encode_horizon_to_rgba(arr, vmin, vmax):
    h, w = arr.shape
    rgba = np.zeros((h, w, 4), dtype="uint8")
    span = (vmax - vmin) or 1.0
    for y in range(h):
        for x in range(w):
            v = arr[y, x]
            if np.isnan(v):
                continue
            if np.isinf(v):
                rgba[y, x] = (*_HORIZON_SAFE, 255); continue
            r, g, b = _ramp_rgb("seq_horizon", min(1.0, max(0.0, (float(v) - vmin) / span)))
            rgba[y, x] = (r, g, b, 255)
    return rgba

def _ramp_hex(cmap):
    return [{"pos": t, "hex": "#%02x%02x%02x" % rgb} for t, rgb in _RAMPS[cmap]]

def build_meta():
    return {
        "variables": [
            {"key": k, "label": v["label"], "units": v["units"], "vmin": v["vmin"],
             "center": v["center"], "vmax": v["vmax"], "cmap": v["cmap"], "kind": v["kind"],
             "ramp": _ramp_hex(v["cmap"]),
             "depths": (DISPLAY_DEPTHS if v["kind"] not in ("horizon", "shift") else [])}
            for k, v in ACID_VARS.items()
        ],
        "depths": DISPLAY_DEPTHS,
        "citation": CITATION,
    }

_GRID_CACHE: dict = {}
_HORIZON_CACHE: dict = {}

def saturation_horizon(omega_col, depths):
    """Depth (m) where Omega crosses below 1.0, linearly interpolated between the
    bracketing levels. `math.inf` = every valid level is supersaturated (Omega >= 1
    all the way down); `None` = no valid (non-NaN) data at all. NaN levels are
    skipped rather than breaking the interpolation across the gap."""
    pairs = [(float(d), float(o)) for d, o in zip(depths, omega_col)
             if o is not None and not math.isnan(o)]
    if not pairs:
        return None
    prev_d, prev_o = pairs[0]
    if prev_o < 1.0:
        return prev_d                       # shallowest valid level already corrosive
    for d, o in pairs[1:]:
        if o < 1.0:
            return prev_d + (1.0 - prev_o) / (o - prev_o) * (d - prev_d)
        prev_d, prev_o = d, o
    return math.inf                          # never crosses → always supersaturated

def _shift_value(horizon_pi, horizon_today):
    """Metres the aragonite saturation horizon has shoaled: horizon_PI - horizon_today.

    Returns None when either side is missing or infinite. `math.inf` means the column never
    crosses Omega=1, so a difference against it has no physical meaning — and it would
    serialise as the bare token `Infinity`, which is invalid JSON (RFC 8259). Small negative
    results are numerical noise from the two independent interpolations and are clamped to 0;
    a preindustrial ocean cannot have had a shallower horizon than today's.
    """
    if horizon_pi is None or horizon_today is None:
        return None
    pi = float(horizon_pi)
    today = float(horizon_today)
    if not (math.isfinite(pi) and math.isfinite(today)):
        return None
    return max(0.0, pi - today)

def _load_grid(var):
    # Area Export passes fs.vars[0] verbatim (underscore "horizon_shift") to both sample()
    # and this grid-shape lookup (routers/export.py _load_any_grid); ACID_VARS only has the
    # hyphenated "horizon-shift" key, so alias here too — not just in sample().
    if var == "horizon_shift":
        var = "horizon-shift"
    if var in _GRID_CACHE:
        return _GRID_CACHE[var]
    cfg = ACID_VARS[var]
    # horizon has no NetCDF of its own — it's derived from OmegaA. Reuse the
    # aragonite grid's axes (lats/lons/depths) so callers that only need the grid
    # shape (e.g. the Area-Export axis inspection) work; horizon VALUES come from
    # horizon_grid()/sample("horizon", …), not from this grid's data cube.
    if cfg["nc_file"] is None:
        g = _load_grid("aragonite")
        _GRID_CACHE[var] = g
        return g
    import xarray as xr
    matches = _glob.glob(str(glodap_carbon.RAW_DIR / "**" / cfg["nc_file"]), recursive=True) \
              or _glob.glob(str(glodap_carbon.RAW_DIR / cfg["nc_file"]))
    if not matches:
        _GRID_CACHE[var] = None; return None
    ds = xr.open_dataset(matches[0])
    depth_name = "Depth" if "Depth" in ds.variables else "depth_surface"
    arr = np.asarray(ds[cfg["nc_var"]].values, dtype="float32")
    while arr.ndim > 3:
        arr = arr.squeeze(axis=0)
    lats = np.asarray(ds["lat"].values, dtype="float64")
    lons = np.asarray(ds["lon"].values, dtype="float64")
    depths = np.asarray(ds[depth_name].values, dtype="float64")
    arr, lons = glodap_carbon.normalize_lon(arr, lons)
    g = glodap_carbon._Grid(lats, lons, depths, arr)
    _GRID_CACHE[var] = g
    return g

def horizon_grid():
    if "h" in _HORIZON_CACHE:
        return _HORIZON_CACHE["h"]
    g = _load_grid("aragonite")
    if g is None:
        return None
    nd, ny, nx = g.data.shape
    out = np.full((ny, nx), np.nan, dtype="float32")
    depths = list(g.depths)
    for yi in range(ny):
        for xi in range(nx):
            h = saturation_horizon(list(g.data[:, yi, xi]), depths)
            out[yi, xi] = np.nan if h is None else (np.inf if math.isinf(h) else h)
    _HORIZON_CACHE["h"] = out
    return out

# Epoch -> GLODAP DIC file/variable. Both epochs go through the IDENTICAL CO2SYS
# configuration below so the horizon difference carries no method bias.
_EPOCH_DIC = {
    "today": ("GLODAPv2.2016b.TCO2.nc", "TCO2"),
    "pi":    ("GLODAPv2.2016b.PI_TCO2.nc", "PI_TCO2"),
}

# Lueker et al. 2000. This is also PyCO2SYS 1.8's default and what vme_sdm.omega_arag uses
# implicitly — set EXPLICITLY so a future library default change cannot silently move the
# numbers. Validated 2026-07-20 against GLODAP's published OmegaA over 3,000 random cells:
# median +0.00167, IQR [-0.0087, +0.0088]. opt_k_carbonic=12 was clearly worse (-0.0117).
_OPT_K_CARBONIC = 10

_OMEGA_CACHE: dict = {}
_HSHIFT_CACHE: dict = {}


def _aux_grid(fn: str, var: str):
    """Load one auxiliary GLODAP field as a raw ndarray on the shared grid."""
    matches = _glob.glob(str(glodap_carbon.RAW_DIR / "**" / fn), recursive=True) \
              or _glob.glob(str(glodap_carbon.RAW_DIR / fn))
    if not matches:
        return None
    import xarray as xr  # lazy — heavy, only imported once a real file is found
    ds = xr.open_dataset(matches[0])
    arr = np.asarray(ds[var].values, dtype="float64")
    while arr.ndim > 3:
        arr = arr.squeeze(axis=0)
    lons = np.asarray(ds["lon"].values, dtype="float64")
    ds.close()
    arr, _ = glodap_carbon.normalize_lon(arr, lons)
    return arr


def omega_grid(epoch: str):
    """Reconstruct aragonite saturation state from GLODAP DIC + TAlk via PyCO2SYS.

    epoch: "today" (TCO2) or "pi" (PI_TCO2). Returns a glodap_carbon._Grid or None.
    NOT used for the shipped `aragonite` field view — that reads GLODAP's published OmegaA
    directly. This exists only for the two horizon reconstructions and the QC.
    """
    if epoch in _OMEGA_CACHE:
        return _OMEGA_CACHE[epoch]
    if epoch not in _EPOCH_DIC:
        raise ValueError(f"unknown epoch {epoch!r}")
    base = _load_grid("aragonite")          # supplies lats/lons/depths axes
    if base is None:
        _OMEGA_CACHE[epoch] = None
        return None
    fn, var = _EPOCH_DIC[epoch]
    dic  = _aux_grid(fn, var)
    talk = _aux_grid("GLODAPv2.2016b.TAlk.nc", "TAlk")
    temp = _aux_grid("GLODAPv2.2016b.temperature.nc", "temperature")
    sal  = _aux_grid("GLODAPv2.2016b.salinity.nc", "salinity")
    po4  = _aux_grid("GLODAPv2.2016b.PO4.nc", "PO4")
    si   = _aux_grid("GLODAPv2.2016b.silicate.nc", "silicate")
    if any(a is None for a in (dic, talk, temp, sal, po4, si)):
        log.warning("acidification: omega_grid(%s) missing an input field", epoch)
        _OMEGA_CACHE[epoch] = None
        return None

    import PyCO2SYS as pyco2  # lazy — heavy
    nd, ny, nx = dic.shape
    pres = np.repeat(np.asarray(base.depths, dtype="float64"), ny * nx).reshape(nd, ny, nx)
    ok = (np.isfinite(dic) & np.isfinite(talk) & np.isfinite(temp)
          & np.isfinite(sal) & np.isfinite(po4) & np.isfinite(si))
    out = np.full((nd, ny, nx), np.nan, dtype="float32")
    if ok.any():
        res = pyco2.sys(
            par1=talk[ok], par1_type=1,      # 1 = total alkalinity
            par2=dic[ok],  par2_type=2,      # 2 = dissolved inorganic carbon
            temperature=temp[ok], salinity=sal[ok], pressure=pres[ok],
            total_phosphate=po4[ok], total_silicate=si[ok],
            opt_k_carbonic=_OPT_K_CARBONIC,
        )
        out[ok] = np.asarray(res["saturation_aragonite"], dtype="float32")
    g = glodap_carbon._Grid(base.lats, base.lons, base.depths, out)
    _OMEGA_CACHE[epoch] = g
    return g


def horizon_recon_grid(epoch: str):
    """Saturation-horizon depth from the RECONSTRUCTED Omega for one epoch."""
    key = f"h_{epoch}"
    if key in _HSHIFT_CACHE:
        return _HSHIFT_CACHE[key]
    g = omega_grid(epoch)
    if g is None:
        return None
    nd, ny, nx = g.data.shape
    out = np.full((ny, nx), np.nan, dtype="float32")
    depths = list(g.depths)
    for yi in range(ny):
        for xi in range(nx):
            col = [float(v) for v in g.data[:, yi, xi]]
            h = saturation_horizon(col, depths)
            out[yi, xi] = np.nan if h is None else (np.inf if math.isinf(h) else h)
    _HSHIFT_CACHE[key] = out
    return out


def horizon_shift_grid():
    """Metres of shoaling: horizon_PI - horizon_today, both RECONSTRUCTED (same method)."""
    if "shift" in _HSHIFT_CACHE:
        return _HSHIFT_CACHE["shift"]
    hp = horizon_recon_grid("pi")
    ht = horizon_recon_grid("today")
    if hp is None or ht is None:
        return None
    ny, nx = hp.shape
    out = np.full((ny, nx), np.nan, dtype="float32")
    for yi in range(ny):
        for xi in range(nx):
            v = _shift_value(float(hp[yi, xi]), float(ht[yi, xi]))
            out[yi, xi] = np.nan if v is None else v
    _HSHIFT_CACHE["shift"] = out
    return out


def qc_omega_vs_published(n: int = 3000) -> dict:
    """Compare our reconstructed present-day Omega against GLODAP's published OmegaA.

    This is the validation that licenses the whole reconstruction: if our CO2SYS
    configuration reproduces GLODAP's own field, the preindustrial reconstruction (which has
    no published counterpart) is trustworthy by the same configuration. Reported in the panel
    and the methods note. Baseline measured 2026-07-20: median +0.00167, IQR ±0.009.
    """
    pub = _load_grid("aragonite")
    rec = omega_grid("today")
    if pub is None or rec is None:
        return {"n": 0, "median": None, "iqr": [None, None], "max_abs": None}
    ok = np.isfinite(pub.data) & np.isfinite(rec.data)
    idx = np.argwhere(ok)
    if not len(idx):
        return {"n": 0, "median": None, "iqr": [None, None], "max_abs": None}
    rng = np.random.default_rng(0)
    sel = idx[rng.choice(len(idx), size=min(n, len(idx)), replace=False)]
    di, yi, xi = sel[:, 0], sel[:, 1], sel[:, 2]
    d = rec.data[di, yi, xi].astype("float64") - pub.data[di, yi, xi].astype("float64")
    return {"n": int(len(d)), "median": float(np.median(d)),
            "iqr": [float(np.percentile(d, 25)), float(np.percentile(d, 75))],
            "max_abs": float(np.max(np.abs(d)))}


def sample(var, lat, lon, depth):
    if var == "horizon_shift":
        var = "horizon-shift"
    if var == "horizon-shift":
        g = _load_grid("aragonite")
        if g is None:
            return None
        sg = horizon_shift_grid()
        if sg is None:
            return None
        yi = glodap_carbon._nearest_idx(g.lats, lat)
        xi = glodap_carbon._nearest_idx(g.lons, lon)
        v = sg[yi, xi]
        return None if np.isnan(v) else float(v)
    if var == "horizon":
        g = _load_grid("aragonite")
        if g is None:
            return None
        hg = horizon_grid()
        yi = glodap_carbon._nearest_idx(g.lats, lat)
        xi = glodap_carbon._nearest_idx(g.lons, lon)
        v = hg[yi, xi]
        if np.isnan(v):
            return None
        return math.inf if np.isinf(v) else float(v)
    g = _load_grid(var)
    if g is None:
        return None
    di = glodap_carbon._nearest_idx(g.depths, depth)
    yi = glodap_carbon._nearest_idx(g.lats, lat)
    xi = glodap_carbon._nearest_idx(g.lons, lon)
    v = g.data[di, yi, xi]
    return None if np.isnan(v) else float(v)

# ── Download / bake ───────────────────────────────────────────────────────────
import logging, tempfile

log = logging.getLogger("acidification")

def ensure_holdings(force: bool = False) -> bool:
    return glodap_carbon.ensure_holdings(force)   # OmegaA/OmegaC are in the same tarball

def baked_png_path(var: str, depth) -> pathlib.Path | None:
    if var == "horizon":
        p = BAKE_DIR / "horizon.png"
    elif var == "horizon-shift":
        p = BAKE_DIR / "horizon_shift.png"
    else:
        p = BAKE_DIR / var / f"{depth}.png"
    return p if p.exists() else None

def encode_shift_to_rgba(arr, vmin, vmax):
    """Sequential ramp over shoaling metres. NaN (incl. never-crossing columns) stays
    transparent — 'no shift value here', which is not the same as 'zero shift'."""
    h, w = arr.shape
    rgba = np.zeros((h, w, 4), dtype="uint8")
    span = (vmax - vmin) or 1.0
    for y in range(h):
        for x in range(w):
            v = arr[y, x]
            if np.isnan(v) or np.isinf(v):
                continue
            r, g, b = _ramp_rgb("seq_shift", min(1.0, max(0.0, (float(v) - vmin) / span)))
            rgba[y, x] = (r, g, b, 255)
    return rgba

def _save_png(rgba, out: pathlib.Path):
    from PIL import Image  # lazy
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=out.parent, suffix=".png.tmp", delete=False) as tmp:
        tmp_path = pathlib.Path(tmp.name)
    Image.fromarray(rgba, "RGBA").save(tmp_path, format="PNG", optimize=True)
    os.replace(tmp_path, out)

def bake_all() -> int:
    if not ensure_holdings():
        return 0
    _GRID_CACHE.clear(); _HORIZON_CACHE.clear()
    _OMEGA_CACHE.clear(); _HSHIFT_CACHE.clear()
    n = 0
    for var in ("aragonite", "calcite"):
        g = _load_grid(var)
        if g is None:
            continue
        cfg = ACID_VARS[var]
        for d in DISPLAY_DEPTHS:
            di = glodap_carbon._nearest_idx(g.depths, d)
            field = np.flipud(g.data[di])                       # row 0 = north
            rgba = encode_diverging_to_rgba(field, cfg["vmin"], cfg["center"], cfg["vmax"], cfg["cmap"])
            _save_png(rgba, BAKE_DIR / var / f"{d}.png"); n += 1
    hg = horizon_grid()
    if hg is not None:
        rgba = encode_horizon_to_rgba(np.flipud(hg), 0.0, 4000.0)
        _save_png(rgba, BAKE_DIR / "horizon.png"); n += 1
    sg = horizon_shift_grid()
    if sg is not None:
        rgba = encode_shift_to_rgba(np.flipud(sg), 0.0, 400.0)
        _save_png(rgba, BAKE_DIR / "horizon_shift.png"); n += 1
    return n
