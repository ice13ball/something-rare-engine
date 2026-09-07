# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Parse ONC's RADCPTS (RDI ADCP Time Series) netCDF data product.

Why this module exists: ONC's `scalardata/location` endpoint does NOT expose
depth-resolved ADCP data. Asking it for `amplitudebeam1` at a real ADCP returns
`does not have propertyCode` — those devices publish only engineering scalars
(pressure, pitch, roll, heading, sound speed, temperature). The depth-binned
profile lives in the `RADCPTS` data product, ordered asynchronously through
`dataProductDelivery`. See `backend/tests/fixtures/onc_adcp/SCHEMA_NOTES.md`.

`build_backscatter_strip` is pure (plain sequences in, plain lists out) so it is
testable without xarray/netCDF4. `load_adcp_timeseries` is the thin file-opening shim and
imports xarray lazily — same split as `services/currents_bake.py`.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

# ONC-side ensemble averaging period. 86400 / 900 = 96 buckets in a 24 h window,
# which is the strip width the panel has always drawn.
ENSEMBLE_PERIOD_S = 900

# The product code is per-device (RDI → RADCPTS, Nortek → NTS) and must be resolved
# against ONC's /dataProducts, not guessed — see onc_dataproduct.pick_product_code.
# Both share the variables this parser reads, so only the extension is fixed here.
DATA_PRODUCT_EXT = "nc"

# The variable we render. dB, averaged across the beams by ONC (4 on RDI, 3 on
# Nortek) — physically meaningful, unlike per-beam `intens_beam*` in instrument counts.
BACKSCATTER_VAR = "meanBackscatter"
BACKSCATTER_UNITS = "dB"


def _cell(v: Any) -> float | None:
    """NaN/±inf/None → None. Mirrors `onc_ingest.adcp_cell`; a gap must stay a gap."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def build_backscatter_strip(
    values: Sequence[Sequence[Any]],
    depths: Sequence[Any],
    times: Sequence[Any],
) -> dict:
    """Turn RADCPTS `meanBackscatter(depth, time)` into `strip[time][bin]`.

    Two transformations, both load-bearing:

    1. **Transpose.** The product is indexed `(depth, time)`; the panel indexes
       `strip[timeIdx][binIdx]`.
    2. **Sort bins shallow → deep.** ONC's `depth` coordinate is DESCENDING
       (index 0 is the deepest bin), while `AdcpHeatmap` paints `binIdx = 0` at
       the top under a "surface" label. Without the sort the heatmap renders
       upside down — and still looks entirely plausible, which is why this is
       asserted in the tests rather than left to a comment.

    Returns `{"depths": [...ascending m...], "times": [...ISO...], "strip": [[...]]}`.
    Cells are `float | None`; `None` is a gap and must never be coerced to 0.0
    (0 dB is a real backscatter value).
    """
    n_depth = len(depths)
    n_time = len(times)
    if n_depth == 0 or n_time == 0:
        return {"depths": [], "times": [], "strip": []}

    order = sorted(range(n_depth), key=lambda i: float(depths[i]))  # shallow → deep

    strip = [[_cell(values[d][t]) for d in order] for t in range(n_time)]
    return {
        "depths": [round(float(depths[i]), 3) for i in order],
        "times": [_iso(t) for t in times],
        "strip": strip,
    }


def _iso(t: Any) -> str:
    """numpy.datetime64 / datetime / str → second-resolution ISO string."""
    s = str(t)
    return s[:19] if len(s) >= 19 else s


def load_adcp_timeseries(path: str) -> dict:
    """Open a RADCPTS/NTS netCDF and return the same dict as `build_backscatter_strip`.

    xarray is imported here, not at module scope, so the pure builder above stays
    importable (and testable) on a machine without netCDF4.
    """
    import xarray as xr  # lazy: heavy, absent in the test env

    with xr.open_dataset(path) as ds:
        if BACKSCATTER_VAR not in ds.variables:
            raise KeyError(f"{path}: no {BACKSCATTER_VAR!r} (vars: {list(ds.variables)[:8]})")
        da = ds[BACKSCATTER_VAR]
        if da.dims != ("depth", "time"):
            raise ValueError(f"{path}: expected dims ('depth','time'), got {da.dims}")
        return build_backscatter_strip(da.values, ds["depth"].values, ds["time"].values)
