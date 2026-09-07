# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Area-Export adapter for the Cumulative Human Impact FieldSource.

`routers/export.py` `_field_rows` dispatches continuous field samplers through a
fixed contract: `_load_grid(var)` (positional var) then `sample(var, lat, lon, lev)`
(the GLODAP-style branch). The native `chi_impact` module is single-variable and
depth-free, so its `_load_grid()` / `sample(lat, lon)` signatures don't match.

This thin shim adapts them WITHOUT changing the CHI feature contract used by the
map layer and the /v1/chi/* endpoints. It exposes the same `_Grid` (with `.lats`
/`.lons`, no `.depths`) so `has_depth=False` yields a single `levels=[None]` pass,
and ignores the surplus var/lev arguments.
"""
from services import chi_impact


def _load_grid(_var: str = "impact"):
    """Return the CHI grid (ignores the var arg — CHI has a single variable)."""
    return chi_impact._load_grid()


def sample(_var: str, lat: float, lon: float, _lev=None):
    """Nearest CHI index at (lat, lon); var/depth args are ignored."""
    return chi_impact.sample(lat, lon)
