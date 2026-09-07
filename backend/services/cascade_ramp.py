# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Per-variable colour ramps for the CASCADE interpolated grid.
Domains are the real p2–p98 ranges of CASCADE v2 (see plan Global Constraints).
Keep in sync with the frontend legend ramp labels.
"""
from __future__ import annotations

CASCADE_VARS = ("oc", "tn", "d13c", "d14c")
_ALPHA = 220

# sequential: (lo_rgb, hi_rgb); diverging: (lo_rgb, mid_rgb, hi_rgb)
RAMPS: dict[str, dict] = {
    "oc":   {"domain": (0.2, 2.0),      "kind": "seq",  "stops": ((255, 247, 188), (0, 90, 50))},
    "tn":   {"domain": (0.03, 0.25),    "kind": "seq",  "stops": ((253, 224, 221), (122, 1, 119))},
    "d13c": {"domain": (-27.0, -20.0),  "kind": "div",  "stops": ((33, 102, 172), (247, 247, 247), (178, 24, 43))},
    "d14c": {"domain": (-750.0, -100.0),"kind": "div",  "stops": ((44, 17, 95), (158, 154, 200), (252, 255, 164))},
}


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def cascade_color(value, variable):
    if value is None:
        return (0, 0, 0, 0)
    try:
        v = float(value)
    except (TypeError, ValueError):
        return (0, 0, 0, 0)
    if v <= -9990:
        return (0, 0, 0, 0)
    spec = RAMPS.get(variable) or RAMPS["oc"]
    lo, hi = spec["domain"]
    t = 0.0 if hi == lo else max(0.0, min(1.0, (v - lo) / (hi - lo)))
    if spec["kind"] == "seq":
        r, g, b = _lerp(spec["stops"][0], spec["stops"][1], t)
    else:
        lo_rgb, mid_rgb, hi_rgb = spec["stops"]
        r, g, b = _lerp(lo_rgb, mid_rgb, t * 2) if t < 0.5 else _lerp(mid_rgb, hi_rgb, (t - 0.5) * 2)
    return (r, g, b, _ALPHA)
