# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Intra-package shared constants for `domains/fields/`.

Not a domain module itself — no `router`, no `clear_caches()`, not registered
in `domains/__init__.py`'s `CACHE_CLEARING_DOMAINS`. Exists solely so
`carbon.py`, `habitat.py` and `climatology.py` can share one definition of a
constant without importing each other (the architecture's "no sub-module may
import another domain" rule) and without duplicating it three times (the
`domains/__init__.py` module docstring's own lesson from Phase 2, where
`geo_context` was given its own copy of a shared TTL cache dict instead of one
extracted definition).

`from ._common import X` from a sibling sub-module is an intra-package import,
not a domain-to-domain edge — it doesn't touch the one-way rule. Kept out of
`fields/__init__.py` on purpose: that file does `from . import carbon, habitat,
climatology, currents`, so a sub-module importing back from `__init__.py`
would be circular.
"""

# Shared by 8 hex-grid endpoints across carbon.py (carbon_hexes, acid_hexes,
# co2_hexes, carbon_unified_hexes), habitat.py (seabed_hexes, chi_hexes) and
# climatology.py (woa_hexes, oxygen_hexes) — every consumer of this query left
# main.py in Task 5, so it moved here rather than being orphaned there.
_HEX_CELLS_SQL = ("SELECT ST_Y(ST_Centroid(geom)) AS lat, ST_X(ST_Centroid(geom)) AS lon, "
                  "ST_AsGeoJSON(geom) AS gj FROM density_hex_cells")
