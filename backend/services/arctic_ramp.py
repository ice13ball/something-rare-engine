# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Pure colour ramp for the arctic-catchments choropleth raster.

MUST stay in sync with ARCTIC_CATCHMENT_RAMP in frontend/src/components/Map3D.tsx.
"""
from __future__ import annotations
import math

ARCTIC_VARS = ("ocs_mean", "oc_tot", "runoff_mean", "pf_frac", "t_2m_mean")

# (min, max, lo_rgb, hi_rgb)
_RAMP: dict[str, tuple[float, float, tuple[int, int, int], tuple[int, int, int]]] = {
    "ocs_mean":    (50.0,  115.0, (255, 247, 236), (127, 39, 4)),
    "oc_tot":      (0.0,   0.006, (247, 252, 253), (0, 68, 27)),
    "runoff_mean": (0.0,   1.6,   (247, 251, 255), (8, 48, 107)),
    "pf_frac":     (0.0,   1.0,   (255, 255, 229), (49, 54, 149)),
    "t_2m_mean":   (250.0, 282.0, (5, 48, 97),     (165, 0, 38)),
}
_MUTED = (100, 116, 139)


def arctic_catchment_color(value, variable: str) -> tuple[int, int, int, int]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return (*_MUTED, 90)
    mn, mx, lo, hi = _RAMP[variable]
    if mx == mn:
        return (*_MUTED, 170)
    t = (value - mn) / (mx - mn)
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    lerp = lambda a, b: int(a + (b - a) * t + 0.5)  # round-half-up = JS Math.round (channels ≥ 0)
    return (lerp(lo[0], hi[0]), lerp(lo[1], hi[1]), lerp(lo[2], hi[2]), 170)
