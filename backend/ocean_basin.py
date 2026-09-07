# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Ocean basin from coordinates — a derivation, deliberately allowed to abstain.

Seamount SEO pages carried one description across all 594 indexed pages, varying
only in digits the searcher had already typed, and asserting *"Biodiversity
hotspot and potential cobalt-crust mining target"* for every feature regardless
of evidence. Measured 2026-08-17: 0.8 % CTR at average position 7.9, against
13.9 % for `/about` at position 5.7.

The honest fix is to say **where** the seamount is. Yesson et al. (2011) is a
morphology-derived census — most of these features are unnamed, and a name that
is not in the source may never be invented. A basin, by contrast, follows from
latitude and longitude, so it is derived rather than made up.

## This is an approximation of the IHO limits, and it abstains rather than guess

Real IHO sea limits are polygons. What follows is a boundary-line approximation,
which is adequate for a one-line "where is this" clause and is wrong nowhere
that matters at that resolution — but it is NOT a substitute for a spatial join,
and nothing beyond page copy should consume it.

`basin_for` returns `None` wherever the answer would be a guess: latitudes
between 30° N and 66.5° N across Asia, longitudes inside the Indonesian
archipelago at the Indian/Pacific transition, and anything outside valid
coordinate ranges. Callers must render **no location clause** in that case —
never "undefined", never a nearest-neighbour guess. That abstention is the
feature, not a gap to be closed later.

Boundaries used, and why:

* **Arctic Ocean** — north of the Arctic Circle (66.5° N). The IHO boundary is
  more intricate; the circle is defensible, citable, and never places a feature
  in the wrong hemisphere.
* **Southern Ocean** — south of 60° S, the IHO (2000) definition.
* **Atlantic / Indian** — the 20° E meridian of Cape Agulhas, the IHO limit.
* **Indian / Pacific** — 146.82° E (South East Cape, Tasmania) south of 10° S,
  the IHO limit. North of that the boundary threads the Indonesian seas, so the
  region between 100° E and 130° E above 10° S returns `None`.
* **Atlantic / Pacific in the Americas** — latitude-dependent, because the
  isthmus moves: −100° above 15° N (so the Gulf of Mexico reads Atlantic),
  −83° across Panama and Colombia, and −70° in the south, approaching the 67° W
  Drake Passage limit.
* **Mediterranean Sea** — boxed out explicitly. Without it a Mediterranean
  seamount would read "Atlantic Ocean", which is simply false.

Validated against the live `seamounts` table (37,889 rows) — see
`backend/tests/test_ocean_basin.py`.
"""

from __future__ import annotations

ARCTIC_CIRCLE = 66.5
SOUTHERN_OCEAN_LIMIT = -60.0
AGULHAS_MERIDIAN = 20.0
TASMANIA_MERIDIAN = 146.82


def _americas_boundary(lat: float) -> float:
    """Longitude separating Atlantic from Pacific through the Americas."""
    if lat >= 15.0:
        return -100.0  # Gulf of Mexico stays Atlantic; Pacific coast lies west
    if lat >= 0.0:
        return -83.0   # Panama / Costa Rica
    return -70.0       # South America, approaching the 67° W Drake Passage limit


def _is_mediterranean(lat: float, lon: float) -> bool:
    return 30.0 <= lat <= 46.0 and -6.0 <= lon <= 36.0


def basin_for(lat: float | None, lon: float | None) -> str | None:
    """Return the ocean basin for a coordinate, or None if it would be a guess.

    None is a valid, expected answer. Callers must omit the location clause
    entirely rather than substitute a placeholder.
    """
    if lat is None or lon is None:
        return None
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return None

    if lat >= ARCTIC_CIRCLE:
        return "Arctic Ocean"
    if lat <= SOUTHERN_OCEAN_LIMIT:
        return "Southern Ocean"
    if _is_mediterranean(lat, lon):
        return "Mediterranean Sea"

    # Asia between the Mediterranean and the Pacific is land at these latitudes;
    # a coordinate landing here is more likely bad data than a real basin.
    if lat > 30.0 and AGULHAS_MERIDIAN <= lon < 100.0:
        return None

    # The Indian/Pacific transition through the Indonesian archipelago is a
    # polygon problem, not a meridian. Abstain rather than pick a side.
    if lat > -10.0 and 100.0 <= lon <= 130.0:
        return None

    if lon >= _americas_boundary(lat) and lon <= AGULHAS_MERIDIAN:
        return "Atlantic Ocean"

    east_limit = TASMANIA_MERIDIAN if lat <= -10.0 else 130.0
    if AGULHAS_MERIDIAN < lon <= east_limit:
        return "Indian Ocean"

    return "Pacific Ocean"
